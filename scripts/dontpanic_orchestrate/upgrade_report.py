"""Plan 2026-06-21-001 F005 — upgrade-readiness report assembly (pure core, no CLI).

:func:`assemble_upgrade_report` is the pure core that combines the three lower
layers into the machine-readable upgrade report the doctor surface (F006) and the
dashboard (F008) render:

* F004 (:mod:`dontpanic_orchestrate.upgrade_state`) — the per-instance marker and
  its ``marker_state`` (absent | predates | known), the displayed acknowledgement,
  and the marker-governed visible advisories;
* F003 (:mod:`dontpanic_orchestrate.upgrade_predicates`) — the ``status_probe``
  (satisfaction, fail-CLOSED) and ``applies_when`` (applicability, fail-OPEN)
  predicate registry;
* F001/F002 (:mod:`dontpanic_orchestrate.upgrade_releases_model`) — the validated
  release manifest with each action's commands + copy.

It returns an :class:`UpgradeReport` ``{summary, required[], advisory[],
migration_status[]}``. Everything here is PURE in the sense that it performs only
READ-ONLY observation (git rev-parse reads, predicate reads) and never mutates any
on-disk state; it also NEVER crashes assembly — a raising / unknown predicate key
degrades to its F003 fail-direction (D026).

KEY INVARIANTS

* **No implicit network fetch (D016).** The upstream block is computed ONLY from
  refs ALREADY KNOWN LOCALLY (``git rev-parse``, ``git rev-list``). ``git fetch``
  is NEVER invoked in the default path — :class:`GitProbe` exposes only read-only
  subcommands, and the no-fetch test asserts no ``fetch`` reaches the runner. An
  opt-in refresh is deferred to F006.

* **installed_commit + upstream degrade to ``unknown`` off-git.** When ``git
  rev-parse --short HEAD`` yields nothing (no git / detached bare / off-git),
  ``installed_commit`` is the literal ``"unknown"`` and ``upstream_status`` is
  ``unknown``.

* **Required pending is marker-INDEPENDENT (D004/D012).** A required action is
  pending iff its ``status_probe`` is NOT satisfied AND its ``applies_when`` holds.
  The marker never satisfies or hides a required action — only the live probe does.

* **Advisories are marker-GOVERNED (D012/D042).** ``advisory[]`` is exactly F004's
  :func:`upgrade_state.visible_advisories` (first-run filter on a fresh marker, all
  on a predates marker, releases-since on a known marker — then dismissals removed).

* **Displayed acknowledgement is NULL on a fresh marker (D042).** ``last_seen_release``
  / ``last_seen_commit`` come from the EffectiveMarker's *displayed* fields, which
  are NULL for an absent marker — never the latest-anchored internal diff value.

* **Pinned item shape, identical for required[] and advisory[] (D041).** Both lists
  carry the same :class:`ReportItem` contract, including the ORIGINAL ``applies_when``
  / ``status_probe`` keys (D046) and ``introduced_commands`` (D022/D033), so a single
  renderer/ActionItem reads one shape.

* **migration_status[] lists EVERY probe-backed action (D051).** Not only pending
  ones: a satisfied or not-applicable probe-backed action still appears with its
  state, so the migration audit/JSON stays complete across runs.
"""

from __future__ import annotations

import dataclasses
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import upgrade_predicates as up
from dontpanic_orchestrate.upgrade_predicates import PredicateContext, PredicateResult
from dontpanic_orchestrate.upgrade_releases_model import (
    Kind,
    UpgradeAction,
    UpgradeManifest,
)
from dontpanic_orchestrate.upgrade_state import (
    EffectiveMarker,
    advisory_key,
    visible_advisories,
)

#: A predicate is a read-only callable mapping a context to a PredicateResult.
PredicateFn = Callable[[PredicateContext], PredicateResult]
#: A predicate registry keyed by role ("status_probe" | "applies_when") -> {key -> fn},
#: mirroring :data:`upgrade_predicates.predicate_registry`.
PredicateRegistry = Mapping[str, Mapping[str, PredicateFn]]


