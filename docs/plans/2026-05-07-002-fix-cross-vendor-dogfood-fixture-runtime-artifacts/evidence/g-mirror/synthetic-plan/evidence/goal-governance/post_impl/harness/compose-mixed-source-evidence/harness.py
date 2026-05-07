"""Plan G F005 (G5) — runtime evidence harness.

The integrating layer that composes G1+G2+G3+G4 adapters behind one
:class:`EvidenceCollector.collect(journey, sources=[...]) -> list[EvidenceRef]`
interface. Pure orchestration; zero source-specific logic in the core.

Public surface:

    EvidenceCollector(plan_dir, clock=None)
        .collect(journey, *, sources) -> list[EvidenceRef]

    EvidenceSource (Protocol): name + collect(journey) -> list[EvidenceRef]
    EvidenceSourceError (raised by sources; wrapped into harness skip)

    Adapter helpers (alongside the harness, NOT inside it):
      web_source(collector, base_url, session_config)
      ios_source(collector, *, simulator=None, scheme=None,
                 app_bundle_id=None, session_config)
      android_source(collector, *, package=None, adb_device_serial=None,
                     artifact_dir=None, session_config)
      backend_source(collector, *, provider=None, project=None,
                     auth=None, session_config)

**Core invariant — source-agnostic (D004 + D006):** the harness core
(the :class:`EvidenceCollector` class body) contains NO references to
specific sources (web / ios / android / backend / firebase / supabase
/ playwright / simctl / adb). Source identity is opaque — the harness
dispatches via the operator-supplied :class:`EvidenceSource` Protocol.
A greppable test in ``test_runtime_evidence_harness.py`` enforces this.

**Capture-only (D002):** harness performs orchestration only. No audit
/ scoring / pass-fail. Each source is responsible for its own capture
semantics; the harness collects and returns.

**Per-source failure handling:**
- Sources that return a list (including typed skip EvidenceRefs) are
  passed through unchanged — preserves G1-G4's skip discipline.
- Sources that raise any exception have their failure wrapped into a
  harness-level skip EvidenceRef written under
  ``evidence/goal-governance/post_impl/harness/<journey>/skip-source-<name>.txt``.

**Deterministic ordering:** refs are returned in source-iteration
order. Within a single source, refs are returned in the order the
source emitted them.

**Dedup:** refs with identical ``(uri, hash)`` are collapsed to the
first occurrence. Preserves order; later duplicates are dropped.

**Config layering separation:** the harness consumes
:class:`EvidenceSource` objects that are already config-bound — the
adapter helpers close over per-call kwargs at construction time.
This keeps source-specific config out of the harness core entirely.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from dontpanic_orchestrate.config import doctor_registry
from dontpanic_orchestrate.nested_orchestration import goal_governance_evidence_path

_SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[3] / ".claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[4] / "agent-conventions" / "schemas" / "v1.0",
]
for _candidate in _SCHEMA_CANDIDATES:
    if (_candidate / "models").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from models.features_model import EvidenceRef  # noqa: E402
from models.features_model import Type as EvidenceType  # noqa: E402

# ──────────────────────────────  source protocol  ──────────────────────────────


class EvidenceSourceError(Exception):
    """Raised by an :class:`EvidenceSource` when it cannot proceed.
    The harness wraps this (and any other exception) into a typed skip
    EvidenceRef so callers always get a list back."""


class EvidenceSource(Protocol):
    """A single source the harness knows how to dispatch to. The
    ``name`` is operator-defined (typically ``web`` / ``ios`` /
    ``android`` / ``backend`` but the harness never branches on it)
    and is used for the harness-level skip filename when this source
    raises."""

    name: str

    def collect(self, journey: str) -> list[EvidenceRef]: ...


# ──────────────────────────────  harness core  ──────────────────────────────


_DEFAULT_CLOCK = lambda: datetime.now(timezone.utc)  # noqa: E731

_HARNESS_SUBDIR = "harness"
"""The single subdir name the harness core knows about — used only for
its OWN skip emissions when a source raises. Never used for source
dispatch logic. The greppable invariant test confirms this is the
ONLY known-source identifier in the core."""


class EvidenceCollector:
    """Goal Governance V1 G5 — runtime evidence harness.

    Per Plan G D002 (capture-only) + D003 (evidence path) + D004
    (project-agnostic) + D006 (cross-vendor invariant inherited from
    F1; harness composes adapters, doesn't review them) + D015
    (runtime_evidence is project-scoped — surfaced by adapter helpers,
    not the core).

    The core's contract is intentionally tiny: iterate sources,
    forward exceptions to typed skip EvidenceRefs, dedupe, return.
    Source-specific behavior lives in the operator-supplied
    :class:`EvidenceSource` instances.
    """

    def __init__(
        self,
        plan_dir: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plan_dir = Path(plan_dir).resolve()
        self._clock = clock if clock is not None else _DEFAULT_CLOCK

    def collect(
        self,
        journey: str,
        *,
        sources: list[EvidenceSource],
    ) -> list[EvidenceRef]:
        """Capture evidence for one journey across N sources. Returns a
        flat list of ``EvidenceRef`` instances in source-iteration
        order, deduped by ``(uri, hash)``.

        Never raises — empty journey, empty sources, source-level
        exceptions all surface as typed skip EvidenceRefs so callers
        always get a list back.
        """
        if not journey:
            return [
                self._write_harness_skip(
                    "_no-journey",
                    source_name="_no-source",
                    reason="skipped: empty journey identifier passed to harness",
                )
            ]
        if not sources:
            return [
                self._write_harness_skip(
                    journey,
                    source_name="_no-sources",
                    reason="skipped: no sources supplied to harness",
                )
            ]

        collected: list[EvidenceRef] = []
        for source in sources:
            collected.extend(self._invoke_source(source, journey))
        return _dedupe_preserving_order(collected)

    # ──────────────────────────────  per-source dispatch  ──────────────────────────────

    def _invoke_source(
        self,
        source: EvidenceSource,
        journey: str,
    ) -> list[EvidenceRef]:
        """Call source.collect(journey). Wrap any exception into a
        typed harness-level skip. Sources that return a list (even an
        empty one or a list of typed skips) pass through unchanged."""
        source_name = getattr(source, "name", None) or "_unnamed-source"
        try:
            refs = source.collect(journey)
        except EvidenceSourceError as exc:
            return [
                self._write_harness_skip(
                    journey,
                    source_name=source_name,
                    reason=f"skipped: source raised: {exc}",
                )
            ]
        except Exception as exc:  # noqa: BLE001 — translate any source fault to skip
            return [
                self._write_harness_skip(
                    journey,
                    source_name=source_name,
                    reason=f"skipped: unexpected source fault: {type(exc).__name__}: {exc}",
                )
            ]
        if refs is None:
            return [
                self._write_harness_skip(
                    journey,
                    source_name=source_name,
                    reason="skipped: source returned None instead of a list",
                )
            ]
        if not isinstance(refs, list):
            return [
                self._write_harness_skip(
                    journey,
                    source_name=source_name,
                    reason=(
                        f"skipped: source returned {type(refs).__name__} instead of "
                        "list[EvidenceRef]"
                    ),
                )
            ]
        return refs

    # ──────────────────────────────  harness-level skip writer  ──────────────────────────────

    def _harness_journey_dir(self, journey: str) -> Path:
        return goal_governance_evidence_path(
            self._plan_dir, "post_impl", f"{_HARNESS_SUBDIR}/{journey}"
        )

    def _write_harness_skip(
        self,
        journey: str,
        *,
        source_name: str,
        reason: str,
    ) -> EvidenceRef:
        # Sanitize source_name into a filename-safe component so an
        # operator-supplied name with slashes or dots can't escape the
        # journey dir.
        safe_name = source_name.replace("/", "_").replace("\\", "_").replace("..", "_")
        filename = f"skip-source-{safe_name}.txt"
        body = f"reason: {reason}\nsource: {source_name}\njourney: {journey}\n"
        out_path = self._harness_journey_dir(journey) / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = body.encode("utf-8")
        out_path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        rel_uri = str(out_path.relative_to(self._plan_dir))
        return EvidenceRef(
            type=EvidenceType.log,
            uri=rel_uri,
            hash=f"sha256:{digest}",
            captured_at=self._clock(),
            captured_by="evidence-harness",
            note=reason,
        )


def _dedupe_preserving_order(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    """Drop refs with duplicate ``(uri, hash)``. First occurrence wins;
    later duplicates are removed. Preserves source-iteration order.

    Two refs with the same uri but different hashes are NOT deduped —
    that signals the same path was overwritten with different content
    by two sources, which the operator should see (both refs surface
    so F2 can flag the conflict)."""
    seen: set[tuple[str, str]] = set()
    out: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.uri, ref.hash)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


# ──────────────────────────────  adapter helpers (alongside, not inside)  ──────────────────────────────


@dataclass(frozen=True)
class _BoundSource:
    """A simple :class:`EvidenceSource` that closes over a callable
    and a name. Used by the adapter helpers below."""

    name: str
    _fn: Callable[[str], list[EvidenceRef]]

    def collect(self, journey: str) -> list[EvidenceRef]:
        return self._fn(journey)


def web_source(collector, base_url, session_config, *, name: str = "web") -> EvidenceSource:
    """Wrap a :class:`WebEvidenceCollector` into an :class:`EvidenceSource`
    bound to one (base_url, session_config) pair. The harness sees the
    bound source; the adapter-specific kwargs never enter the core."""

    def _collect(journey: str) -> list[EvidenceRef]:
        return collector.collect(journey, base_url=base_url, session_config=session_config)

    return _BoundSource(name=name, _fn=_collect)


def ios_source(
    collector,
    *,
    simulator: str | None = None,
    scheme: str | None = None,
    app_bundle_id: str | None = None,
    session_config,
    name: str = "ios",
) -> EvidenceSource:
    """Wrap an :class:`IosEvidenceCollector` into an :class:`EvidenceSource`."""

    def _collect(journey: str) -> list[EvidenceRef]:
        return collector.collect(
            journey,
            simulator=simulator,
            scheme=scheme,
            app_bundle_id=app_bundle_id,
            session_config=session_config,
        )

    return _BoundSource(name=name, _fn=_collect)


def android_source(
    collector,
    *,
    package: str | None = None,
    adb_device_serial: str | None = None,
    artifact_dir: Path | None = None,
    session_config,
    name: str = "android",
) -> EvidenceSource:
    """Wrap an :class:`AndroidEvidenceCollector` into an :class:`EvidenceSource`."""

    def _collect(journey: str) -> list[EvidenceRef]:
        return collector.collect(
            journey,
            package=package,
            adb_device_serial=adb_device_serial,
            artifact_dir=artifact_dir,
            session_config=session_config,
        )

    return _BoundSource(name=name, _fn=_collect)


def backend_source(
    collector,
    *,
    provider: str | None = None,
    project: str | None = None,
    auth: str | None = None,
    session_config,
    name: str = "backend",
) -> EvidenceSource:
    """Wrap a :class:`BackendEvidenceCollector` into an :class:`EvidenceSource`."""

    def _collect(journey: str) -> list[EvidenceRef]:
        return collector.collect(
            journey,
            provider=provider,
            project=project,
            auth=auth,
            session_config=session_config,
        )

    return _BoundSource(name=name, _fn=_collect)


# ──────────────────────────────  doctor check  ──────────────────────────────


def _evidence_harness_check() -> doctor_registry.DoctorResult:
    """The harness has no external dependencies — it composes the
    other adapters via Protocol. Always reports ``pass``; per-adapter
    readiness lives in their own doctor checks (web / ios / android /
    backend) which the harness does not duplicate here."""
    return doctor_registry.DoctorResult(
        name="evidence_harness",
        status="pass",
        detail="harness available; per-source readiness via adapter checks",
    )


def _register_harness_doctor_checks() -> None:
    """Idempotent — also called from tests after registry resets so
    the harness check survives F006's per-test ``_reset_for_tests``
    autouse."""
    doctor_registry.register_doctor_check("evidence_harness", _evidence_harness_check)


_register_harness_doctor_checks()


__all__ = [
    "EvidenceCollector",
    "EvidenceSource",
    "EvidenceSourceError",
    "android_source",
    "backend_source",
    "ios_source",
    "web_source",
]
