"""Plan G F004 (G4) — backend runtime evidence capture.

Capture-only adapter (D002). Provider-adapter based per D010 — the
collector itself is provider-neutral; per-provider modules implement
the live capture surface. Three providers in v1:

- ``firebase``: production adapter. Lazy-imports ``firebase_admin``
  when present; auth resolved from operator-supplied pointer (D014:
  ``adc`` / path / ``env:NAME``). When the SDK isn't installed, the
  provider raises :class:`BackendProviderError` and the collector
  emits a typed skip.
- ``supabase``: provider SLOT only in v1. Always raises
  :class:`BackendProviderError` with a deferred-wiring message — the
  fixture-driven swap seam is the supported test path.
- ``generic``: HTTP GET / log-file read / JSONL stream read using
  stdlib (``urllib.request``, file IO). Always available; no SDK
  required.

Public surface:

    BackendEvidenceCollector(plan_dir, providers=None, clock=None)
        .collect(journey, *, provider=None, project=None, auth=None,
                 session_config) -> list[EvidenceRef]

    BackendProbe(name, kind, params)
    BackendSessionConfig(provider, probes, ...)
    BackendProvider / BackendProviderSession (Protocols)
    BackendProviderError (raised by providers; wrapped into skip)

**Capture-only (D002):** no audit / scoring. EvidenceRef artifacts
are the contract; F2 consumes them later.

**Project-agnostic (D004):** no project-name special cases. The
``provider`` / ``project`` / ``auth`` are operator-supplied per call
OR pulled from per-project ``runtime_evidence.backend`` config (D015
— global config never names a default backend). No global tier.

**No new credential storage (D005 + D014):** ``auth`` is always a
POINTER, never a credential value. Allowed shapes:
- ``adc``: Application Default Credentials (gcloud / firebase
  default).
- path-only: ``/abs/path/to/sa.json``, ``./relative/sa.json``,
  ``~/path/sa.json``.
- ``env:NAME``: env var holding either a path or JSON contents
  (provider decides).

**Skip discipline:** when the provider isn't registered, the SDK
isn't installed, the auth pointer is missing, or any probe fails,
the collector writes a typed
``EvidenceRef(type='log', note='skipped: ...')`` rather than raising.
Callers always get a list back.

The doctor checks ``backend_firebase`` / ``backend_supabase`` /
``backend_generic`` (registered at module import via
:mod:`config.doctor_registry`) report ``warn`` when their SDK isn't
available — never ``fail``. Projects that don't target a backend see
the warn but aren't blocked from dispatch.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from dontpanic_orchestrate.config import (
    doctor_registry,
)
from dontpanic_orchestrate.config import (
    resolvers as _resolvers,
)
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

# ──────────────────────────────  pointer + config shapes  ──────────────────────────────


_ENV_POINTER_RE = re.compile(r"^env:[A-Z_][A-Z0-9_]*$")
_POINTER_PATH_PREFIXES: tuple[str, ...] = ("/", "./", "../", "~/")


def _is_credential_pointer(value: str) -> bool:
    """Mirror the F006 setup.is_credential_pointer rule (D014). Local
    copy so this module doesn't depend on setup.py at import time."""
    if not value or not isinstance(value, str):
        return False
    if value == "adc":
        return True
    if _ENV_POINTER_RE.match(value):
        return True
    return value.startswith(_POINTER_PATH_PREFIXES)


BackendProviderName = Literal["firebase", "supabase", "generic"]


@dataclass(frozen=True)
class BackendProbe:
    """One unit of backend capture. ``kind`` is a free-form string
    interpreted by the chosen provider; ``params`` is provider-specific."""

    name: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class BackendSessionConfig:
    """Operator-supplied backend session configuration. ``provider``
    discriminates which provider is consulted."""

    provider: BackendProviderName
    probes: list[BackendProbe] = field(default_factory=list)
    provider_options: dict[str, Any] = field(default_factory=dict)
    """Pass-through dict the chosen provider may consume (timeout,
    headers, max_results, etc.). Keys are provider-defined."""


class BackendProviderError(Exception):
    """Raised by providers when a session can't be opened or a probe
    can't capture. The collector wraps this into a skip-reason
    EvidenceRef so callers never see the raw exception."""


class BackendProviderSession(Protocol):
    """A live provider session. Per-probe: ``execute_probe`` returns
    the raw bytes + the EvidenceType to record. ``close`` releases any
    connection / SDK handle."""

    def execute_probe(self, probe: BackendProbe) -> tuple[bytes, EvidenceType]: ...
    def close(self) -> None: ...