# ──────────────────────────────  closed enums  ──────────────────────────────


class UpdateState(str, Enum):
    """Closed enum for the summary's overall update position (count matrix)."""

    up_to_date = "up_to_date"
    required_pending = "required_pending"
    advisories_pending = "advisories_pending"
    unknown = "unknown"


class UpstreamStatusKind(str, Enum):
    """Closed enum: this checkout's position vs the tracked upstream ref."""

    up_to_date = "up_to_date"
    behind = "behind"
    ahead = "ahead"
    diverged = "diverged"
    unknown = "unknown"


class MigrationState(str, Enum):
    """Closed enum for a probe-backed action's current state (D051)."""

    pending = "pending"
    satisfied = "satisfied"
    not_applicable = "not_applicable"


#: Sentinel used when git HEAD is undeterminable (off-git).
UNKNOWN_COMMIT = "unknown"

#: Per-status remediation hint surfaced in the upstream block (D016).
_UPSTREAM_REMEDIATION: dict[str, str] = {
    UpstreamStatusKind.up_to_date.value: "Up to date with the tracked upstream.",
    UpstreamStatusKind.behind.value: (
        "Newer DontPanic commits are available upstream; run `git pull` to update, "
        "then re-run `dontpanic doctor --upgrade`."
    ),
    UpstreamStatusKind.ahead.value: (
        "Your checkout has local commits not on the tracked upstream; push or open a PR."
    ),
    UpstreamStatusKind.diverged.value: (
        "Your checkout and the tracked upstream have diverged; reconcile with "
        "`git pull --rebase` (or merge) before updating."
    ),
}
_REMEDIATION_OFF_GIT = (
    "Upstream position unknown: not a git checkout, so the newest DontPanic cannot "
    "be compared here."
)
_REMEDIATION_NO_UPSTREAM = (
    "Upstream position unknown: this branch has no tracked upstream ref. Set one with "
    "`git branch --set-upstream-to=origin/<branch>` to enable behind/ahead detection."
)
_REMEDIATION_NEVER_FETCHED = (
    "Upstream position unknown: the tracked upstream ref is not present locally (never "
    "fetched). Run `git fetch` to refresh, then re-run `dontpanic doctor --upgrade`."
)


# ──────────────────────────────  git probe (read-only seam)  ──────────────────────────────


GitRunner = Callable[[Sequence[str]], str | None]


def _default_git_runner(root: Path | None) -> GitRunner:
    """Return a read-only git runner rooted at ``root`` (cwd when ``None``).

    The runner shells out to ``git`` with ONLY the read-only subcommands the report
    needs (rev-parse, rev-list). It NEVER fetches. Any failure (git missing, non-zero
    exit, not a repo) returns ``None`` and never raises — so the report degrades to
    ``unknown`` off-git instead of crashing.
    """
    prefix = ["git", *(["-C", str(root)] if root is not None else [])]

    def _run(args: Sequence[str]) -> str | None:
        try:
            proc = subprocess.run(  # noqa: S603 — fixed argv, shell=False, read-only git
                [*prefix, *args], capture_output=True, text=True
            )
        except (OSError, ValueError):
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None

    return _run


@dataclass
class GitProbe:
    """Read-only git seam for installed-commit + upstream computation.

    Exposes ONLY :meth:`run`, which forwards read-only git args to a runner. There is
    deliberately no fetch/pull entrypoint, so the no-network-fetch invariant (D016) is
    structural, not merely conventional. Tests inject a ``runner`` that records calls
    and returns canned output, then assert no recorded call begins with ``fetch``.
    """

    root: Path | None = None
    runner: GitRunner | None = None

    def run(self, *args: str) -> str | None:
        runner = self.runner or _default_git_runner(self.root)
        return runner(list(args))


# ──────────────────────────────  report dataclasses (JSON-able)  ──────────────────────────────


@dataclass(frozen=True)
class CommandView:
    """One ordered command in a report item (label + exact command + optional why)."""

    label: str
    command: str
    description: str | None = None


