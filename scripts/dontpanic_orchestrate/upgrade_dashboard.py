"""Plan 2026-06-21-001 F008 — dashboard upgrade-status visibility + drill-down.

Two projections, both fed by the F005 :class:`upgrade_report.UpgradeReport`:

1. :func:`upgrade_status_projection` — the ALWAYS-rendered standing signal shown as
   a Tools & Setup / Health row (D011). A single status line plus the structured
   fields a renderer needs (``update_state``, pending counts, ``last_seen_release``
   / ``last_seen_commit``, ``installed_commit``, ``upstream_status``). It is emitted
   in EVERY state, including the positive up-to-date case — the dashboard's quiet
   state still shows "DontPanic: up to date", never nothing.

2. :func:`provide_upgrade_actions` — the DRILL-DOWN :class:`operator_console.ActionItem`
   list (``source='upgrade'``, D052). A probe-pending required action becomes a
   ``needs_action`` item carrying its first ``apply``-labeled command; an undismissed
   advisory becomes an ``advisory`` item (a satisfied-probe advisory demotes to
   ``info``). Dismissed advisories and satisfied required actions are already absent
   from the F005 report, so they never reach this projection.

KEY INVARIANTS

* **update_state and upstream_status are DISTINCT and both shown (D031).**
  ``update_state`` is manifest-action readiness; ``upstream_status`` is code-level
  freshness vs the tracked upstream. The status line NEVER renders "up to date"
  while ``upstream_status == behind`` — a checkout that is behind the newest
  DontPanic always reads as behind, even with zero pending manifest actions.

* **last_seen_commit vs installed_commit are NEVER conflated (D037).** The
  last-acknowledged display renders ``last_seen_commit`` (the acknowledged checkout
  from the marker); ``installed_commit`` (the CURRENT checkout) is carried as a
  separate field, never substituted into the acknowledgement line.

* **Absent marker -> "never acknowledged" (D042).** When ``marker_state == absent``
  (a fresh install) the row renders ``never acknowledged`` rather than a synthetic
  latest-release/commit acknowledgement, so a first run is never misreported.

* **No secret shapes (D048 sibling).** The status projection is run through
  :func:`operator_console._assert_no_secret_shapes` before return; the drill-down
  items flow through :func:`operator_console.render_envelope`, which asserts the
  same. Neither projection carries a secret-shaped field.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from dontpanic_orchestrate import operator_console as oc
from dontpanic_orchestrate.operator_console import ActionItem, Band
from dontpanic_orchestrate.upgrade_report import (
    UpdateState,
    UpgradeReport,
    UpstreamStatusKind,
)

#: Dashboard section the standing status row renders under (Tools & Setup / Health).
UPGRADE_STATUS_SECTION = "tools_setup_health"

#: Rendered when no acknowledgement exists (absent marker / null displayed fields).
NEVER_ACKNOWLEDGED = "never acknowledged"

#: The manifest command label whose command the drill-down surfaces (preview->APPLY->verify).
_APPLY_LABEL = "apply"


# ──────────────────────────────  status projection (always shown)  ──────────────────────────────


def _plural_actions(n: int) -> str:
    return f"{n} upgrade action{'s' if n != 1 else ''} pending"


def _plural_advisories(n: int) -> str:
    return f"{n} upgrade advisor{'ies' if n != 1 else 'y'} pending"


def _status_line(report: UpgradeReport) -> str:
    """The single Tools & Setup / Health line, driven by update_state + upstream (D031).

    ``upstream_status == behind`` ALWAYS wins over the up-to-date phrasing, so the
    row can never read "up to date" while the checkout is behind the newest DontPanic.
    """
    s = report.summary
    behind = s.upstream.upstream_status == UpstreamStatusKind.behind.value
    if behind:
        if s.pending_required:
            return f"DontPanic: behind the newest DontPanic — {_plural_actions(s.pending_required)}"
        if s.pending_advisory:
            return (
                "DontPanic: behind the newest DontPanic — "
                f"{_plural_advisories(s.pending_advisory)}"
            )
        return "DontPanic: behind the newest DontPanic (run `git pull`)"
    if s.update_state == UpdateState.required_pending.value:
        return f"DontPanic: {_plural_actions(s.pending_required)}"
    if s.update_state == UpdateState.advisories_pending.value:
        return f"DontPanic: {_plural_advisories(s.pending_advisory)}"
    if s.update_state == UpdateState.unknown.value:
        return "DontPanic: upgrade status unknown"
    return "DontPanic: up to date"


def _last_acknowledged_line(report: UpgradeReport) -> str:
    """The last-acknowledged display — renders ``last_seen_commit`` (D037), absent->never (D042)."""
    s = report.summary
    if s.marker_state == "absent":
        return NEVER_ACKNOWLEDGED
    rel = s.last_seen_release
    commit = s.last_seen_commit  # NEVER installed_commit (D037).
    if rel and commit:
        return f"Last acknowledged: {rel} (commit {commit})"
    if rel:
        return f"Last acknowledged: {rel}"
    if commit:
        return f"Last acknowledged: commit {commit}"
    return NEVER_ACKNOWLEDGED


def upgrade_status_projection(report: UpgradeReport) -> dict[str, Any]:
    """Project the F005 summary into the ALWAYS-shown Tools & Setup / Health row (D011).

    Returns a flat JSON-able dict the dashboard renders as one status line plus its
    structured fields. ``installed_commit`` (current checkout) and ``last_seen_commit``
    (acknowledged checkout) are carried SEPARATELY (D037); ``update_state`` and
    ``upstream_status`` are both present and distinct (D031). Always returns a dict —
    there is no "absent" path that hides the row.
    """
    s = report.summary
    projection: dict[str, Any] = {
        "section": UPGRADE_STATUS_SECTION,
        "always_shown": True,
        "status_line": _status_line(report),
        "update_state": s.update_state,
        "pending_required": s.pending_required,
        "pending_advisory": s.pending_advisory,
        "installed_commit": s.installed_commit,
        "last_seen_release": s.last_seen_release,
        "last_seen_commit": s.last_seen_commit,
        "last_acknowledged": _last_acknowledged_line(report),
        "marker_state": s.marker_state,
        "upstream_status": s.upstream.upstream_status,
        "behind_upstream": s.upstream.upstream_status == UpstreamStatusKind.behind.value,
        "latest_release_id": s.latest_release_id,
    }
    # No secret shapes (D048 sibling) — refuse to emit if a regex ever matches.
    oc._assert_no_secret_shapes(projection)
    return projection


# ──────────────────────────────  drill-down ActionItems (D052)  ──────────────────────────────


def _apply_command(item: Any) -> str | None:
    """Return the first ``apply``-labeled command for a report item, else None.

    Advisories carry no commands, so this is None for them. The preview/verify
    siblings are intentionally not surfaced as the copyable target — apply is the
    one the operator runs to satisfy the action.
    """
    for cmd in item.commands:
        if cmd.label == _APPLY_LABEL:
            return cmd.command
    return None


def _command_fields(command: str | None) -> tuple[str | None, str | None]:
    """Split a manifest command into (exact_command, operator_command).

    A command that passes the validated ActionItem boundary becomes ``exact_command``;
    anything else (e.g. a raw ``git pull`` or a not-yet-recognized ``dontpanic``
    subcommand) is surfaced via the honest-commands escape hatch ``operator_command``
    rather than tripping the boundary validator. None command -> both None.
    """
    if command is None:
        return None, None
    if oc._command_is_valid(command):
        return command, None
    return None, command


def _upgrade_item(item: Any, *, band: Band, updated_at: str, reason: str) -> ActionItem:
    command = _apply_command(item)
    exact_command, operator_command = _command_fields(command)
    return ActionItem(
        id=item.item_id,  # stable: upgrade:<release>:<action>
        source=oc.SOURCE_UPGRADE,
        band=band,
        title=item.title,
        detail=item.detail,
        exact_command=exact_command,
        automatable=False,
        human_required_reason=reason,
        evidence_uri=item.probe_evidence_uri or item.docs_url,
        updated_at=updated_at,
        audience=(oc.AUDIENCE_OPERATOR,),
        dedupe_key=item.item_id,
        operator_command=operator_command,
    )


def provide_upgrade_actions(
    report: UpgradeReport, *, now: _dt.datetime | None = None
) -> tuple[ActionItem, ...]:
    """Map the F005 report's required[]/advisory[] into drill-down ActionItems (D052).

    * required[] (already only the probe-pending, applies_when-holding ones) ->
      ``needs_action`` carrying the action's first ``apply``-labeled command.
    * advisory[] (already marker-filtered: dismissed advisories absent) -> ``advisory``,
      except a satisfied-probe advisory demotes to ``info`` (satisfied -> info, never
      a fresh needs-action ask).

    Ids are stable (``upgrade:<release>:<action>``) and the result is run through the
    SAME :func:`operator_console._sort` (band -> source -> id) every other provider uses.
    """
    updated_at = oc._now_iso(now)
    items: list[ActionItem] = []
    for item in report.required:
        items.append(
            _upgrade_item(item, band=Band.NEEDS_ACTION, updated_at=updated_at, reason="upgrade action")
        )
    for item in report.advisory:
        band = Band.INFO if item.satisfied is True else Band.ADVISORY
        items.append(
            _upgrade_item(item, band=band, updated_at=updated_at, reason="upgrade advisory")
        )
    return oc._sort(items)


# ──────────────────────────────  read-only report assembly seam  ──────────────────────────────


def build_dashboard_report(
    *,
    manifest_path: Any | None = None,
    marker_path: Any | None = None,
    predicate_registry: Any | None = None,
    predicate_ctx: Any | None = None,
    git: Any | None = None,
) -> UpgradeReport:
    """Assemble the F005 report for the dashboard — READ-ONLY (D015), NO fetch (D016).

    Loads the packaged release manifest and reads the per-instance marker WITHOUT
    writing it (``read_upgrade_state``), then assembles the report against the live
    predicate registry and a read-only git probe. Seams are injectable so tests drive
    every state hermetically. The dashboard wraps this best-effort: a broken/absent
    manifest must never fail the build.
    """
    from dontpanic_orchestrate import upgrade_report as ur
    from dontpanic_orchestrate.release_manifest import load_release_manifest
    from dontpanic_orchestrate.upgrade_predicates import PredicateContext
    from dontpanic_orchestrate.upgrade_state import read_upgrade_state

    manifest = load_release_manifest(manifest_path)
    marker = read_upgrade_state(manifest, path=marker_path)  # NEVER writes (D015).
    ctx = predicate_ctx if predicate_ctx is not None else PredicateContext()
    probe = git if git is not None else ur.GitProbe()
    return ur.assemble_upgrade_report(
        manifest, marker, predicate_registry, predicate_ctx=ctx, git=probe
    )


__all__ = [
    "NEVER_ACKNOWLEDGED",
    "UPGRADE_STATUS_SECTION",
    "build_dashboard_report",
    "provide_upgrade_actions",
    "upgrade_status_projection",
]
