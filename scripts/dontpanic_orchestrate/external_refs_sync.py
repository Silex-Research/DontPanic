"""Plan 2026-05-20-001 F002 — external_refs lifecycle hooks.

Bridges plan.md's optional ``external_refs[]`` frontmatter array onto the
category-adapter layer from F001 (PM-tool wrapper hooks). The hooks land
on three operations:

  * ``dontpanic plan lock`` — validates every ref's URI is reachable via
    ``read_issue``. ``sync='push_status'`` refs that fail to resolve block
    lock loud; ``sync='none'`` refs tolerate unreachable URIs.
  * ``dontpanic plan close`` — walks ``sync='push_status'`` refs and
    calls ``push_status``. Every attempt (success, failure, dry-run,
    skipped) writes a durable :class:`ExternalSyncRecord` into
    ``evidence/external_sync.json``. Failures NEVER block close.
  * ``dontpanic plan resync <plan-id>`` — re-reads the evidence file and
    retries any ``failed|pending`` entries. ``pushed`` rows are skipped.

The category-adapter resolver is dependency-injected via
:class:`AdapterResolver` so tests can hand-build a fake registry. The
real-world resolver (operator-config-driven) lives in
``dontpanic_orchestrate.integrations.adapter_registry`` and is loaded by
the CLI; this module never imports it directly to keep the test surface
small.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from dontpanic_orchestrate.integrations.pm_tool_models import PMStatus
from dontpanic_orchestrate.integrations.pm_tool_sync import (
    ExternalSyncRecord,
    ExternalSyncStatus,
    PMToolSyncHook,
    make_failed_record,
    make_pending_record,
    utcnow,
)

if TYPE_CHECKING:
    from dontpanic_orchestrate.capabilities import CapabilityIndex

# Plan 2026-05-21-001 F004 — ref-kind to capability-category mapping. v0
# only ships ``pm_issue`` → ``pm-tool``; extending external_refs with a new
# kind means extending this table, not editing the validator.
EXTERNAL_REF_KIND_CATEGORY: dict[str, str] = {
    "pm_issue": "pm-tool",
}

# Default DontPanic-side intended status for ``plan close``. The bridge
# only flips status outbound at close time; a future feature may carry
# per-feature status, but v0 always pushes DONE on close.
DEFAULT_CLOSE_INTENDED_STATUS: PMStatus = PMStatus.DONE

EVIDENCE_RELPATH: Path = Path("evidence") / "external_sync.json"


class ExternalRefsSyncError(RuntimeError):
    """Raised for fatal lock-time refusals or operator-facing usage errors.

    Close-time failures DO NOT raise — they produce ``status='failed'``
    evidence records instead (F002 acceptance: failures must NEVER block
    close-out).
    """


class AdapterUnavailable(ExternalRefsSyncError):
    """Raised when no wrapper is registered for a URI scheme. Surfaces at
    lock-time as a hard refusal so the operator sees the missing adapter
    *before* implementation starts. At close-time, the resolver does NOT
    raise — :func:`run_close_push` catches and emits a ``failed`` evidence
    record so the close path stays unblocked."""


@dataclass(frozen=True)
class _ExternalRefShape:
    """Frozen normalization of one ``external_refs[]`` entry. We don't
    re-validate here — the plan_loader already parses + validates via
    Pydantic. This shape is just the loader-to-sync boundary."""

    kind: str
    uri: str
    sync: str  # "none" | "push_status"
    capability_id: str | None = None  # F004 — optional manifest binding


class ExternalRefCapabilityBindingError(ExternalRefsSyncError):
    """Raised when an ExternalRef's ``capability_id`` cannot be resolved.

    Two failure modes:

    * Unknown capability_id — the manifest index has no entry for the id
      the ref declared. Operator typo or stale plan.
    * Incompatible category — the manifest exists but its category does
      not match the ref ``kind`` (e.g. a ``pm_issue`` ref pointing at a
      ``dashboard-realtime`` capability).
    """


class AdapterResolver:
    """Maps URI schemes to :class:`PMToolSyncHook` wrappers.

    Real-world callers (the CLI) instantiate one resolver per process and
    register every wrapper the operator has configured. Tests construct
    an empty resolver and register fake hooks per case.

    The resolver does NOT instantiate wrappers itself — operators wire
    them up in the CLI bootstrap and hand the resolver pre-built hook
    instances. This keeps the resolver dependency-free of mapping JSONs
    and PP-adapter binaries.
    """

    def __init__(self) -> None:
        self._by_scheme: dict[str, PMToolSyncHook] = {}
        # F004 — secondary index keyed by capability_id. A hook may be
        # registered with capability_id=None (legacy / unbound mapping)
        # in which case it only appears in ``_by_scheme``. Capability
        # lookup falls back to ``AdapterUnavailable`` for those refs.
        self._by_capability_id: dict[str, PMToolSyncHook] = {}

    def register(
        self,
        hook: PMToolSyncHook,
        *,
        capability_id: str | None = None,
    ) -> None:
        scheme = hook.uri_scheme
        if scheme in self._by_scheme:
            raise ExternalRefsSyncError(
                f"AdapterResolver already has a wrapper for uri_scheme="
                f"{scheme!r}; refusing to re-register."
            )
        if capability_id is not None and capability_id in self._by_capability_id:
            raise ExternalRefsSyncError(
                f"AdapterResolver already has a wrapper for capability_id="
                f"{capability_id!r}; refusing to re-register."
            )
        self._by_scheme[scheme] = hook
        if capability_id is not None:
            self._by_capability_id[capability_id] = hook

    def resolve(self, uri: str) -> PMToolSyncHook:
        scheme = _scheme_from_uri(uri)
        try:
            return self._by_scheme[scheme]
        except KeyError as exc:
            raise AdapterUnavailable(
                f"No PM-tool wrapper registered for URI scheme {scheme!r} "
                f"(uri={uri!r}). Register one via AdapterResolver.register "
                f"during CLI bootstrap before this URI is locked or closed."
            ) from exc

    def resolve_by_capability_id(self, capability_id: str) -> PMToolSyncHook:
        """F004 — fetch a hook by capability_id. Raises
        :class:`AdapterUnavailable` when no registered adapter declares
        that capability_id."""

        try:
            return self._by_capability_id[capability_id]
        except KeyError as exc:
            raise AdapterUnavailable(
                f"No PM-tool wrapper registered for capability_id="
                f"{capability_id!r}. Register an adapter mapping that "
                f"declares ``capability_id: {capability_id}`` in "
                f"~/.dontpanic/adapters/<service>.json before this ref "
                f"is locked or closed."
            ) from exc

    def has(self, scheme: str) -> bool:
        return scheme in self._by_scheme

    def has_capability_id(self, capability_id: str) -> bool:
        return capability_id in self._by_capability_id


def _scheme_from_uri(uri: str) -> str:
    """``linear://issue/ABC-123`` → ``"linear"``. Plan_loader validates
    the URI pattern before we reach here; this is a thin convenience."""

    parsed = urlparse(uri)
    if not parsed.scheme:
        raise ExternalRefsSyncError(f"URI {uri!r} has no scheme; cannot resolve adapter.")
    return parsed.scheme


# ──────────────────────────────  lock-time  ──────────────────────────────


# Session-scoped cache for lock-time validation. Keyed by URI + optional
# capability_id; a successful read short-circuits repeat reads within the
# same process only for the same capability-binding context. Tests reset
# this between cases via :func:`reset_read_cache`.
_ReadCacheKey = tuple[str, str | None]
_READ_CACHE: dict[_ReadCacheKey, Any] = {}


def reset_read_cache() -> None:
    """Clear the lock-time per-uri read cache. Tests and long-running
    processes that re-lock the same plan multiple times call this to
    force a fresh validation pass."""

    _READ_CACHE.clear()


def validate_capability_bindings(
    refs: Iterable[Any],
    capability_index: CapabilityIndex,
) -> None:
    """F004 — validate every ref's ``capability_id`` against the manifest index.

    Refs without ``capability_id`` are skipped (backward compatibility).
    Otherwise the capability_id MUST exist in the index AND its manifest
    category MUST match the ref kind via :data:`EXTERNAL_REF_KIND_CATEGORY`.
    Lock-time callers invoke this before resolver lookups so an unknown or
    miscategorized capability fails with an actionable error instead of
    silently dropping through to scheme-based resolution.
    """

    for ref in refs:
        shape = _normalize(ref)
        if shape.capability_id is None:
            continue
        expected_category = EXTERNAL_REF_KIND_CATEGORY.get(shape.kind)
        if expected_category is None:
            raise ExternalRefCapabilityBindingError(
                f"external_ref kind={shape.kind!r} has no category mapping; "
                f"known kinds: {sorted(EXTERNAL_REF_KIND_CATEGORY)}. Update "
                f"EXTERNAL_REF_KIND_CATEGORY when adding a new ref kind."
            )
        manifest = capability_index.get(shape.capability_id)
        if manifest is None:
            raise ExternalRefCapabilityBindingError(
                f"external_ref uri={shape.uri!r} declares unknown "
                f"capability_id {shape.capability_id!r}; check "
                f"capabilities/<id>.json manifests."
            )
        if manifest.category != expected_category:
            raise ExternalRefCapabilityBindingError(
                f"external_ref uri={shape.uri!r} (kind={shape.kind!r}) "
                f"binds to capability_id {shape.capability_id!r} but its "
                f"manifest category is {manifest.category!r}; expected "
                f"{expected_category!r}."
            )


def _resolve_for_ref(resolver: AdapterResolver, shape: _ExternalRefShape) -> PMToolSyncHook:
    """F004 — prefer capability_id resolution when the ref declares one.

    When ``shape.capability_id`` is set, look up the hook in the
    resolver's capability_id index; if no adapter is registered with
    that capability_id, raise :class:`AdapterUnavailable` (the caller
    decides whether to honor the failure based on ``sync`` mode).

    When ``shape.capability_id`` is None, fall through to the legacy
    scheme-based ``resolve(uri)`` path.
    """

    if shape.capability_id is not None:
        return resolver.resolve_by_capability_id(shape.capability_id)
    return resolver.resolve(shape.uri)


def _read_cache_key(shape: _ExternalRefShape) -> _ReadCacheKey:
    """Cache scope for lock-time reads.

    Capability-bound refs cannot reuse legacy same-URI reads because the
    binding contract also proves a registered adapter implements the
    declared capability_id.
    """

    return (shape.uri, shape.capability_id)


def validate_refs_for_lock(
    refs: Iterable[Any],
    resolver: AdapterResolver,
    *,
    use_cache: bool = True,
    capability_index: CapabilityIndex | None = None,
) -> None:
    """Lock-time validation hook. Calls ``read_issue`` on every ref to
    confirm reachability via the category-adapter layer.

    Behavior matrix (per acceptance #3):
      * ``sync='push_status'`` AND read fails  → :class:`ExternalRefsSyncError`
        (block lock loud — push targets MUST exist).
      * ``sync='push_status'`` AND no adapter  → :class:`AdapterUnavailable`
        (subclass of ExternalRefsSyncError — same blocking behavior).
      * ``sync='none'`` AND read fails         → ignored (the ref is
        informational; logging belongs to the caller, not this module).

    F004: when ``capability_index`` is supplied, every ref's declared
    ``capability_id`` is validated against the manifest index first
    (unknown id or incompatible category raises
    :class:`ExternalRefCapabilityBindingError` regardless of ``sync``
    mode — config errors are loud at lock-time so operators see them
    before close). Resolver lookups for refs with ``capability_id`` go
    through the capability_id index rather than the URI scheme.

    Cache: a successful read is cached per (URI, capability_id) for the
    rest of the process so re-locking the same plan doesn't re-hit the
    vendor, while capability-bound refs cannot inherit legacy same-URI
    validation.
    """

    refs_list = list(refs)
    if capability_index is not None:
        validate_capability_bindings(refs_list, capability_index)
    for ref in refs_list:
        shape = _normalize(ref)
        try:
            hook = _resolve_for_ref(resolver, shape)
        except AdapterUnavailable:
            if shape.sync == "push_status":
                raise
            continue
        cache_key = _read_cache_key(shape)
        if use_cache and cache_key in _READ_CACHE:
            continue
        try:
            issue = hook.read_issue(shape.uri)
        except Exception as exc:  # noqa: BLE001 — wrapper-defined failures
            if shape.sync == "push_status":
                raise ExternalRefsSyncError(
                    f"external_ref uri={shape.uri!r} (sync=push_status) is "
                    f"not reachable via adapter: {type(exc).__name__}: {exc}. "
                    f"Lock blocked — push targets MUST exist. Fix the URI, "
                    f"the adapter config, or drop the ref to sync=none."
                ) from exc
            continue
        if use_cache:
            _READ_CACHE[cache_key] = issue


# ──────────────────────────────  close-time  ──────────────────────────────


@dataclass(frozen=True)
class ExternalSyncResult:
    """Aggregate close-time result. The caller (plan close CLI) uses
    ``records`` for operator output; ``evidence_path`` is the durable
    artifact path (always written, even when ``records`` is empty)."""

    records: tuple[ExternalSyncRecord, ...]
    evidence_path: Path
    dry_run: bool

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.records if r.status is ExternalSyncStatus.FAILED)

    @property
    def pushed_count(self) -> int:
        return sum(1 for r in self.records if r.status is ExternalSyncStatus.PUSHED)


def run_close_push(
    refs: Iterable[Any],
    resolver: AdapterResolver,
    plan_dir: Path,
    *,
    dry_run: bool = False,
    intended_status: PMStatus = DEFAULT_CLOSE_INTENDED_STATUS,
) -> ExternalSyncResult:
    """Close-time hook. Walks every ref, pushes status for the ones with
    ``sync='push_status'``, writes a record per attempt into
    ``evidence/external_sync.json``.

    Per acceptance #4: EVERY ref attempt produces a record:

      * ``sync='push_status'`` + adapter PUSHED       → status=pushed
      * ``sync='push_status'`` + adapter raises        → status=failed
      * ``sync='push_status'`` + no adapter             → status=failed
      * ``sync='push_status'`` + dry_run=True           → status=pending
      * ``sync='none'``                                 → status=skipped

    Failures NEVER raise — they appear as records with ``status='failed'``
    so the close path stays unblocked but the failure is durable evidence.
    """

    records: list[ExternalSyncRecord] = []

    for ref in refs:
        shape = _normalize(ref)
        if shape.sync == "none":
            records.append(
                ExternalSyncRecord(
                    ref_uri=shape.uri,
                    kind=shape.kind,
                    attempted_at=utcnow(),
                    status=ExternalSyncStatus.SKIPPED,
                    intended_status=intended_status,
                    response=None,
                    error=None,
                )
            )
            continue

        # sync='push_status' branch. Dry-run path: construct the
        # PENDING evidence record directly WITHOUT calling the category
        # adapter (F002 acceptance #5). Operators still see the intended
        # status + URI in the preview; the wrapper's vendor-specific
        # payload shape is not load-bearing here.
        if dry_run:
            records.append(
                make_pending_record(
                    ref_uri=shape.uri,
                    kind=shape.kind,
                    intended_status=intended_status,
                    payload={
                        "uri": shape.uri,
                        "intended_status": intended_status.value,
                    },
                )
            )
            continue

        try:
            hook = _resolve_for_ref(resolver, shape)
        except AdapterUnavailable as exc:
            records.append(
                make_failed_record(
                    ref_uri=shape.uri,
                    kind=shape.kind,
                    intended_status=intended_status,
                    error=f"AdapterUnavailable: {exc}",
                )
            )
            continue

        try:
            record = hook.push_status(shape.uri, intended_status, dry_run=False)
        except Exception as exc:  # noqa: BLE001 — failure stays evidence, not raise
            record = make_failed_record(
                ref_uri=shape.uri,
                kind=shape.kind,
                intended_status=intended_status,
                error=f"{type(exc).__name__}: {exc}",
            )
        records.append(record)

    evidence_path = write_evidence(plan_dir, records)
    return ExternalSyncResult(
        records=tuple(records),
        evidence_path=evidence_path,
        dry_run=dry_run,
    )


# ──────────────────────────────  resync  ──────────────────────────────


def run_resync(
    plan_dir: Path,
    resolver: AdapterResolver,
    *,
    intended_status: PMStatus = DEFAULT_CLOSE_INTENDED_STATUS,
) -> ExternalSyncResult:
    """``dontpanic plan resync`` — re-read ``evidence/external_sync.json``
    and retry any entry with ``status ∈ {failed, pending}``. Idempotent:
    already-pushed entries are NOT replayed.

    Per acceptance #6: the operation is idempotent. Entries that were
    pushed in a previous close stay pushed; entries that were skipped
    (sync='none') stay skipped. Only failed/pending entries are retried;
    each retry produces a fresh record (pushed/failed) appended into the
    rewritten evidence file (replaces the prior entry at the same URI).
    """

    evidence_path = plan_dir / EVIDENCE_RELPATH
    existing = load_evidence(plan_dir)
    if not existing:
        return ExternalSyncResult(records=(), evidence_path=evidence_path, dry_run=False)

    next_records: list[ExternalSyncRecord] = []
    for record in existing:
        if record.status in (ExternalSyncStatus.PUSHED, ExternalSyncStatus.SKIPPED):
            next_records.append(record)
            continue

        # Retry path: failed or pending → call push_status.
        try:
            hook = resolver.resolve(record.ref_uri)
        except AdapterUnavailable as exc:
            next_records.append(
                make_failed_record(
                    ref_uri=record.ref_uri,
                    kind=record.kind,
                    intended_status=record.intended_status or intended_status,
                    error=f"AdapterUnavailable: {exc}",
                )
            )
            continue
        try:
            replay = hook.push_status(
                record.ref_uri,
                record.intended_status or intended_status,
                dry_run=False,
            )
        except Exception as exc:  # noqa: BLE001
            replay = make_failed_record(
                ref_uri=record.ref_uri,
                kind=record.kind,
                intended_status=record.intended_status or intended_status,
                error=f"{type(exc).__name__}: {exc}",
            )
        next_records.append(replay)

    write_evidence(plan_dir, next_records)
    return ExternalSyncResult(
        records=tuple(next_records),
        evidence_path=evidence_path,
        dry_run=False,
    )


# ──────────────────────────────  evidence I/O  ──────────────────────────────


def write_evidence(plan_dir: Path, records: Iterable[ExternalSyncRecord]) -> Path:
    """Write the evidence array verbatim. Overwrites any prior file —
    each plan-close (and each resync) produces a complete snapshot, not
    an append log.

    The single-snapshot decision is deliberate: downstream consumers
    (F003 dashboard chip) join on the most recent record per URI, and a
    snapshot file is simpler to validate than an append log. Operators
    who want the audit trail run ``git log evidence/external_sync.json``.
    """

    evidence_path = plan_dir / EVIDENCE_RELPATH
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [json.loads(r.model_dump_json()) for r in records]
    evidence_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return evidence_path


def load_evidence(plan_dir: Path) -> list[ExternalSyncRecord]:
    """Read + validate the evidence file. Returns ``[]`` when absent."""

    evidence_path = plan_dir / EVIDENCE_RELPATH
    if not evidence_path.is_file():
        return []
    raw = json.loads(evidence_path.read_text())
    if not isinstance(raw, list):
        raise ExternalRefsSyncError(
            f"{evidence_path}: expected a JSON array of ExternalSyncRecord; "
            f"got {type(raw).__name__}."
        )
    return [ExternalSyncRecord.model_validate(row) for row in raw]


def format_dry_run_preview(result: ExternalSyncResult) -> list[str]:
    """Operator-readable preview lines for ``plan close --dry-run``.

    Returns a list of strings the CLI prints in order. Empty result
    (no external_refs declared) returns an empty list — caller prints
    nothing.
    """

    if not result.records:
        return []
    lines = [
        f"[external_sync] dry-run preview ({len(result.records)} ref(s)):",
    ]
    for r in result.records:
        marker = {
            ExternalSyncStatus.PENDING: "PENDING",
            ExternalSyncStatus.SKIPPED: "SKIPPED",
            ExternalSyncStatus.PUSHED: "PUSHED",
            ExternalSyncStatus.FAILED: "FAILED",
        }[r.status]
        payload = ""
        if r.response is not None:
            payload = f"  payload={json.dumps(r.response, sort_keys=True)}"
        lines.append(f"  - {marker} {r.ref_uri} (kind={r.kind}){payload}")
    lines.append(f"[external_sync] evidence: {result.evidence_path}")
    return lines


# ──────────────────────────────  helpers  ──────────────────────────────


def _normalize(ref: Any) -> _ExternalRefShape:
    """Accept either a Pydantic ExternalRef (from plan_loader) or a plain
    dict (tests). Returns a frozen shape with .kind, .uri, .sync as plain
    strings."""

    if hasattr(ref, "model_dump"):
        # mode='json' coerces enums to their .value so the resulting dict
        # carries plain strings (matches the YAML-loaded frontmatter shape).
        data = ref.model_dump(mode="json")
    elif isinstance(ref, dict):
        data = ref
    else:
        raise ExternalRefsSyncError(f"Unrecognized external_ref shape: {type(ref).__name__}")
    kind = data.get("kind")
    uri = data.get("uri")
    sync = data.get("sync")
    capability_id = data.get("capability_id")
    # Defensive: dict callers may hand us raw enums.
    if hasattr(kind, "value"):
        kind = kind.value  # type: ignore[union-attr]
    if hasattr(sync, "value"):
        sync = sync.value  # type: ignore[union-attr]
    if not (isinstance(kind, str) and isinstance(uri, str) and isinstance(sync, str)):
        raise ExternalRefsSyncError(
            f"external_ref missing required fields {{kind, uri, sync}}: {data!r}"
        )
    if capability_id is not None and not isinstance(capability_id, str):
        raise ExternalRefsSyncError(f"external_ref capability_id must be str or absent: {data!r}")
    return _ExternalRefShape(kind=kind, uri=uri, sync=sync, capability_id=capability_id)


__all__ = [
    "AdapterResolver",
    "AdapterUnavailable",
    "DEFAULT_CLOSE_INTENDED_STATUS",
    "EVIDENCE_RELPATH",
    "EXTERNAL_REF_KIND_CATEGORY",
    "ExternalRefCapabilityBindingError",
    "ExternalRefsSyncError",
    "ExternalSyncResult",
    "format_dry_run_preview",
    "load_evidence",
    "reset_read_cache",
    "run_close_push",
    "run_resync",
    "validate_capability_bindings",
    "validate_refs_for_lock",
    "write_evidence",
]