@dataclass(frozen=True)
class UpstreamBlock:
    """The summary's UPSTREAM availability block (D016).

    ``fetched_upstream_commit`` is the tracked upstream ref's commit AS ALREADY KNOWN
    LOCALLY (read-only; NULL when off-git / no upstream / never fetched).
    """

    fetched_upstream_commit: str | None
    upstream_status: str  # UpstreamStatusKind value
    remediation: str
    upstream_ref: str | None = None


@dataclass(frozen=True)
class ReportSummary:
    """The version/update summary (D010) plus the upstream block (D016)."""

    installed_commit: str  # short sha, or UNKNOWN_COMMIT off-git
    latest_release_id: str | None
    last_seen_release: str | None  # displayed acknowledgement — NULL on absent marker (D042)
    last_seen_commit: str | None  # displayed acknowledgement — NULL on absent marker (D023/D042)
    pending_required: int
    pending_advisory: int
    update_state: str  # UpdateState value
    marker_state: str  # F004 MarkerState value (absent | predates | known)
    upstream: UpstreamBlock


@dataclass(frozen=True)
class ReportItem:
    """Pinned report-item shape, IDENTICAL for required[] and advisory[] (D041).

    Carries the resolved ``applies`` / ``satisfied`` values AND the ORIGINAL
    ``applies_when`` / ``status_probe`` keys (D046), ``introduced_commands``
    (D022/D033), and BOTH predicate resolutions' ``detail``/``error`` surfaces so a
    degraded/unknown ``applies_when`` (fail-OPEN) or ``status_probe`` (fail-CLOSED)
    key stays auditable in the JSON rather than being silently flattened to its
    resolved bool (D026). ``satisfied`` / ``probe_detail`` are NULL when the action
    has no status_probe.
    """

    item_id: str  # upgrade:<release>:<action>
    release_id: str
    action_id: str
    kind: str  # Kind value (required | advisory)
    severity: str | None
    title: str
    detail: str
    applies: bool  # resolved from applies_when
    applies_when_key: str | None  # ORIGINAL manifest key (D046)
    applies_detail: str  # human detail from applies_when resolution (D026)
    applies_error: bool  # F003 fail-OPEN/degraded flag for applies_when surfaced (D026)
    status_probe_key: str | None  # ORIGINAL manifest key (D046)
    commands: list[CommandView]
    success_message: str | None
    failure_message: str | None
    human_next_step: str | None
    docs_url: str | None
    introduced_commands: list[str]  # [] when none (D022/D033)
    satisfied: bool | None  # None when no status_probe
    probe_detail: str | None  # None when no status_probe
    probe_error: bool  # F003 degraded/fail-direction flag surfaced (D026)
    probe_evidence_uri: str | None


@dataclass(frozen=True)
class MigrationStatusItem:
    """Pinned migration-status contract (D024), one per probe-backed action (D051)."""

    release_id: str
    action_id: str
    applies: bool
    status_probe_key: str | None  # probe key
    satisfied: bool
    state: str  # MigrationState value
    detail: str  # human detail (from the probe)
    evidence_uri: str | None  # evidence pointer


@dataclass(frozen=True)
class UpgradeReport:
    """The assembled upgrade-readiness report."""

    summary: ReportSummary
    required: list[ReportItem]
    advisory: list[ReportItem]
    migration_status: list[MigrationStatusItem]


def report_to_dict(report: UpgradeReport) -> dict[str, Any]:
    """Serialize an :class:`UpgradeReport` to a plain JSON-able dict (D046/D048).

    All fields are primitives / lists / nested dataclasses, so ``dataclasses.asdict``
    fully recurses without custom encoders. F006 uses this for ``--upgrade --json``.
    """
    return dataclasses.asdict(report)


# ──────────────────────────────  predicate resolution (mirrors F003)  ──────────────────────────────


