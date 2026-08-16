"""Plan 2026-08-09-002 F007/F008 — every approval surface reads one snapshot.

CLI, INBOX, notify, Discord, and the dashboard do not re-derive impact from
plan artifacts. They format the :class:`DecisionBrief` taken at pause time.
Truncation follows D006: the impact line survives; supporting detail shortens.
The dashboard is the single unabridged surface.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal

from dontpanic_orchestrate.decision_brief import BriefStatus, DecisionBrief
from dontpanic_orchestrate.state_projection import scrub_secrets

SNAPSHOT_FILENAME: Final[str] = "decision-brief.json"

Surface = Literal["cli", "inbox", "notify", "dashboard"]

#: Per-surface cap on *supporting* detail (what_changes + consequence).
#: ``None`` means unabridged (dashboard only).
SUPPORTING_CAP_CHARS: Final[dict[str, int | None]] = {
    "cli": 280,
    "inbox": 280,
    "notify": 140,
    "dashboard": None,
}

UNDECLARED_IMPACT: Final[str] = "User impact not declared for this feature."
STALE_PREFIX: Final[str] = "Written against an earlier version: "


@dataclass(frozen=True)
class BriefPayload:
    """The three brief elements as one surface will show them."""

    what_changes: str
    user_impact: str
    decision_consequence: str
    text: str


def impact_line(brief: DecisionBrief) -> str:
    """Who feels it — never synthesized. D002: undeclared stays undeclared."""
    status = brief.status
    status_value = status.value if isinstance(status, BriefStatus) else str(status)
    summary = (brief.user_impact or "").strip()
    if status_value == BriefStatus.UNDECLARED.value or (
        status_value == BriefStatus.DECLARED.value and not summary
    ):
        if status_value == BriefStatus.DECLARED.value and not summary:
            return "No user-facing impact (audience: none)."
        return UNDECLARED_IMPACT
    if status_value == BriefStatus.POSSIBLY_STALE.value:
        if not summary:
            return "Declared impact may be stale; no summary is on record."
        return STALE_PREFIX + summary.rstrip(". ") + "."
    return summary


def _clip(text: str, cap: int | None) -> str:
    if cap is None or len(text) <= cap:
        return text
    if cap <= 1:
        return text[:cap]
    return text[: cap - 1].rstrip() + "…"


def render_brief(brief: DecisionBrief, *, surface: Surface) -> BriefPayload:
    """Format one snapshot for one surface. Never reads plan artifacts."""
    impact = impact_line(brief)
    cap = SUPPORTING_CAP_CHARS[surface]
    what = _clip(brief.what_changes, cap)
    consequence = _clip(brief.decision_consequence, cap)
    what = scrub_secrets(what) or ""
    impact = scrub_secrets(impact) or ""
    consequence = scrub_secrets(consequence) or ""
    text = (
        f"What changes: {what}\n"
        f"Who feels it: {impact}\n"
        f"What approving does: {consequence}"
    )
    return BriefPayload(
        what_changes=what,
        user_impact=impact,
        decision_consequence=consequence,
        text=text,
    )


def format_approve_prompt(brief: DecisionBrief) -> str:
    """CLI approve / resume prompt. Same snapshot, CLI truncation."""
    return render_brief(brief, surface="cli").text


def format_inbox_brief(brief: DecisionBrief) -> str:
    """INBOX annotation body. Same snapshot and cap as the approve prompt."""
    return render_brief(brief, surface="inbox").text


def format_notify_brief(brief: DecisionBrief) -> str:
    """Terminal-notifier / Discord — tighter cap, impact line still intact."""
    return render_brief(brief, surface="notify").text


def format_dashboard_brief(brief: DecisionBrief) -> str:
    """Dashboard card — unabridged."""
    return render_brief(brief, surface="dashboard").text


def terminal_payload(brief: DecisionBrief) -> BriefPayload:
    return render_brief(brief, surface="notify")


def discord_payload(brief: DecisionBrief) -> BriefPayload:
    return render_brief(brief, surface="notify")


def dashboard_payload(brief: DecisionBrief) -> BriefPayload:
    return render_brief(brief, surface="dashboard")


def dashboard_card_fields(brief: DecisionBrief) -> dict[str, str]:
    """Unabridged fields the dashboard ActionItem card renders."""
    payload = dashboard_payload(brief)
    return {
        "what_changes": payload.what_changes,
        "user_impact": payload.user_impact,
        "decision_consequence": payload.decision_consequence,
    }


def snapshot_path(plan_dir: Path) -> Path:
    return plan_dir / "audit" / SNAPSHOT_FILENAME


def persist(plan_dir: Path, brief: DecisionBrief) -> Path | None:
    """Write the pause snapshot so later CLI approve/resume can read it.

    Skips directories that are not a plan (no plan.md) so test stubs that
    pass a fixture folder as plan_dir do not grow an audit sidecar.
    """
    if not (plan_dir / "plan.md").is_file():
        return None
    path = snapshot_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(brief)
    payload["status"] = (
        brief.status.value if isinstance(brief.status, BriefStatus) else str(brief.status)
    )
    payload["surfaces"] = list(brief.surfaces)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def load(plan_dir: Path) -> DecisionBrief | None:
    """Read a previously persisted snapshot. None if the pause never wrote one."""
    path = snapshot_path(plan_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        status_raw = raw.get("status") or BriefStatus.UNDECLARED.value
        status = (
            status_raw
            if isinstance(status_raw, BriefStatus)
            else BriefStatus(str(status_raw))
        )
        return DecisionBrief(
            what_changes=str(raw.get("what_changes") or ""),
            user_impact=raw.get("user_impact"),
            affected_audience=raw.get("affected_audience"),
            decision_consequence=str(raw.get("decision_consequence") or ""),
            reversible=bool(raw.get("reversible", False)),
            status=status,
            surfaces=tuple(raw.get("surfaces") or ()),
        )
    except (TypeError, ValueError, KeyError):
        return None


__all__ = [
    "SUPPORTING_CAP_CHARS",
    "UNDECLARED_IMPACT",
    "BriefPayload",
    "dashboard_card_fields",
    "dashboard_payload",
    "discord_payload",
    "format_approve_prompt",
    "format_dashboard_brief",
    "format_inbox_brief",
    "format_notify_brief",
    "impact_line",
    "load",
    "persist",
    "render_brief",
    "snapshot_path",
    "terminal_payload",
]