class BackendProvider(Protocol):
    """Pluggable provider. v1 ships :class:`_FirebaseProvider`,
    :class:`_SupabaseProvider`, :class:`_GenericProvider`; tests +
    operators pass any callable object satisfying this protocol."""

    name: str

    def open_session(
        self,
        *,
        project: str | None,
        auth: str | None,
        session_config: BackendSessionConfig,
    ) -> BackendProviderSession: ...


# ──────────────────────────────  generic provider (always available)  ──────────────────────────────


class _GenericProviderSession:
    """No live connection state — each probe opens its own resource
    and closes it. ``close`` is a no-op."""

    def __init__(self, *, options: dict[str, Any]):
        self._options = dict(options)

    def execute_probe(self, probe: BackendProbe) -> tuple[bytes, EvidenceType]:
        if probe.kind == "http_get":
            return self._http_get(probe)
        if probe.kind == "log_file":
            return self._log_file(probe)
        if probe.kind == "jsonl_stream":
            return self._jsonl_stream(probe)
        raise BackendProviderError(
            f"generic provider doesn't understand probe.kind={probe.kind!r}; "
            f"supported: http_get, log_file, jsonl_stream"
        )

    def close(self) -> None:
        return

    def _http_get(self, probe: BackendProbe) -> tuple[bytes, EvidenceType]:
        url = probe.params.get("url")
        if not url:
            raise BackendProviderError(
                f"http_get probe {probe.name!r} missing required param 'url'"
            )
        headers = probe.params.get("headers") or {}
        if not isinstance(headers, dict):
            raise BackendProviderError(f"http_get probe {probe.name!r} 'headers' must be a dict")
        timeout = probe.params.get("timeout") or self._options.get("timeout") or 10
        # Lazy import — ``urllib.request`` is stdlib so always available.
        from urllib.error import URLError
        from urllib.request import Request, urlopen

        req = Request(url, headers=headers)  # noqa: S310  # operator-supplied URL passed through urllib.Request
        try:
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — operator-supplied URL
                payload = resp.read()
        except (URLError, TimeoutError) as exc:
            raise BackendProviderError(f"http_get probe {probe.name!r} failed: {exc}") from exc
        return payload, EvidenceType.file

    def _log_file(self, probe: BackendProbe) -> tuple[bytes, EvidenceType]:
        path_str = probe.params.get("path")
        if not path_str:
            raise BackendProviderError(
                f"log_file probe {probe.name!r} missing required param 'path'"
            )
        path = Path(path_str).expanduser()
        if not path.is_file():
            raise BackendProviderError(f"log_file probe {probe.name!r}: path {path} does not exist")
        payload = path.read_bytes()
        max_bytes = probe.params.get("max_bytes")
        if isinstance(max_bytes, int) and max_bytes > 0 and len(payload) > max_bytes:
            payload = payload[-max_bytes:]
        return payload, EvidenceType.log

    def _jsonl_stream(self, probe: BackendProbe) -> tuple[bytes, EvidenceType]:
        path_str = probe.params.get("path")
        if not path_str:
            raise BackendProviderError(
                f"jsonl_stream probe {probe.name!r} missing required param 'path'"
            )
        path = Path(path_str).expanduser()
        if not path.is_file():
            raise BackendProviderError(
                f"jsonl_stream probe {probe.name!r}: path {path} does not exist"
            )
        # Validate each line parses as JSON; degrade unreadable lines to a
        # `# malformed` comment so the artifact stays readable.
        out_lines: list[str] = []
        max_lines = probe.params.get("max_lines")
        for i, raw in enumerate(path.read_text().splitlines()):
            if isinstance(max_lines, int) and max_lines > 0 and i >= max_lines:
                break
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                json.loads(stripped)
            except json.JSONDecodeError:
                out_lines.append(f"# malformed: {stripped}")
                continue
            out_lines.append(stripped)
        return ("\n".join(out_lines) + "\n").encode("utf-8"), EvidenceType.log