def _resolve_status_probe(
    registry: PredicateRegistry, key: str | None, ctx: PredicateContext
) -> PredicateResult:
    """Resolve a status_probe via the passed registry, fail-CLOSED (mirrors F003 D026).

    A ``None`` / unknown key, or a predicate that raises, yields ``satisfied=False``
    with ``error=True`` and an explicit detail — a typo can never satisfy a required
    action, and the error is surfaced rather than crashing assembly.
    """
    probes = registry.get("status_probe", {}) if registry else {}
    fn = probes.get(key) if key is not None else None
    if fn is None:
        return PredicateResult(
            satisfied=False,
            detail=f"unknown status_probe key {key!r}; fail-closed (never satisfied)",
            error=True,
        )
    try:
        return fn(ctx)
    except Exception as exc:  # noqa: BLE001 — a predicate must never crash assembly
        return PredicateResult(
            satisfied=False,
            detail=f"status_probe {key!r} raised; fail-closed (not satisfied): {exc}",
            error=True,
        )


def _resolve_applies_when(
    registry: PredicateRegistry, key: str | None, ctx: PredicateContext
) -> PredicateResult:
    """Resolve an applies_when via the passed registry, fail-OPEN (mirrors F003 D026).

    A ``None`` key means "no applicability gate" -> applies (clean). An unknown key, or
    a predicate that raises, yields ``satisfied=True`` (applies) with ``error=True`` —
    a typo can never silently HIDE required work.
    """
    if key is None:
        return PredicateResult(satisfied=True, detail="no applies_when gate; action applies")
    gates = registry.get("applies_when", {}) if registry else {}
    fn = gates.get(key)
    if fn is None:
        return PredicateResult(
            satisfied=True,
            detail=f"unknown applies_when key {key!r}; fail-open (action shown)",
            error=True,
        )
    try:
        return fn(ctx)
    except Exception as exc:  # noqa: BLE001 — a predicate must never crash assembly
        return PredicateResult(
            satisfied=True,
            detail=f"applies_when {key!r} raised; fail-open (action applies): {exc}",
            error=True,
        )


# ──────────────────────────────  item builders  ──────────────────────────────


def _command_views(action: UpgradeAction) -> list[CommandView]:
    return [
        CommandView(label=c.label.value, command=c.command, description=c.description)
        for c in action.commands
    ]


def _build_item(
    release_id: str,
    action: UpgradeAction,
    applies: PredicateResult,
    probe: PredicateResult | None,
) -> ReportItem:
    """Build the pinned :class:`ReportItem` (D041) shared by required[] and advisory[]."""
    return ReportItem(
        item_id=advisory_key(release_id, action.id),
        release_id=release_id,
        action_id=action.id,
        kind=action.kind.value,
        severity=action.severity.value if action.severity is not None else None,
        title=action.title,
        detail=action.detail,
        applies=applies.satisfied,
        applies_when_key=action.applies_when,
        applies_detail=applies.detail,
        applies_error=applies.error,
        status_probe_key=action.status_probe,
        commands=_command_views(action),
        success_message=action.success_message,
        failure_message=action.failure_message,
        human_next_step=action.human_next_step,
        docs_url=action.docs_url,
        introduced_commands=list(action.introduced_commands or []),
        satisfied=(probe.satisfied if probe is not None else None),
        probe_detail=(probe.detail if probe is not None else None),
        probe_error=(probe.error if probe is not None else False),
        probe_evidence_uri=(probe.evidence_uri if probe is not None else None),
    )


def _iter_required_actions(
    manifest: UpgradeManifest,
) -> list[tuple[str, UpgradeAction]]:
    out: list[tuple[str, UpgradeAction]] = []
    for release in manifest.releases:
        for action in release.actions:
            if action.kind is Kind.required:
                out.append((release.id, action))
    return out


def _iter_probe_backed_actions(
    manifest: UpgradeManifest,
) -> list[tuple[str, UpgradeAction]]:
    out: list[tuple[str, UpgradeAction]] = []
    for release in manifest.releases:
        for action in release.actions:
            if action.status_probe is not None:
                out.append((release.id, action))
    return out


