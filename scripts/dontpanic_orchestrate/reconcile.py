"""Plan 2026-05-23-002 — ``dontpanic reconcile`` subcommand surface.

F001 ships the ``baseline`` subcommand that builds (and optionally
writes) an install snapshot to ``~/.dontpanic/install-snapshot.json``.
F002 adds the ``check`` subcommand that compares the current capability
manifests + setup_steps against that snapshot and reports drift. Both
share this CLI module so ``dontpanic reconcile <verb>`` is the single
entry point.

``reconcile baseline`` is preview-by-default. Without ``--yes`` it
prints the snapshot the operator is about to write but does not touch
the filesystem. With ``--yes`` it writes the snapshot at mode 0o600.

``reconcile check`` is read-only by contract — it never writes to the
filesystem. It loads the snapshot anchor (the F001 install snapshot),
loads the current capability manifests, computes per-capability drift
deterministically, and renders text or JSON with exact next commands.

Exit codes (baseline):
  0  preview emitted OR snapshot written
  1  capability loading failed / write failed
  2  argparse / usage error

Exit codes (check):
  0  status == ``clean`` — current capabilities match the snapshot and
     the status cache (if relevant) is fresh
  1  status is any non-clean value from the v0 vocabulary
     (``missing_snapshot``, ``new_capabilities``, ``removed_capabilities``,
     ``changed_capabilities``, ``stale_status_cache``)
  2  argparse / usage error
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.capabilities import (
    CapabilityIndex,
    CapabilityManifestError,
    load_capabilities,
)
from dontpanic_orchestrate.install_snapshot import (
    CapabilityFingerprint,
    CapabilityLoadError,
    InstallSnapshot,
    build_snapshot,
    capability_fingerprint,
    load_snapshot,
    render_snapshot_json,
    render_snapshot_text,
    snapshot_path,
    write_snapshot,
)

_LOG = logging.getLogger(__name__)

CHECK_SCHEMA_VERSION = "1.1.0"
"""Pinned at the v1 reconcile-check envelope. Agents bind to this shape;
bump when the JSON envelope adds or removes fields. v1.1.0 widened
``status`` to the full vocabulary (no more catch-all ``drift``) and
added ``drift_kinds`` listing every applicable kind in priority order."""

_STATUS_CACHE_FILENAME = "capabilities-status.json"

# Exact commands the operator/agent should run to resolve each drift kind.
# Centralized so text and JSON renderers always emit the same strings.
_CMD_BASELINE = "dontpanic reconcile baseline --yes"
_CMD_STATUS = "dontpanic capabilities status"

# F002 status vocabulary. Single source of truth — the JSON contract,
# the text renderer, and the CLI exit-code branch all key off these.
STATUS_CLEAN = "clean"
STATUS_MISSING_SNAPSHOT = "missing_snapshot"
STATUS_NEW_CAPABILITIES = "new_capabilities"
STATUS_REMOVED_CAPABILITIES = "removed_capabilities"
STATUS_CHANGED_CAPABILITIES = "changed_capabilities"
STATUS_STALE_STATUS_CACHE = "stale_status_cache"

# Priority order used when multiple drift kinds apply at once. The
# primary ``status`` field collapses to the highest-priority kind in
# this list; ``drift_kinds`` still enumerates every applicable kind so
# agents that need the full picture can branch on the list.
_DRIFT_PRIORITY: tuple[str, ...] = (
    STATUS_REMOVED_CAPABILITIES,
    STATUS_NEW_CAPABILITIES,
    STATUS_CHANGED_CAPABILITIES,
    STATUS_STALE_STATUS_CACHE,
)


# ── result types ─────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class NewCapability:
    """A capability present in the current repo but absent from the snapshot."""

    capability_id: str
    manifest_fingerprint: str
    setup_steps_fingerprint: str
    setup_step_ids: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class RemovedCapability:
    """A capability present in the snapshot but absent from the current repo."""

    capability_id: str
    manifest_fingerprint: str
    setup_steps_fingerprint: str
    setup_step_ids: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ChangedCapability:
    """A capability whose fingerprint or setup_step_ids differ from the snapshot.

    ``manifest_changed`` and ``setup_steps_changed`` are independent —
    a manifest summary edit that leaves setup_steps alone toggles only
    the first; a step rename toggles both because the step id list
    contributes to the setup_steps fingerprint.
    """

    capability_id: str
    manifest_changed: bool
    setup_steps_changed: bool
    old_manifest_fingerprint: str
    new_manifest_fingerprint: str
    old_setup_steps_fingerprint: str
    new_setup_steps_fingerprint: str
    old_setup_step_ids: tuple[str, ...]
    new_setup_step_ids: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class StatusCacheState:
    """Reconcile result for ``~/.dontpanic/capabilities-status.json``.

    ``state`` is one of:
      * ``fresh``   — cache exists and post-dates the snapshot
      * ``missing`` — cache file does not exist on disk
      * ``stale``   — cache exists but predates the snapshot's
                      ``generated_at`` (so the cache may not reflect the
                      latest baselined capability set)
      * ``unknown`` — cache exists but couldn't be parsed for
                      ``generated_at``; treat as drift-worthy
    """

    state: str
    path: str
    snapshot_generated_at: str | None = None
    cache_generated_at: str | None = None


@dataclasses.dataclass(frozen=True)
class CapabilityCheckResult:
    """Top-level envelope returned by :func:`check_capabilities` and rendered
    by ``dontpanic reconcile check --area=capabilities``.

    ``status`` is one value from the v0 vocabulary:
      * ``clean``                  — snapshot exists, no drift, cache fresh-or-N/A
      * ``missing_snapshot``       — no snapshot at the expected path
      * ``new_capabilities``       — current repo has capabilities the snapshot does not
      * ``removed_capabilities``   — snapshot has capabilities the current repo does not
      * ``changed_capabilities``   — at least one capability's manifest or
                                     setup_steps fingerprint changed
      * ``stale_status_cache``     — capabilities-status.json is missing,
                                     stale relative to the snapshot, or
                                     unparseable

    Multi-kind drifts (e.g. a new capability AND a stale cache) collapse
    ``status`` to the highest-priority kind from :data:`_DRIFT_PRIORITY`.
    The complete enumeration lives in :attr:`drift_kinds` so agents can
    branch on every applicable kind without re-deriving them from the
    lists below.

    Drift categories are surfaced via ``new_capabilities``,
    ``removed_capabilities``, ``changed_capabilities``, and
    ``status_cache`` — agents can branch on the lists rather than parsing
    free-form text. ``next_commands`` lists exact shell commands the
    operator/agent should run to resolve the observed drift.
    """

    schema_version: str
    area: str
    status: str
    drift_kinds: tuple[str, ...]
    checked_at: str
    snapshot_path: str
    snapshot_generated_at: str | None
    new_capabilities: tuple[NewCapability, ...]
    removed_capabilities: tuple[RemovedCapability, ...]
    changed_capabilities: tuple[ChangedCapability, ...]
    status_cache: StatusCacheState | None
    next_commands: tuple[str, ...]

    @property
    def has_capability_drift(self) -> bool:
        return bool(
            self.new_capabilities
            or self.removed_capabilities
            or self.changed_capabilities
        )

    @property
    def has_status_cache_drift(self) -> bool:
        return (
            self.status_cache is not None
            and self.status_cache.state != "fresh"
        )


# ── pure comparison ──────────────────────────────────────────────────────


def diff_capability_fingerprints(
    snapshot_caps: Sequence[CapabilityFingerprint],
    current_caps: Sequence[CapabilityFingerprint],
) -> tuple[
    tuple[NewCapability, ...],
    tuple[RemovedCapability, ...],
    tuple[ChangedCapability, ...],
]:
    """Pure diff of two capability-fingerprint sequences.

    Returns ``(new, removed, changed)`` sorted by ``capability_id`` so
    the output is deterministic for both human review and agent
    consumption. Identical fingerprints (no manifest or setup-steps
    change AND identical setup_step_ids order) are filtered out — only
    real drift appears in the ``changed`` tuple.
    """

    snapshot_by_id = {cap.capability_id: cap for cap in snapshot_caps}
    current_by_id = {cap.capability_id: cap for cap in current_caps}

    new_ids = sorted(set(current_by_id) - set(snapshot_by_id))
    removed_ids = sorted(set(snapshot_by_id) - set(current_by_id))
    common_ids = sorted(set(snapshot_by_id) & set(current_by_id))

    new = tuple(
        NewCapability(
            capability_id=current_by_id[cap_id].capability_id,
            manifest_fingerprint=current_by_id[cap_id].manifest_fingerprint,
            setup_steps_fingerprint=current_by_id[cap_id].setup_steps_fingerprint,
            setup_step_ids=tuple(current_by_id[cap_id].setup_step_ids),
        )
        for cap_id in new_ids
    )
    removed = tuple(
        RemovedCapability(
            capability_id=snapshot_by_id[cap_id].capability_id,
            manifest_fingerprint=snapshot_by_id[cap_id].manifest_fingerprint,
            setup_steps_fingerprint=snapshot_by_id[cap_id].setup_steps_fingerprint,
            setup_step_ids=tuple(snapshot_by_id[cap_id].setup_step_ids),
        )
        for cap_id in removed_ids
    )

    changed: list[ChangedCapability] = []
    for cap_id in common_ids:
        old = snapshot_by_id[cap_id]
        new_cap = current_by_id[cap_id]
        manifest_changed = old.manifest_fingerprint != new_cap.manifest_fingerprint
        setup_steps_changed = (
            old.setup_steps_fingerprint != new_cap.setup_steps_fingerprint
            or tuple(old.setup_step_ids) != tuple(new_cap.setup_step_ids)
        )
        if not (manifest_changed or setup_steps_changed):
            continue
        changed.append(
            ChangedCapability(
                capability_id=cap_id,
                manifest_changed=manifest_changed,
                setup_steps_changed=setup_steps_changed,
                old_manifest_fingerprint=old.manifest_fingerprint,
                new_manifest_fingerprint=new_cap.manifest_fingerprint,
                old_setup_steps_fingerprint=old.setup_steps_fingerprint,
                new_setup_steps_fingerprint=new_cap.setup_steps_fingerprint,
                old_setup_step_ids=tuple(old.setup_step_ids),
                new_setup_step_ids=tuple(new_cap.setup_step_ids),
            )
        )
    return new, removed, tuple(changed)


# ── status cache state ───────────────────────────────────────────────────


def _parse_iso_z(value: str | None) -> _dt.datetime | None:
    """Parse a snapshot/cache ``generated_at`` string. Returns ``None`` on
    unparseable input so callers can branch on staleness without trying
    to compare ``None`` to a real datetime."""
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed


def evaluate_status_cache(
    snapshot: InstallSnapshot,
    *,
    cache_path: Path,
) -> StatusCacheState:
    """Compare ``~/.dontpanic/capabilities-status.json`` against the
    snapshot's ``generated_at``.

    Result vocabulary:
      * ``missing`` — file does not exist on disk
      * ``stale``   — cache file ``generated_at`` < snapshot
        ``generated_at`` (the snapshot is newer than the cache, so the
        cache may not reflect the latest baselined capability set)
      * ``unknown`` — cache exists but ``generated_at`` couldn't be
        parsed (treat as drift-worthy — operator should regenerate)
      * ``fresh``   — cache exists and post-dates the snapshot
    """

    if not cache_path.is_file():
        return StatusCacheState(
            state="missing",
            path=str(cache_path),
            snapshot_generated_at=snapshot.generated_at,
            cache_generated_at=None,
        )
    try:
        body = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning(
            "reconcile check: capabilities-status cache at %s unreadable (%s); "
            "treating as 'unknown' for drift purposes",
            cache_path,
            exc,
        )
        return StatusCacheState(
            state="unknown",
            path=str(cache_path),
            snapshot_generated_at=snapshot.generated_at,
            cache_generated_at=None,
        )
    cache_generated_at = body.get("generated_at") if isinstance(body, dict) else None
    cache_dt = _parse_iso_z(cache_generated_at)
    snapshot_dt = _parse_iso_z(snapshot.generated_at)
    if cache_dt is None or snapshot_dt is None:
        return StatusCacheState(
            state="unknown",
            path=str(cache_path),
            snapshot_generated_at=snapshot.generated_at,
            cache_generated_at=cache_generated_at,
        )
    if cache_dt < snapshot_dt:
        return StatusCacheState(
            state="stale",
            path=str(cache_path),
            snapshot_generated_at=snapshot.generated_at,
            cache_generated_at=cache_generated_at,
        )
    return StatusCacheState(
        state="fresh",
        path=str(cache_path),
        snapshot_generated_at=snapshot.generated_at,
        cache_generated_at=cache_generated_at,
    )


# ── top-level check ──────────────────────────────────────────────────────


def _now_iso() -> str:
    return (
        _dt.datetime.now(tz=_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _resolve_status_cache_path(snapshot: InstallSnapshot) -> Path:
    """Decide which cache path to evaluate.

    Prefer the path captured in the snapshot (``status_cache.path``)
    because that's what was anchored at baseline time. Fall back to the
    canonical sibling of the snapshot anchor when the snapshot was built
    before the cache existed.
    """
    if snapshot.status_cache is not None:
        return Path(snapshot.status_cache.path)
    return snapshot_path().parent / _STATUS_CACHE_FILENAME


def check_capabilities(
    *,
    capability_index: CapabilityIndex | None = None,
    snapshot: InstallSnapshot | None = None,
    snapshot_target_path: Path | None = None,
    cache_path: Path | None = None,
    now_iso: str | None = None,
    repo_root: Path | None = None,
) -> CapabilityCheckResult:
    """Run the capability-area reconcile check.

    Pure(-ish) function: reads the snapshot file and the cache file from
    disk but never writes. Loading current capability manifests through
    :func:`load_capabilities` is also a read-only operation. The
    function makes no decisions about exit codes — callers (the CLI)
    translate the result into a return code.

    ``snapshot`` is exposed for tests that want to inject a synthetic
    anchor without writing to ``~/.dontpanic``. ``capability_index`` is
    exposed for the same reason. Both default to loading from disk.
    """

    target_path = snapshot_target_path if snapshot_target_path is not None else snapshot_path()
    checked_at = now_iso if now_iso is not None else _now_iso()

    if snapshot is None:
        snapshot = load_snapshot(target_path)

    if snapshot is None:
        return CapabilityCheckResult(
            schema_version=CHECK_SCHEMA_VERSION,
            area="capabilities",
            status=STATUS_MISSING_SNAPSHOT,
            drift_kinds=(STATUS_MISSING_SNAPSHOT,),
            checked_at=checked_at,
            snapshot_path=str(target_path),
            snapshot_generated_at=None,
            new_capabilities=(),
            removed_capabilities=(),
            changed_capabilities=(),
            status_cache=None,
            next_commands=(_CMD_BASELINE,),
        )

    if capability_index is None:
        capability_index = load_capabilities(repo_root=repo_root)
    current_caps = tuple(capability_fingerprint(m) for m in capability_index.all)

    new_caps, removed_caps, changed_caps = diff_capability_fingerprints(
        snapshot.capabilities, current_caps
    )

    cache_target = cache_path if cache_path is not None else _resolve_status_cache_path(snapshot)
    cache_state = evaluate_status_cache(snapshot, cache_path=cache_target)

    kinds: list[str] = []
    if new_caps:
        kinds.append(STATUS_NEW_CAPABILITIES)
    if removed_caps:
        kinds.append(STATUS_REMOVED_CAPABILITIES)
    if changed_caps:
        kinds.append(STATUS_CHANGED_CAPABILITIES)
    if cache_state.state != "fresh":
        kinds.append(STATUS_STALE_STATUS_CACHE)

    # Canonical ordering for the drift_kinds tuple: priority order so
    # repeated invocations against the same drift state emit identical
    # bytes. The scalar ``status`` follows the same priority.
    ordered_kinds = tuple(k for k in _DRIFT_PRIORITY if k in kinds)
    if ordered_kinds:
        status = ordered_kinds[0]
        drift_kinds: tuple[str, ...] = ordered_kinds
    else:
        status = STATUS_CLEAN
        drift_kinds = ()

    next_commands: list[str] = []
    if new_caps or removed_caps or changed_caps:
        # Capability set changed → operator needs to re-baseline once they
        # confirm the new state is intended.
        next_commands.append(_CMD_BASELINE)
    if cache_state.state != "fresh":
        next_commands.append(_CMD_STATUS)

    return CapabilityCheckResult(
        schema_version=CHECK_SCHEMA_VERSION,
        area="capabilities",
        status=status,
        drift_kinds=drift_kinds,
        checked_at=checked_at,
        snapshot_path=str(target_path),
        snapshot_generated_at=snapshot.generated_at,
        new_capabilities=new_caps,
        removed_capabilities=removed_caps,
        changed_capabilities=changed_caps,
        status_cache=cache_state,
        next_commands=tuple(next_commands),
    )


# ── renderers ────────────────────────────────────────────────────────────


def _check_result_to_json_dict(result: CapabilityCheckResult) -> dict[str, Any]:
    """Stable JSON envelope for ``--format=json``. Agents bind to this
    shape; bump :data:`CHECK_SCHEMA_VERSION` when fields are added or
    removed."""

    def _new_dict(cap: NewCapability) -> dict[str, Any]:
        return {
            "capability_id": cap.capability_id,
            "manifest_fingerprint": cap.manifest_fingerprint,
            "setup_steps_fingerprint": cap.setup_steps_fingerprint,
            "setup_step_ids": list(cap.setup_step_ids),
        }

    def _removed_dict(cap: RemovedCapability) -> dict[str, Any]:
        return {
            "capability_id": cap.capability_id,
            "manifest_fingerprint": cap.manifest_fingerprint,
            "setup_steps_fingerprint": cap.setup_steps_fingerprint,
            "setup_step_ids": list(cap.setup_step_ids),
        }

    def _changed_dict(cap: ChangedCapability) -> dict[str, Any]:
        return {
            "capability_id": cap.capability_id,
            "manifest_changed": cap.manifest_changed,
            "setup_steps_changed": cap.setup_steps_changed,
            "old_manifest_fingerprint": cap.old_manifest_fingerprint,
            "new_manifest_fingerprint": cap.new_manifest_fingerprint,
            "old_setup_steps_fingerprint": cap.old_setup_steps_fingerprint,
            "new_setup_steps_fingerprint": cap.new_setup_steps_fingerprint,
            "old_setup_step_ids": list(cap.old_setup_step_ids),
            "new_setup_step_ids": list(cap.new_setup_step_ids),
        }

    status_cache: dict[str, Any] | None
    if result.status_cache is None:
        status_cache = None
    else:
        status_cache = {
            "state": result.status_cache.state,
            "path": result.status_cache.path,
            "snapshot_generated_at": result.status_cache.snapshot_generated_at,
            "cache_generated_at": result.status_cache.cache_generated_at,
        }

    return {
        "schema_version": result.schema_version,
        "area": result.area,
        "status": result.status,
        "drift_kinds": list(result.drift_kinds),
        "checked_at": result.checked_at,
        "snapshot_path": result.snapshot_path,
        "snapshot_generated_at": result.snapshot_generated_at,
        "new_capabilities": [_new_dict(c) for c in result.new_capabilities],
        "removed_capabilities": [_removed_dict(c) for c in result.removed_capabilities],
        "changed_capabilities": [_changed_dict(c) for c in result.changed_capabilities],
        "status_cache": status_cache,
        "next_commands": list(result.next_commands),
    }


def render_check_json(result: CapabilityCheckResult) -> str:
    return json.dumps(_check_result_to_json_dict(result), indent=2, sort_keys=True) + "\n"


def render_check_text(result: CapabilityCheckResult) -> str:
    """Compact human-friendly output. One line per drift item plus a
    final ``Next commands:`` block when actions are required."""

    lines: list[str] = []
    if result.status == STATUS_CLEAN:
        lines.append("reconcile check (capabilities): clean")
        lines.append(f"  snapshot:     {result.snapshot_path}")
        if result.snapshot_generated_at:
            lines.append(f"  generated_at: {result.snapshot_generated_at}")
        if result.status_cache is not None:
            lines.append(
                f"  status_cache: fresh ({result.status_cache.path})"
            )
        return "\n".join(lines) + "\n"

    if result.status == STATUS_MISSING_SNAPSHOT:
        lines.append("reconcile check (capabilities): drift — missing_snapshot")
        lines.append(f"  expected:     {result.snapshot_path}")
        lines.append("  fix: run the baseline command below to create the anchor.")
        lines.append("Next commands:")
        for cmd in result.next_commands:
            lines.append(f"  $ {cmd}")
        return "\n".join(lines) + "\n"

    # Drift: header advertises every applicable drift kind so agents
    # grepping the text output see the full vocabulary, not just the
    # priority winner.
    lines.append(
        "reconcile check (capabilities): drift — "
        + ", ".join(result.drift_kinds)
    )
    lines.append(f"  snapshot:     {result.snapshot_path}")
    if result.snapshot_generated_at:
        lines.append(f"  generated_at: {result.snapshot_generated_at}")

    if result.new_capabilities:
        lines.append(f"  new ({len(result.new_capabilities)}):")
        for cap in result.new_capabilities:
            lines.append(
                f"    + {cap.capability_id} "
                f"manifest={cap.manifest_fingerprint[:12]}… "
                f"setup_steps={cap.setup_steps_fingerprint[:12]}…"
            )

    if result.removed_capabilities:
        lines.append(f"  removed ({len(result.removed_capabilities)}):")
        for cap in result.removed_capabilities:
            lines.append(
                f"    - {cap.capability_id} "
                f"manifest={cap.manifest_fingerprint[:12]}… "
                f"setup_steps={cap.setup_steps_fingerprint[:12]}…"
            )

    if result.changed_capabilities:
        lines.append(f"  changed ({len(result.changed_capabilities)}):")
        for cap in result.changed_capabilities:
            tags = []
            if cap.manifest_changed:
                tags.append("manifest")
            if cap.setup_steps_changed:
                tags.append("setup_steps")
            lines.append(f"    ~ {cap.capability_id} [{', '.join(tags)}]")
            if cap.manifest_changed:
                lines.append(
                    f"        manifest:    "
                    f"{cap.old_manifest_fingerprint[:12]}… → "
                    f"{cap.new_manifest_fingerprint[:12]}…"
                )
            if cap.setup_steps_changed:
                lines.append(
                    f"        setup_steps: "
                    f"{cap.old_setup_steps_fingerprint[:12]}… → "
                    f"{cap.new_setup_steps_fingerprint[:12]}…"
                )
                if tuple(cap.old_setup_step_ids) != tuple(cap.new_setup_step_ids):
                    lines.append(
                        f"        step_ids:    "
                        f"{list(cap.old_setup_step_ids)} → "
                        f"{list(cap.new_setup_step_ids)}"
                    )

    if result.status_cache is not None and result.status_cache.state != "fresh":
        cache = result.status_cache
        lines.append(f"  status_cache: {cache.state} ({cache.path})")
        if cache.cache_generated_at:
            lines.append(
                f"    cache.generated_at:    {cache.cache_generated_at}"
            )
        if cache.snapshot_generated_at:
            lines.append(
                f"    snapshot.generated_at: {cache.snapshot_generated_at}"
            )

    if result.next_commands:
        lines.append("Next commands:")
        for cmd in result.next_commands:
            lines.append(f"  $ {cmd}")

    return "\n".join(lines) + "\n"


# ── argparse + CLI ────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dontpanic reconcile",
        description=(
            "Install-snapshot reconciliation. `baseline` builds the anchor; "
            "`check` compares the current repo against it."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand")

    baseline = sub.add_parser(
        "baseline",
        help=(
            "Build (and optionally write) the install snapshot anchor at "
            "~/.dontpanic/install-snapshot.json. Preview-only without `--yes`."
        ),
    )
    baseline.add_argument(
        "--profile",
        default="core",
        help="Profile to stamp into the snapshot (default: core).",
    )
    baseline.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Write the snapshot to disk. Without this flag, baseline is "
            "preview-only and never touches the filesystem."
        ),
    )
    baseline.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format for the snapshot body (default: text).",
    )

    check = sub.add_parser(
        "check",
        help=(
            "Compare current capability manifests + setup_steps against the "
            "install snapshot at ~/.dontpanic/install-snapshot.json. "
            "Never writes."
        ),
    )
    check.add_argument(
        "--area",
        choices=("capabilities",),
        default="capabilities",
        help=(
            "Reconciliation area to check. v0 ships `capabilities` only; "
            "additional areas (mcp, agent_manifest) are future work."
        ),
    )
    check.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )

    # Plan 2026-05-30-001 F006 — config-home reconciliation.
    homes = sub.add_parser(
        "homes",
        help=(
            "Reconcile the canonical ~/.dontpanic home against the legacy "
            "~/.jarvis home: surface split-brain config files and migrate "
            "legacy-only files canonical-ward. Dry-run by default; --confirm "
            "to migrate. Divergent same-name files are always refused."
        ),
    )
    homes.add_argument(
        "--confirm",
        action="store_true",
        help="Perform the migration (default is a dry-run that writes nothing).",
    )
    homes.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run (the default). Mutually exclusive with --confirm.",
    )
    homes.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    return parser


def _baseline_main(args: argparse.Namespace) -> int:
    try:
        snapshot = build_snapshot(profile=args.profile)
    except CapabilityLoadError as exc:
        print(f"reconcile baseline: failed to load capabilities: {exc}", file=sys.stderr)
        return 1

    target_path: Path = snapshot_path()
    if args.format == "json":
        sys.stdout.write(render_snapshot_json(snapshot))
    else:
        sys.stdout.write(render_snapshot_text(snapshot, target_path=target_path))
        sys.stdout.write("\n")

    if not args.yes:
        # Preview-only: never touch the filesystem.
        if args.format == "text":
            print(
                f"\n[preview] not written. Re-run with `--yes` to write {target_path} "
                "with mode 0600.",
                file=sys.stderr,
            )
        return 0

    try:
        written = write_snapshot(snapshot, path=target_path)
    except OSError as exc:
        print(f"reconcile baseline: failed to write snapshot: {exc}", file=sys.stderr)
        return 1
    if args.format == "text":
        print(f"\n[ok] wrote {written} (mode 0600).", file=sys.stderr)
    return 0


def _check_main(args: argparse.Namespace) -> int:
    try:
        result = check_capabilities()
    except CapabilityManifestError as exc:
        print(f"reconcile check: failed to load capabilities: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        sys.stdout.write(render_check_json(result))
    else:
        sys.stdout.write(render_check_text(result))

    if result.status == "clean":
        return 0
    return 1


def reconcile_main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.subcommand is None:
        parser.print_help(sys.stderr)
        return 2
    if args.subcommand == "baseline":
        return _baseline_main(args)
    if args.subcommand == "check":
        return _check_main(args)
    if args.subcommand == "homes":
        return _homes_main(args)
    parser.print_help(sys.stderr)  # pragma: no cover - argparse already restricts
    return 2


def _homes_main(args: argparse.Namespace) -> int:
    """``dontpanic reconcile homes`` — Plan 2026-05-30-001 F006.

    Exit codes:
      0 — clean (homes reconciled) OR migrations applied with no conflicts
      1 — divergent same-name files remain (ambiguous merge refused)
      2 — usage error (handled by argparse / mutually-exclusive guard)
    """
    from dontpanic_orchestrate import home_reconcile as hr

    if args.confirm and args.dry_run:
        print("reconcile homes: --confirm and --dry-run are mutually exclusive", file=sys.stderr)
        return 2
    confirm = bool(args.confirm)

    states = hr.classify_homes()
    plan = hr.plan_reconcile(states)
    result = hr.apply_reconcile(plan, confirm=confirm)

    if args.format == "json":
        payload = {
            "canonical_home": str(hr.canonical_home()),
            "legacy_home": str(hr.legacy_home()),
            "dry_run": result.dry_run,
            "files": [
                {"name": s.name, "status": s.status} for s in states
            ],
            "planned_migrations": [a.name for a in plan.migrations],
            "migrated": result.migrated,
            "refused_divergent": result.refused,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(f"canonical: {hr.canonical_home()}\n")
        sys.stdout.write(f"legacy:    {hr.legacy_home()}\n\n")
        for s in states:
            sys.stdout.write(f"  {s.status:14} {s.name}\n")
        if plan.migrations:
            verb = "migrated" if not result.dry_run else "would migrate"
            sys.stdout.write(f"\n{verb}: {', '.join(a.name for a in plan.migrations)}\n")
        if plan.conflicts:
            sys.stdout.write(
                "\n[refused] divergent (not merged — resolve by hand): "
                f"{', '.join(s.name for s in plan.conflicts)}\n"
            )
        if result.dry_run and (plan.migrations or plan.conflicts):
            sys.stdout.write("\n[preview] nothing written. Re-run with `--confirm` to migrate.\n")
        if plan.is_empty:
            sys.stdout.write("\n[ok] homes are reconciled — nothing to do.\n")

    # Divergent conflicts are the only non-clean terminal: surface as exit 1 so
    # scripts can detect an unresolved ambiguous merge.
    return 1 if plan.conflicts else 0


__all__ = [
    "CHECK_SCHEMA_VERSION",
    "CapabilityCheckResult",
    "ChangedCapability",
    "NewCapability",
    "RemovedCapability",
    "StatusCacheState",
    "check_capabilities",
    "diff_capability_fingerprints",
    "evaluate_status_cache",
    "reconcile_main",
    "render_check_json",
    "render_check_text",
]