class _GenericProvider:
    name = "generic-provider"

    def open_session(
        self,
        *,
        project: str | None,
        auth: str | None,
        session_config: BackendSessionConfig,
    ) -> BackendProviderSession:
        # Generic provider doesn't need project / auth — they're informational
        # only. Validate auth pointer shape if supplied (D014 belt-and-suspenders;
        # the F006 CLI already enforces this at write time).
        if auth is not None and not _is_credential_pointer(auth):
            raise BackendProviderError(
                "refusing to open session with non-pointer auth (D014); got value "
                "that is not 'adc', 'env:NAME', or a path"
            )
        return _GenericProviderSession(options=session_config.provider_options)


# ──────────────────────────────  firebase provider  ──────────────────────────────


class _FirebaseProvider:
    """Firebase provider. Lazy-imports ``firebase_admin``; production
    session adapter (Firestore doc fetch, query, Cloud Logging read)
    is left as a follow-up. v1 validates auth pointer shape, then
    raises :class:`BackendProviderError` so the collector emits a
    typed skip when no operator-supplied stub provider is registered.
    Reuses the existing F022 SA discipline — we never store a
    credential value here, only the operator's pointer.
    """

    name = "firebase-provider"

    _ALLOWED_KINDS: tuple[str, ...] = (
        "firestore_doc",
        "firestore_query",
        "cloud_logging_read",
    )

    def open_session(
        self,
        *,
        project: str | None,
        auth: str | None,
        session_config: BackendSessionConfig,
    ) -> BackendProviderSession:
        if not project:
            raise BackendProviderError(
                "firebase provider requires 'project'. Set "
                "runtime_evidence.backend.project in per-project config "
                "(`dontpanic project config set runtime_evidence.backend.project "
                "<id>`) or pass per-call."
            )
        if not auth:
            raise BackendProviderError(
                "firebase provider requires 'auth' pointer. Set "
                "runtime_evidence.backend.auth to 'adc', 'env:NAME', or "
                "a service-account path (D014: pointer only, never a "
                "credential value)."
            )
        if not _is_credential_pointer(auth):
            raise BackendProviderError(
                "firebase provider refused to open session: 'auth' must be a "
                "pointer shape (D014). Got non-pointer value."
            )
        # Validate any probe kinds upfront so the operator gets a clear
        # error before the deferred-wiring skip rather than after.
        for probe in session_config.probes:
            if probe.kind not in self._ALLOWED_KINDS:
                raise BackendProviderError(
                    f"firebase provider doesn't understand probe.kind="
                    f"{probe.kind!r}; supported: {self._ALLOWED_KINDS}"
                )
        # Lazy SDK probe — used for the warn-only doctor check too.
        if importlib.util.find_spec("firebase_admin") is None:
            raise BackendProviderError(
                "firebase_admin SDK not installed. Install via "
                "`pip install firebase-admin` to enable the default "
                "Firebase provider, or pass an explicit provider to "
                "BackendEvidenceCollector."
            )
        # Production wiring of the firebase_admin session adapter is left
        # as a follow-up plan. The fixture-driven swap seam (operator-
        # supplied BackendProvider) is the supported path during Plan G v1.
        raise BackendProviderError(
            "firebase production session adapter not wired in Plan G v1. "
            "Pass an explicit provider to BackendEvidenceCollector for "
            "now; production firebase_admin wiring lands in a follow-up "
            "plan."
        )


# ──────────────────────────────  supabase provider (slot only)  ──────────────────────────────


class _SupabaseProvider:
    """Supabase provider — SLOT only in Plan G v1 per D010 lock. Always
    raises :class:`BackendProviderError`; the fixture-driven swap seam
    (operator-supplied provider) is the only supported test path until
    Supabase production wiring lands in its own plan.
    """

    name = "supabase-provider"

    def open_session(
        self,
        *,
        project: str | None,
        auth: str | None,
        session_config: BackendSessionConfig,
    ) -> BackendProviderSession:
        if auth is not None and not _is_credential_pointer(auth):
            raise BackendProviderError(
                "supabase provider refused to open session: 'auth' must be a "
                "pointer shape (D014). Got non-pointer value."
            )
        raise BackendProviderError(
            "Supabase provider is a slot in Plan G v1 (D010 lock). Pass an "
            "explicit provider to BackendEvidenceCollector to wire your own "
            "Supabase session, or wait for the production adapter to land."
        )


# ──────────────────────────────  collector  ──────────────────────────────


_DEFAULT_CLOCK = lambda: datetime.now(timezone.utc)  # noqa: E731


def _default_providers() -> dict[str, BackendProvider]:
    return {
        "firebase": _FirebaseProvider(),
        "supabase": _SupabaseProvider(),
        "generic": _GenericProvider(),
    }