# ──────────────────────────────  upstream computation  ──────────────────────────────


def _classify_upstream(counts: str | None) -> UpstreamStatusKind:
    """Map ``git rev-list --left-right --count HEAD...@{upstream}`` output to a status.

    Left = commits HEAD is ahead, right = commits HEAD is behind. Unparseable output
    (degraded read) -> ``unknown``, never a crash.
    """
    if not counts:
        return UpstreamStatusKind.unknown
    parts = counts.split()
    if len(parts) != 2:
        return UpstreamStatusKind.unknown
    try:
        ahead, behind = int(parts[0]), int(parts[1])
    except ValueError:
        return UpstreamStatusKind.unknown
    if ahead == 0 and behind == 0:
        return UpstreamStatusKind.up_to_date
    if ahead == 0 and behind > 0:
        return UpstreamStatusKind.behind
    if ahead > 0 and behind == 0:
        return UpstreamStatusKind.ahead
    return UpstreamStatusKind.diverged


def _compute_repo_state(git: GitProbe) -> tuple[str, UpstreamBlock]:
    """Compute (installed_commit, upstream block) READ-ONLY, with NO network fetch (D016).

    Returns ``(UNKNOWN_COMMIT, unknown-block)`` off-git. Otherwise resolves the tracked
    upstream ref and compares positions using only locally-known refs.
    """
    head = git.run("rev-parse", "--short", "HEAD")
    if not head:
        return UNKNOWN_COMMIT, UpstreamBlock(
            fetched_upstream_commit=None,
            upstream_status=UpstreamStatusKind.unknown.value,
            remediation=_REMEDIATION_OFF_GIT,
            upstream_ref=None,
        )

    upstream_ref = git.run("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if not upstream_ref:
        return head, UpstreamBlock(
            fetched_upstream_commit=None,
            upstream_status=UpstreamStatusKind.unknown.value,
            remediation=_REMEDIATION_NO_UPSTREAM,
            upstream_ref=None,
        )

    upstream_commit = git.run("rev-parse", "--short", upstream_ref)
    if not upstream_commit:
        # Tracked ref configured but not present locally — never fetched.
        return head, UpstreamBlock(
            fetched_upstream_commit=None,
            upstream_status=UpstreamStatusKind.unknown.value,
            remediation=_REMEDIATION_NEVER_FETCHED,
            upstream_ref=upstream_ref,
        )

    status = _classify_upstream(
        git.run("rev-list", "--left-right", "--count", f"HEAD...{upstream_ref}")
    )
    remediation = _UPSTREAM_REMEDIATION.get(status.value, _REMEDIATION_NEVER_FETCHED)
    return head, UpstreamBlock(
        fetched_upstream_commit=upstream_commit,
        upstream_status=status.value,
        remediation=remediation,
        upstream_ref=upstream_ref,
    )


# ──────────────────────────────  update_state matrix  ──────────────────────────────


def _update_state(
    manifest: UpgradeManifest, pending_required: int, pending_advisory: int
) -> UpdateState:
    """The count matrix: required_pending > advisories_pending > up_to_date.

    ``unknown`` only when the manifest has no releases (nothing to assess).
    """
    if not manifest.releases:
        return UpdateState.unknown
    if pending_required > 0:
        return UpdateState.required_pending
    if pending_advisory > 0:
        return UpdateState.advisories_pending
    return UpdateState.up_to_date


# ──────────────────────────────  public assembly  ──────────────────────────────


def assemble_upgrade_report(
    manifest: UpgradeManifest,
    marker: EffectiveMarker,
    predicate_registry: PredicateRegistry | None = None,
    *,
    predicate_ctx: PredicateContext | None = None,
    git: GitProbe | None = None,
) -> UpgradeReport:
    """Assemble the upgrade-readiness report ``{summary, required[], advisory[],
    migration_status[]}`` (pure core, no CLI).

    Args:
        manifest: the validated release manifest (F001/F002).
        marker: the EffectiveMarker from F004 :func:`upgrade_state.read_upgrade_state`
            (carries ``marker_state`` + the displayed acknowledgement).
        predicate_registry: role -> {key -> predicate} (default:
            :data:`upgrade_predicates.predicate_registry`). Resolution mirrors F003's
            fail-closed (status_probe) / fail-open (applies_when) semantics (D026).
        predicate_ctx: read-only context for predicate resolution (default: empty).
        git: read-only git seam (default: real :class:`GitProbe`). NEVER fetches (D016).

    Required actions are pending iff status_probe unsatisfied AND applies_when holds —
    marker-independent (D004). Advisories follow F004's marker-governed visibility.
    """
    registry: PredicateRegistry = predicate_registry if predicate_registry is not None else up.predicate_registry
    ctx = predicate_ctx if predicate_ctx is not None else PredicateContext()
    probe_git = git if git is not None else GitProbe()

    # ── required[] — marker-independent; only the PENDING ones (live probe-gated) ──
    required_items: list[ReportItem] = []
    for release_id, action in _iter_required_actions(manifest):
        applies = _resolve_applies_when(registry, action.applies_when, ctx)
        probe = _resolve_status_probe(registry, action.status_probe, ctx)
        pending = applies.satisfied and not probe.satisfied
        if pending:
            required_items.append(_build_item(release_id, action, applies, probe))
    pending_required = len(required_items)

    # ── advisory[] — marker-governed visibility (first-run / predates / known + dismissals) ──
    advisory_items: list[ReportItem] = []
    for visible in visible_advisories(marker, manifest):
        action = visible.action
        applies = _resolve_applies_when(registry, action.applies_when, ctx)
        probe = (
            _resolve_status_probe(registry, action.status_probe, ctx)
            if action.status_probe is not None
            else None
        )
        advisory_items.append(_build_item(visible.release_id, action, applies, probe))
    pending_advisory = len(advisory_items)

    # ── migration_status[] — EVERY probe-backed action with its state (D051) ──
    migration_status: list[MigrationStatusItem] = []
    for release_id, action in _iter_probe_backed_actions(manifest):
        applies = _resolve_applies_when(registry, action.applies_when, ctx)
        probe = _resolve_status_probe(registry, action.status_probe, ctx)
        if not applies.satisfied:
            state = MigrationState.not_applicable
        elif probe.satisfied:
            state = MigrationState.satisfied
        else:
            state = MigrationState.pending
        migration_status.append(
            MigrationStatusItem(
                release_id=release_id,
                action_id=action.id,
                applies=applies.satisfied,
                status_probe_key=action.status_probe,
                satisfied=probe.satisfied,
                state=state.value,
                detail=probe.detail,
                evidence_uri=probe.evidence_uri,
            )
        )

    # ── summary + upstream ──
    installed_commit, upstream = _compute_repo_state(probe_git)
    latest_release_id = manifest.releases[-1].id if manifest.releases else None
    update_state = _update_state(manifest, pending_required, pending_advisory)

    summary = ReportSummary(
        installed_commit=installed_commit,
        latest_release_id=latest_release_id,
        last_seen_release=marker.displayed_last_seen_release,
        last_seen_commit=marker.displayed_last_seen_commit,
        pending_required=pending_required,
        pending_advisory=pending_advisory,
        update_state=update_state.value,
        marker_state=marker.marker_state.value,
        upstream=upstream,
    )

    return UpgradeReport(
        summary=summary,
        required=required_items,
        advisory=advisory_items,
        migration_status=migration_status,
    )


__all__ = [
    "UNKNOWN_COMMIT",
    "CommandView",
    "GitProbe",
    "GitRunner",
    "MigrationState",
    "MigrationStatusItem",
    "PredicateFn",
    "PredicateRegistry",
    "ReportItem",
    "ReportSummary",
    "UpdateState",
    "UpgradeReport",
    "UpstreamBlock",
    "UpstreamStatusKind",
    "assemble_upgrade_report",
    "report_to_dict",
]
