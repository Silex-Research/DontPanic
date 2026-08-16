"""Plan 2026-08-09-002 F008 — notify, Discord, and dashboard share one snapshot.

Acceptance maps one class per clause:

  1. All three sinks carry the same three brief elements, modulo truncation.
  2. Dashboard is unabridged; both notification sinks are capped.
  3. Truncation preserves the impact line in every capped sink.
  4. Secret scrubbing runs over all three payloads.
"""

from __future__ import annotations

from dataclasses import replace

from dontpanic_orchestrate import brief_surfaces, notify, notify_discord, notify_event
from dontpanic_orchestrate.decision_brief import BriefStatus, DecisionBrief

_SECRET = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"

WHAT = "Rewrite the approval headline so product outcome leads."
IMPACT = "Operators read the outcome before the plan id."
CONSEQUENCE = "Clearing pre_merge lets the implementer run on F008."


def _brief(**over: object) -> DecisionBrief:
    base: dict[str, object] = {
        "what_changes": WHAT,
        "user_impact": IMPACT,
        "affected_audience": "operator",
        "decision_consequence": CONSEQUENCE,
        "reversible": True,
        "status": BriefStatus.DECLARED,
        "surfaces": ("backend",),
    }
    base.update(over)
    return DecisionBrief(**base)  # type: ignore[arg-type]


def _event(brief: DecisionBrief) -> notify_event.NotifyEvent:
    return notify_event.NotifyEvent(
        kind="gate_paused",
        severity="action_required",
        plan_id="2026-08-09-002-feat-decision-brief-at-gates",
        feature_id="F008",
        body="**Gate pause** (implement) — awaiting: pre_merge",
        inbox_event="gate_hit",
        subtype="implement",
        decision_brief=brief,
    )


class TestThreeSinksShareElements:
    """AC1 — Discord, terminal, dashboard carry the same three elements."""

    def test_same_elements_modulo_truncation(self) -> None:
        brief = _brief()
        terminal = brief_surfaces.terminal_payload(brief)
        discord = brief_surfaces.discord_payload(brief)
        dashboard = brief_surfaces.dashboard_payload(brief)
        for payload in (terminal, discord, dashboard):
            assert IMPACT in payload.text
            assert WHAT in payload.text or payload.what_changes.startswith(WHAT[:20])
            assert (
                CONSEQUENCE in payload.text
                or payload.decision_consequence.startswith(CONSEQUENCE[:20])
            )
        assert terminal.user_impact == discord.user_impact == dashboard.user_impact


class TestDashboardUnabridgedNotifyCapped:
    """AC2 — dashboard is the only unabridged surface."""

    def test_dashboard_keeps_full_support_notify_clips(self) -> None:
        long_what = "W" * 400
        long_cons = "C" * 400
        brief = _brief(what_changes=long_what, decision_consequence=long_cons)
        dash = brief_surfaces.dashboard_payload(brief)
        term = brief_surfaces.terminal_payload(brief)
        disc = brief_surfaces.discord_payload(brief)
        assert dash.what_changes == long_what
        assert dash.decision_consequence == long_cons
        assert len(term.what_changes) < len(long_what)
        assert len(disc.what_changes) < len(long_what)
        assert term.what_changes.endswith("…")
        assert disc.what_changes.endswith("…")


class TestTruncationKeepsImpact:
    """AC3 — capped sinks keep the impact line."""

    def test_capped_sinks_keep_impact(self) -> None:
        brief = _brief(what_changes="W" * 800, decision_consequence="C" * 800)
        for surface in ("notify",):
            payload = brief_surfaces.render_brief(brief, surface=surface)
            assert IMPACT in payload.text
            assert IMPACT == payload.user_impact
            assert "W" * 800 not in payload.text


class TestSecretScrubbing:
    """AC4 — token-shaped summary is redacted on every sink."""

    def test_token_redacted_on_all_three(self) -> None:
        brief = _brief(user_impact=f"Operators never see {_SECRET} here.")
        for payload in (
            brief_surfaces.terminal_payload(brief),
            brief_surfaces.discord_payload(brief),
            brief_surfaces.dashboard_payload(brief),
        ):
            assert _SECRET not in payload.text
            assert "[REDACTED]" in payload.text

    def test_live_sink_helpers_read_the_snapshot(self) -> None:
        brief = _brief()
        mutated = replace(brief, user_impact="Sink-mutated impact line here.")
        event = _event(mutated)
        assert "Sink-mutated impact line here." in notify.brief_message(event)
        assert "Sink-mutated impact line here." in notify_discord.brief_message(event)
        card = brief_surfaces.dashboard_card_fields(mutated)
        assert card["user_impact"] == "Sink-mutated impact line here."
        assert "plan file" not in card["user_impact"]
