"""Plan 2026-06-21-001 F003 — detection predicate registry (status_probes + applies_when).

This is the **pure core** of the upgrade-readiness detection layer. A *predicate*
maps a stable key to a callable returning a :class:`PredicateResult`
(``{satisfied, detail, evidence_uri}``). Two namespaces, two roles:

* **status_probe** — the ONLY authority for whether a REQUIRED action is satisfied
  (the per-instance marker NEVER satisfies a required action, D004). Fails CLOSED:
  an undeterminable / unknown / raising status_probe resolves to ``satisfied=False``
  so a typo or a degraded read can never silently mark a migration done (D026).

* **applies_when** — gates whether an action is shown to THIS instance at all. Fails
  OPEN: an undeterminable / unknown / raising applies_when resolves to
  ``satisfied=True`` (the action APPLIES) so a typo can never silently HIDE required
  work (D026). For an applies_when result ``satisfied`` is read as *applies*.

Key invariants:

* :func:`canonical_discovery_registered_active` is an **OUTCOME** probe (D019): it is
  satisfied iff DontPanic resolves to ``registered_active`` via the canonical-discovery
  reconcile READ path. Evidence validity does NOT gate the outcome — a stale/malformed
  leftover backfill-evidence file can never flip an already-``registered_active``
  outcome to pending. The probe NEVER reads the evidence file.

* :func:`canonical_backfill_evidence_valid` is the SEPARATE evidence-consuming
  predicate (D019). It is the ONLY predicate evidence validity gates, used where the
  remaining work depends on that evidence and the outcome is not yet proven.

* NO-MUTATION CONTRACT (D028): every predicate is a strictly READ-ONLY observation.
  It MUST NOT write or modify registry, evidence, config, ledger, or any on-disk
  state. ``canonical_discovery_registered_active`` reuses ONLY the
  read/reconcile path of canonical-discovery, never a write path.

* No predicate is allowed to crash report assembly: :func:`resolve_status_probe` and
  :func:`resolve_applies_when` wrap every call so a raising predicate degrades to its
  fail direction (closed / open) instead of propagating.
"""

from __future__ import annotations

import datetime
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import canonical_discovery as cd
from dontpanic_orchestrate import canonical_evidence as ce
from dontpanic_orchestrate import global_config as gc
from dontpanic_orchestrate import invocation_ledger as il
from dontpanic_orchestrate import projects_registry
from dontpanic_orchestrate.projects_registry import Registry

_LOG = logging.getLogger(__name__)

#: Default backfill-evidence filename under ``$DONTPANIC_HOME`` (C4, mirrors
#: :data:`canonical_backfill.EVIDENCE_FILENAME`).
EVIDENCE_FILENAME = "canonical-backfill-evidence.json"


# ──────────────────────────────  result + context  ──────────────────────────────


@dataclass(frozen=True)
class PredicateResult:
    """The pinned predicate return shape ``{satisfied, detail, evidence_uri}``.

    * ``satisfied`` — for a status_probe: the required action is satisfied. For an
      applies_when: the action APPLIES to this instance.
    * ``detail`` — a human-readable explanation, ALWAYS populated (so a fail-closed /
      fail-open / unknown-key result is never an opaque bare boolean).
    * ``evidence_uri`` — optional pointer to the artifact the predicate observed.
    * ``error`` — True when this is a DEGRADED / fail-direction result (undeterminable
      read, unknown key, or a predicate that raised). A clean negative
      (e.g. "no registered_active", "no tracked projects", "evidence file absent") is
      NOT an error. F005 surfaces ``error`` so a typo/degradation is visible, never
      silently dropped (D026).
    """

    satisfied: bool
    detail: str
    evidence_uri: str | None = None
    error: bool = False


