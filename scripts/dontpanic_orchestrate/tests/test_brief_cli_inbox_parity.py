"""Plan 2026-08-09-002 F007 — CLI approve/resume and INBOX share one snapshot.

Acceptance maps one class per clause:

  1. The approve prompt shows the same three brief elements as the INBOX entry.
  2. Both read the snapshot: mutating it changes both outputs.
  3. A summary that exceeds the cap keeps the impact line and shortens support.
  4. Secret scrubbing runs over both payloads.

The thing these tests exist to prevent is a sink that re-derives impact from
plan artifacts (or invents it) at a different moment than the pause snapshot.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from dontpanic_orchestrate import brief_surfaces, decision_brief, inbox
from dontpanic_orchestrate.decision_brief import BriefStatus, DecisionBrief

# Canonical GitHub PAT shape from test_f001_secret_shapes — synthetic only.
_SECRET = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"

WHAT = "Rewrite the approval headline so product outcome leads."
IMPACT = "Operators read the outcome before the plan id."
CONSEQUENCE = "Clearing pre_merge lets the implementer run on F007."


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


def _three(payload: brief_surfaces.BriefPayload) -> tuple[str, str, str]:
    return (
        payload.what_changes,
        payload.user_impact,
        payload.decision_consequence,
    )


class TestApprovePromptMatchesInbox:
    """AC1 — same three brief elements on both surfaces."""

    def test_three_elements_present_and_equal(self) -> None:
        brief = _brief()
        approve = brief_surfaces.format_approve_prompt(brief)
        inbox_text = brief_surfaces.format_inbox_brief(brief)
        for text in (approve, inbox_text):
            assert WHAT in text
            assert IMPACT in text
            assert CONSEQUENCE in text
        assert _three(brief_surfaces.render_brief(brief, surface="cli")) == _three(
            brief_surfaces.render_brief(brief, surface="inbox")
        )


class TestBothReadTheSnapshot:
    """AC2 — mutating the snapshot changes both outputs.

    If either surface re-derived from a plan file, replacing the snapshot
    would leave that surface's text unchanged.
    """

    def test_mutated_snapshot_reaches_both_surfaces(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "features.json"
        plan_file.write_text('{"features":[{"id":"F007","description":"plan file"}]}')
        original = _brief()
        before_cli = brief_surfaces.format_approve_prompt(original)
        before_inbox = brief_surfaces.format_inbox_brief(original)
        mutated = replace(
            original,
            user_impact="Mutated impact line that is long enough.",
            what_changes="Mutated what-changes line for the snapshot test.",
            decision_consequence="Mutated consequence of approving this gate.",
        )
        after_cli = brief_surfaces.format_approve_prompt(mutated)
        after_inbox = brief_surfaces.format_inbox_brief(mutated)
        assert after_cli != before_cli
        assert after_inbox != before_inbox
        for text in (after_cli, after_inbox):
            assert "Mutated impact line that is long enough." in text
            assert "Mutated what-changes line for the snapshot test." in text
            assert "Mutated consequence of approving this gate." in text
            assert IMPACT not in text
        # The on-disk plan was never consulted.
        assert "plan file" not in after_cli
        assert "plan file" not in after_inbox

    def test_inbox_annotation_reads_the_snapshot(self, tmp_path: Path) -> None:
        brief = _brief()
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()

        class _Rendered:
            title = "Approval needed"
            detail = "orchestration prose"
            exact_command = "dontpanic approve demo pre_merge"
            evidence_uri = None
            band = "needs_action"
            technical_metadata = {}

        inbox.append_rendered_annotation(
            plan_dir,
            plan_id="demo",
            rendered=_Rendered(),
            brief=brief,
        )
        body = (plan_dir / "INBOX.md").read_text()
        assert IMPACT in body
        assert WHAT in body
        assert CONSEQUENCE in body


class TestTruncationKeepsImpact:
    """AC3 — over-cap supporting detail shortens; the impact line survives."""

    def test_long_support_is_clipped_impact_is_not(self) -> None:
        long_what = "W" * 800
        long_cons = "C" * 800
        brief = _brief(what_changes=long_what, decision_consequence=long_cons)
        payload = brief_surfaces.render_brief(brief, surface="cli")
        assert IMPACT in payload.text
        assert IMPACT == payload.user_impact
        assert long_what not in payload.text
        assert long_cons not in payload.text
        assert payload.what_changes.endswith("…")
        assert payload.decision_consequence.endswith("…")
        assert payload.what_changes.startswith("W")
        assert payload.decision_consequence.startswith("C")


class TestSecretScrubbing:
    """AC4 — a token-shaped string planted in the summary is redacted on both."""

    def test_token_redacted_on_cli_and_inbox(self) -> None:
        brief = _brief(
            user_impact=f"Operators never see {_SECRET} in the prompt."
        )
        for surface in ("cli", "inbox"):
            text = brief_surfaces.render_brief(brief, surface=surface).text
            assert _SECRET not in text
            assert "[REDACTED]" in text
            assert "Operators never see" in text