class BackendEvidenceCollector:
    """Goal Governance V1 G4 — backend runtime evidence capture.

    Per Plan G D002 (capture-only) + D003 (evidence path) + D004
    (project-agnostic) + D005 (no credential storage) + D010
    (provider-adapter pattern; Firebase first, Supabase slot, Generic
    fallback) + D015 (runtime_evidence is project-scoped). Honors
    per-call overrides and falls through to per-project
    ``runtime_evidence.backend`` config via
    :func:`config.resolvers.resolve_runtime_evidence`.
    """

    def __init__(
        self,
        plan_dir: Path,
        providers: dict[str, BackendProvider] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plan_dir = Path(plan_dir).resolve()
        self._providers: dict[str, BackendProvider] = (
            dict(providers) if providers is not None else _default_providers()
        )
        self._clock = clock if clock is not None else _DEFAULT_CLOCK

    def collect(
        self,
        journey: str,
        *,
        provider: str | None = None,
        project: str | None = None,
        auth: str | None = None,
        session_config: BackendSessionConfig,
    ) -> list[EvidenceRef]:
        """Capture backend evidence for one journey. Returns a list of
        ``EvidenceRef`` instances pointing at artifacts written under
        ``evidence/goal-governance/post_impl/backend/<journey>/``.

        Per-call kwargs win over per-project ``runtime_evidence.backend``
        config which wins over None (no global tier per D015). The
        ``provider`` kwarg, if supplied, overrides
        ``session_config.provider``.

        Never raises — provider lookup failures + per-probe failures
        + skip-eligible conditions are recorded as skip-reason
        EvidenceRefs so callers always get a list back.
        """
        if not journey:
            return [
                self._write_skip(
                    "_no-journey",
                    "skipped: empty journey identifier passed to collector",
                    provider_name=provider or session_config.provider,
                )
            ]

        # Resolve config layers: per-call > project > none. The
        # per-call overrides feed resolve_runtime_evidence's per_call
        # dict so the rest of the resolution chain takes care of
        # itself.
        per_call: dict[str, Any] = {}
        if provider is not None:
            per_call["provider"] = provider
        if project is not None:
            per_call["project"] = project
        if auth is not None:
            per_call["auth"] = auth
        resolved = _resolvers.resolve_runtime_evidence(
            self._plan_dir, "backend", per_call=per_call or None
        )
        eff_provider = resolved.get("provider") or session_config.provider
        eff_project = resolved.get("project")
        eff_auth = resolved.get("auth")

        provider_obj = self._providers.get(eff_provider)
        if provider_obj is None:
            return [
                self._write_skip(
                    journey,
                    f"skipped: unknown provider {eff_provider!r}; "
                    f"registered: {sorted(self._providers)}",
                    provider_name=eff_provider,
                )
            ]

        try:
            session = provider_obj.open_session(
                project=eff_project,
                auth=eff_auth,
                session_config=session_config,
            )
        except BackendProviderError as exc:
            return [
                self._write_skip(
                    journey,
                    f"skipped: provider init failed: {exc}",
                    provider_name=provider_obj.name,
                )
            ]
        except Exception as exc:  # noqa: BLE001
            return [
                self._write_skip(
                    journey,
                    f"skipped: unexpected provider fault: {type(exc).__name__}: {exc}",
                    provider_name=provider_obj.name,
                )
            ]

        refs: list[EvidenceRef] = []
        try:
            for probe in session_config.probes:
                refs.extend(self._capture_probe(session, journey, probe, provider_obj))
        finally:
            self._safe_close(session)
        if not refs:
            refs.append(
                self._write_skip(
                    journey,
                    "skipped: provider session opened but no probes were configured",
                    provider_name=provider_obj.name,
                )
            )
        return refs

    # ──────────────────────────────  per-probe capture  ──────────────────────────────

    def _capture_probe(
        self,
        session: BackendProviderSession,
        journey: str,
        probe: BackendProbe,
        provider_obj: BackendProvider,
    ) -> list[EvidenceRef]:
        try:
            payload, evidence_type = session.execute_probe(probe)
        except BackendProviderError as exc:
            return [
                self._write_skip(
                    journey,
                    f"skipped: probe {probe.name!r} ({probe.kind}) failed: {exc}",
                    provider_name=provider_obj.name,
                    step_name=probe.name,
                )
            ]
        if not isinstance(payload, bytes):
            payload = bytes(payload)
        filename = self._probe_filename(probe, evidence_type)
        return [
            self._write_artifact(
                journey,
                filename,
                payload,
                evidence_type,
                provider_obj.name,
                note=f"probe={probe.name}; kind={probe.kind}",
            )
        ]

    @staticmethod
    def _probe_filename(probe: BackendProbe, evidence_type: EvidenceType) -> str:
        # Normalize probe name to a safe filename component.
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", probe.name) or "probe"
        ext_map = {
            EvidenceType.file: ".bin",
            EvidenceType.log: ".log",
            EvidenceType.test_output: ".txt",
            EvidenceType.screenshot: ".png",
        }
        ext = ext_map.get(evidence_type, ".bin")
        return f"probe-{safe}{ext}"

    # ──────────────────────────────  artifact + skip writers  ──────────────────────────────

    def _journey_dir(self, journey: str) -> Path:
        return goal_governance_evidence_path(self._plan_dir, "post_impl", f"backend/{journey}")

    def _write_artifact(
        self,
        journey: str,
        filename: str,
        payload: bytes,
        evidence_type: EvidenceType,
        captured_by: str,
        *,
        note: str | None = None,
    ) -> EvidenceRef:
        out_path = self._journey_dir(journey) / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        rel_uri = str(out_path.relative_to(self._plan_dir))
        return EvidenceRef(
            type=evidence_type,
            uri=rel_uri,
            hash=f"sha256:{digest}",
            captured_at=self._clock(),
            captured_by=captured_by,
            note=note,
        )

    def _write_skip(
        self,
        journey: str,
        reason: str,
        *,
        provider_name: str,
        step_name: str | None = None,
    ) -> EvidenceRef:
        suffix = f"-{step_name}" if step_name else ""
        filename = f"skip-reason{suffix}.txt"
        body = (
            f"reason: {reason}\n"
            f"provider: {provider_name}\n"
            f"journey: {journey}\n"
            f"step: {step_name or '(n/a)'}\n"
        )
        return self._write_artifact(
            journey,
            filename,
            body.encode("utf-8"),
            EvidenceType.log,
            provider_name,
            note=reason,
        )

    def _safe_close(self, session: BackendProviderSession) -> None:
        try:
            session.close()
        except BackendProviderError:
            return


# ──────────────────────────────  doctor checks  ──────────────────────────────


def _backend_firebase_check() -> doctor_registry.DoctorResult:
    """Soft availability probe for the Firebase provider — warns when
    ``firebase_admin`` isn't importable. Never returns ``fail``."""
    if importlib.util.find_spec("firebase_admin") is None:
        return doctor_registry.DoctorResult(
            name="backend_firebase",
            status="warn",
            detail="firebase_admin SDK not installed; firebase backend evidence unavailable",
        )
    return doctor_registry.DoctorResult(
        name="backend_firebase",
        status="pass",
        detail="firebase_admin importable",
    )


def _backend_supabase_check() -> doctor_registry.DoctorResult:
    """Supabase is a slot in v1 — always warn so operators see the
    deferred status. Never returns ``fail``."""
    has_sdk = importlib.util.find_spec("supabase") is not None
    detail = (
        "supabase SDK importable; provider is a slot in Plan G v1 (D010)"
        if has_sdk
        else "supabase SDK not installed; provider is a slot in Plan G v1 (D010)"
    )
    return doctor_registry.DoctorResult(
        name="backend_supabase",
        status="warn",
        detail=detail,
    )


def _backend_generic_check() -> doctor_registry.DoctorResult:
    """Generic provider uses stdlib only; always available."""
    return doctor_registry.DoctorResult(
        name="backend_generic",
        status="pass",
        detail="generic provider (stdlib http/log/jsonl) available",
    )


def _register_backend_doctor_checks() -> None:
    """Idempotent — also called from tests after registry resets so the
    backend checks survive F006's per-test ``_reset_for_tests`` autouse."""
    doctor_registry.register_doctor_check("backend_firebase", _backend_firebase_check)
    doctor_registry.register_doctor_check("backend_supabase", _backend_supabase_check)
    doctor_registry.register_doctor_check("backend_generic", _backend_generic_check)


_register_backend_doctor_checks()


__all__ = [
    "BackendEvidenceCollector",
    "BackendProbe",
    "BackendProvider",
    "BackendProviderError",
    "BackendProviderName",
    "BackendProviderSession",
    "BackendSessionConfig",
]