@dataclass
class PredicateContext:
    """Read-only inputs for predicate resolution, with dependency-injection seams.

    Every field defaults to ``None`` and is resolved at call time from the
    ``$DONTPANIC_HOME``-anchored real loaders, so production callers construct an
    empty ``PredicateContext()``. Tests inject ``registry`` / ``ledger_records`` /
    ``projection`` / ``evidence_path`` to drive each state deterministically without
    touching real on-disk state.

    NOTHING here is a writer: the context only carries data and read-only loaders.
    """

    #: ISO-8601 ``now`` for the reconcile recency window; resolved to current UTC.
    now: str | None = None
    #: Injected registry; else :func:`projects_registry.load_registry`.
    registry: Registry | None = None
    #: Injected parsed ledger records; else read from the invocation ledger.
    ledger_records: Sequence[Mapping[str, Any]] | None = None
    #: Injected reconcile projection (short-circuits the read path entirely).
    projection: Mapping[str, Any] | None = None
    #: Override the backfill-evidence path; else ``$DONTPANIC_HOME``/EVIDENCE_FILENAME.
    evidence_path: Path | None = None
    #: Override the reconcile decay/threshold policy (C5 defaults otherwise).
    policy: cd.DiscoveryPolicy | None = None
    #: The current DontPanic instance's ``canonical_repo_key`` — the identity the
    #: OUTCOME probe filters the projection by, so a DIFFERENT project being
    #: registered_active can never satisfy THIS instance's required action. When
    #: ``None`` it is resolved at call time by canonicalizing the running repo via
    #: the same read path the ledger writer uses (``None`` if undeterminable).
    self_canonical_key: str | None = None
    #: The current instance's registry name. Optional refinement used only to
    #: derive an honest not-satisfied reason (stale / path-missing / unresolved)
    #: when the running instance's registered path does not resolve to a canonical
    #: key. Never required for satisfaction (that is keyed on the canonical repo).
    self_registry_name: str | None = None


# ──────────────────────────────  read-only loaders  ──────────────────────────────


def _now_iso_utc() -> str:
    """Current UTC instant as an ISO-8601 ``...Z`` string for the reconcile policy."""
    return (
        datetime.datetime.now(tz=datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _now(ctx: PredicateContext) -> str:
    return ctx.now or _now_iso_utc()


def _load_registry(ctx: PredicateContext) -> Registry:
    if ctx.registry is not None:
        return ctx.registry
    return projects_registry.load_registry()


def _read_ledger_records(target: Path) -> list[dict[str, Any]]:
    """Read the invocation ledger into parsed records (read-only, lenient).

    A missing ledger yields no records; a malformed line is skipped rather than
    aborting. NEVER reads ``record.command`` (C6) — only structured records are
    returned and the F003 canonical-discovery adapters take it from there. Mirrors
    the F004 discover reader so the probe uses the identical read path."""
    if not target.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def _load_ledger_records(ctx: PredicateContext) -> Sequence[Mapping[str, Any]]:
    if ctx.ledger_records is not None:
        return ctx.ledger_records
    return _read_ledger_records(il.ledger_path())


def _evidence_path(ctx: PredicateContext) -> Path:
    if ctx.evidence_path is not None:
        return Path(ctx.evidence_path)
    return gc.dontpanic_home() / EVIDENCE_FILENAME


def _reconcile_projection(ctx: PredicateContext) -> Mapping[str, Any]:
    """Run the canonical-discovery reconcile READ path -> five-state projection (D028).

    An injected ``ctx.projection`` short-circuits the read entirely. Otherwise this
    loads the ledger + registry, builds the observed/registered adapters, and calls
    the PURE :func:`canonical_discovery.reconcile`. Every step is read-only: the
    ledger reader and registry loader only read, and ``reconcile`` performs no IO. No
    write path of canonical-discovery is ever reached."""
    if ctx.projection is not None:
        return ctx.projection
    records = _load_ledger_records(ctx)
    observed = cd.observed_canonical_from_ledger(records)
    reg = _load_registry(ctx)
    registered = cd.registered_canonical_from_registry(reg.projects)
    policy = ctx.policy or cd.DiscoveryPolicy()
    return cd.reconcile(registered, observed, _now(ctx), policy)


# ──────────────────────────────  self-instance identity  ──────────────────────────────


def _detect_repo_root(start: Path) -> Path:
    """First ancestor of ``start`` (inclusive) containing a ``.git`` entry, else
    ``start``. Mirrors the ledger writer's repo-root detection so the OUTCOME probe
    keys on the SAME canonical identity the writer stamps (read-only)."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def _self_canonical_key(ctx: PredicateContext) -> str | None:
    """The current DontPanic instance's ``canonical_repo_key`` (D019 identity).

    An injected ``ctx.self_canonical_key`` short-circuits the read. Otherwise this
    canonicalizes the running repo via the SAME read path the ledger writer uses
    (``git rev-parse`` only — no writes). Returns ``None`` when the running repo
    cannot be canonicalized (undeterminable identity); the OUTCOME probe treats
    that as fail-closed (D026)."""
    if ctx.self_canonical_key is not None:
        return ctx.self_canonical_key or None
    try:
        root = _detect_repo_root(Path.cwd())
        result = il.canonicalize_repo(root)
        canonical_root = result.get("canonical_root")
        if canonical_root is None:
            return None
        pair = il.make_path_pair(canonical_root)
        return pair["path_key"] if pair else None
    except Exception as exc:  # noqa: BLE001 — undeterminable self -> None (fail-closed upstream)
        _LOG.warning("could not resolve current DontPanic canonical identity: %s", exc)
        return None


def _self_registry_name(
    ctx: PredicateContext, projection: Mapping[str, Any], self_key: str | None
) -> str | None:
    """Best-effort registry name of the running instance, used ONLY to label an
    honest not-satisfied reason. Prefers an injected ``ctx.self_registry_name``;
    otherwise reads it from the projection's active/stale row that already matches
    ``self_key`` (no extra IO). ``None`` when it cannot be determined."""
    if ctx.self_registry_name is not None:
        return ctx.self_registry_name or None
    if self_key is None:
        return None
    for bucket in ("registered_active", "registered_stale"):
        for row in projection.get(bucket, []):
            if row.get("canonical_repo_key") == self_key:
                name = row.get("registry_name")
                return str(name) if name else None
    return None


def _row_is_self(
    row: Mapping[str, Any], self_key: str | None, self_name: str | None
) -> bool:
    """True iff ``row`` describes the running DontPanic instance — matched by
    ``canonical_repo_key`` (active/stale rows) or, as a fallback for the
    null-keyed path-missing/unresolved rows, by ``registry_name``."""
    if self_key is not None and row.get("canonical_repo_key") == self_key:
        return True
    if self_name is not None and row.get("registry_name") == self_name:
        return True
    return False


# ──────────────────────────────  status_probes  ──────────────────────────────


def _self_active_detail(rows: Sequence[Mapping[str, Any]]) -> str:
    names = [str(r.get("registry_name")) for r in rows if r.get("registry_name")]
    label = ", ".join(sorted(names)) if names else "(unnamed)"
    return f"DontPanic is registered_active (canonical repo: {label})"


def canonical_discovery_registered_active(ctx: PredicateContext | None = None) -> PredicateResult:
    """OUTCOME probe: satisfied iff THIS DontPanic instance resolves to
    ``registered_active`` (D019).

    Runs ONLY the canonical-discovery reconcile READ path, then filters the
    projection to the running instance's own identity (its ``canonical_repo_key``,
    resolved via the same read path the ledger writer uses). Satisfied iff the
    instance's OWN row is in ``registered_active`` — a DIFFERENT project being
    registered_active never satisfies this instance's required action.

    The evidence file is NEVER consulted here: a stale/malformed leftover
    backfill-evidence file does NOT flip an already-``registered_active`` outcome to
    pending (D019). When not satisfied the ``detail`` reflects the instance's OWN
    state — stale / path-missing / unresolved / not-registered. Fails CLOSED
    (``satisfied=False``, ``error=True``) on a read-path failure OR an
    undeterminable self-identity (D026)."""
    ctx = ctx or PredicateContext()
    try:
        projection = _reconcile_projection(ctx)
    except Exception as exc:  # noqa: BLE001 — fail-closed, never crash assembly (D026/D028)
        _LOG.warning("canonical_discovery reconcile read path failed: %s", exc)
        return PredicateResult(
            satisfied=False,
            detail=f"canonical-discovery reconcile read path failed; fail-closed: {exc}",
            error=True,
        )

    self_key = _self_canonical_key(ctx)
    self_name = _self_registry_name(ctx, projection, self_key)
    if self_key is None and self_name is None:
        # Undeterminable self-identity -> fail-closed (never satisfy on ambiguity).
        return PredicateResult(
            satisfied=False,
            detail=(
                "could not determine this DontPanic instance's canonical identity; "
                "fail-closed (not satisfied)"
            ),
            error=True,
        )

    active = [
        r for r in projection.get("registered_active", []) if _row_is_self(r, self_key, self_name)
    ]
    if active:
        return PredicateResult(satisfied=True, detail=_self_active_detail(active))

    # Not registered_active — derive an honest reason from THIS instance's own row
    # in the remaining buckets (another project's bucket is never consulted).
    if any(_row_is_self(r, self_key, self_name) for r in projection.get("registered_stale", [])):
        detail = "DontPanic is registered but stale (no recent qualifying usage); not registered_active"
    elif any(
        _row_is_self(r, self_key, self_name) for r in projection.get("registered_path_missing", [])
    ):
        detail = "DontPanic's registered project path is missing; not registered_active"
    elif any(
        _row_is_self(r, self_key, self_name) for r in projection.get("registered_unresolved", [])
    ):
        detail = "DontPanic's registered project path is unresolved; not registered_active"
    else:
        detail = "no registered entry resolves to this DontPanic instance; not registered_active"
    return PredicateResult(satisfied=False, detail=detail)


def canonical_backfill_evidence_valid(ctx: PredicateContext | None = None) -> PredicateResult:
    """Evidence-consuming predicate: satisfied iff the backfill evidence is shape-valid.

    This is the ONLY predicate that gates on evidence validity (D019). It is used where
    the remaining work depends on consuming the evidence and the outcome is not yet
    proven — it is NOT consulted by the outcome probe. Validates SHAPE only, via the
    F006 file-fatal contract (:func:`canonical_evidence.load_evidence_file`): a
    missing / unreadable / invalid / structurally-defective file -> ``satisfied=False``
    with a stable reason in ``detail``."""
    ctx = ctx or PredicateContext()
    path = _evidence_path(ctx)
    try:
        ce.load_evidence_file(path)
    except ce.EvidenceFatalError as exc:
        # A determinable negative (missing/invalid evidence). Fail-closed by virtue of
        # satisfied=False; only a genuinely undeterminable read is flagged error=True.
        degraded = exc.reason == ce.FATAL_UNREADABLE_FILE
        return PredicateResult(
            satisfied=False,
            detail=f"backfill evidence not valid ({exc.reason}): {exc}",
            evidence_uri=str(path),
            error=degraded,
        )
    except Exception as exc:  # noqa: BLE001 — any other read failure fails closed
        _LOG.warning("backfill evidence read failed: %s", exc)
        return PredicateResult(
            satisfied=False,
            detail=f"backfill evidence unreadable; fail-closed: {exc}",
            evidence_uri=str(path),
            error=True,
        )
    return PredicateResult(
        satisfied=True,
        detail="backfill evidence present and shape-valid",
        evidence_uri=str(path),
    )


# ──────────────────────────────  applies_when  ──────────────────────────────


def has_tracked_projects(ctx: PredicateContext | None = None) -> PredicateResult:
    """applies_when: the action APPLIES iff a non-empty project registry exists.

    ``satisfied`` is read as *applies*. A *missing* registry (clean zero state) or a
    valid empty one -> does not apply (a clean negative, not an error). A registry
    that is PRESENT but UNDETERMINABLE — unreadable / invalid JSON / schema-violating
    — fails OPEN: applies=True with an error detail, so a required action is never
    silently hidden behind a file we could not parse (D026).

    This uses :func:`projects_registry.load_registry_strict` rather than the lenient
    :func:`~projects_registry.load_registry`: the lenient loader maps a malformed
    file to an EMPTY registry, which would masquerade as "no tracked projects" and
    silently hide the action — exactly the fail-open violation we must avoid."""
    ctx = ctx or PredicateContext()
    if ctx.registry is not None:
        reg: Registry = ctx.registry
    else:
        try:
            reg = projects_registry.load_registry_strict()
        except projects_registry.RegistryUnreadableError as exc:
            # Present-but-undeterminable registry -> fail-open (applies), surfaced.
            return PredicateResult(
                satisfied=True,
                detail=f"project registry undeterminable; applying action (fail-open): {exc}",
                error=True,
            )
        except Exception as exc:  # noqa: BLE001 — any other read failure also fails open
            _LOG.warning("has_tracked_projects registry read failed: %s", exc)
            return PredicateResult(
                satisfied=True,
                detail=f"project registry undeterminable; applying action (fail-open): {exc}",
                error=True,
            )
    count = len(reg.projects)
    if count > 0:
        return PredicateResult(satisfied=True, detail=f"{count} tracked project(s) in registry")
    return PredicateResult(satisfied=False, detail="no tracked projects in registry")


# ──────────────────────────────  registry + resolvers  ──────────────────────────────


#: status_probe namespace: key -> read-only predicate callable. The SOLE authority
#: for required-action satisfaction (D004).
STATUS_PROBES: dict[str, Callable[[PredicateContext], PredicateResult]] = {
    "canonical_discovery_registered_active": canonical_discovery_registered_active,
    "canonical_backfill_evidence_valid": canonical_backfill_evidence_valid,
}

#: applies_when namespace: key -> read-only predicate callable. Gates whether an
#: action is shown to this instance.
APPLIES_WHEN: dict[str, Callable[[PredicateContext], PredicateResult]] = {
    "has_tracked_projects": has_tracked_projects,
}

#: The combined registry covering BOTH namespaces, keyed by role.
predicate_registry: dict[str, dict[str, Callable[[PredicateContext], PredicateResult]]] = {
    "status_probe": STATUS_PROBES,
    "applies_when": APPLIES_WHEN,
}


def resolve_status_probe(
    key: str | None, ctx: PredicateContext | None = None
) -> PredicateResult:
    """Resolve a status_probe ``key`` to a :class:`PredicateResult`, fail-CLOSED.

    A ``None`` / unknown key, or a predicate that raises, yields ``satisfied=False``
    with an explicit error detail (a typo can never satisfy or silently hide a required
    action, D026). Never raises into report assembly."""
    ctx = ctx or PredicateContext()
    fn = STATUS_PROBES.get(key) if key is not None else None
    if fn is None:
        return PredicateResult(
            satisfied=False,
            detail=f"unknown status_probe key {key!r}; fail-closed (never satisfied)",
            error=True,
        )
    try:
        return fn(ctx)
    except Exception as exc:  # noqa: BLE001 — a predicate must never crash assembly
        _LOG.warning("status_probe %r raised: %s", key, exc)
        return PredicateResult(
            satisfied=False,
            detail=f"status_probe {key!r} raised; fail-closed (not satisfied): {exc}",
            error=True,
        )


def resolve_applies_when(
    key: str | None, ctx: PredicateContext | None = None
) -> PredicateResult:
    """Resolve an applies_when ``key`` to a :class:`PredicateResult`, fail-OPEN.

    A ``None`` key means "no applicability gate" -> applies (clean, not an error). An
    UNKNOWN key, or a predicate that raises, yields ``satisfied=True`` (applies) with an
    error detail (a typo can never silently hide a required action, D026). Never raises
    into report assembly."""
    ctx = ctx or PredicateContext()
    if key is None:
        return PredicateResult(satisfied=True, detail="no applies_when gate; action applies")
    fn = APPLIES_WHEN.get(key)
    if fn is None:
        return PredicateResult(
            satisfied=True,
            detail=f"unknown applies_when key {key!r}; fail-open (action shown)",
            error=True,
        )
    try:
        return fn(ctx)
    except Exception as exc:  # noqa: BLE001 — a predicate must never crash assembly
        _LOG.warning("applies_when %r raised: %s", key, exc)
        return PredicateResult(
            satisfied=True,
            detail=f"applies_when {key!r} raised; fail-open (action applies): {exc}",
            error=True,
        )


__all__ = [
    "APPLIES_WHEN",
    "EVIDENCE_FILENAME",
    "PredicateContext",
    "PredicateResult",
    "STATUS_PROBES",
    "canonical_backfill_evidence_valid",
    "canonical_discovery_registered_active",
    "has_tracked_projects",
    "predicate_registry",
    "resolve_applies_when",
    "resolve_status_probe",
]
