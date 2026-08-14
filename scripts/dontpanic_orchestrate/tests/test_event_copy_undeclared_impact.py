"""Plan 2026-08-09-002 F006 — honesty rules for undeclared and stale impact.

Acceptance clause 6 names this module and requires it to cover the other five.
Each class below maps to one clause and the class docstring says which.

The thing these tests exist to prevent is a renderer that fills silence with
invention. Every assertion here is therefore written to fail if the renderer
starts *saying something* where it currently says "not declared", or presents a
stale claim as a current one. Two of the classes additionally carry an
anti-vacuity guard: a test that would still pass if the mechanism it checks
were deleted is worse than no test, because it converts an absent guarantee
into a green tick.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import cli, decision_brief, event_copy, notify_event

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

PLAN_ID = "2026-08-09-002-feat-decision-brief-at-gates"


def _brief(status: decision_brief.BriefStatus, **over):
    """A DecisionBrief in the given status, with sane declared defaults."""
    base = {
        "what_changes": "Rewrite the approval headline",
        "user_impact": "Operators read the outcome before the plan id.",
        "affected_audience": "operator",
        "decision_consequence": "Clearing pre_merge lets the volley continue.",
        "reversible": True,
        "status": status,
        "surfaces": ("backend",),
    }
    base.update(over)
    return decision_brief.DecisionBrief(**base)


def _event(*, brief=None, feature_id: str | None = "F006"):
    return notify_event.NotifyEvent(
        kind="gate_paused",
        severity="action_required",
        plan_id=PLAN_ID,
        feature_id=feature_id,
        body="**Gate pause** (implement) — awaiting: pre_merge",
        inbox_event="gate_hit",
        subtype="implement",
        decision_brief=brief,
    )


def _rendered_text(rendered) -> str:
    """Every string slot of a RenderedEvent, joined — what an operator sees."""
    return " ".join(
        str(getattr(rendered, f.name) or "")
        for f in dataclasses.fields(rendered)
        if isinstance(getattr(rendered, f.name, None), str)
    )


def _write_plan(tmp_path: Path, *, surfaces, features) -> Path:
    """A minimal on-disk plan the loader and the advisory both accept."""
    d = tmp_path / PLAN_ID
    d.mkdir(parents=True, exist_ok=True)
    surface_lines = "".join(f"\n  - {s}" for s in surfaces)
    (d / "plan.md").write_text(
        "---\n"
        f"id: {PLAN_ID}\n"
        "title: Fixture plan\n"
        "type: feat\n"
        "tier: local\n"
        "status: active\n"
        'date: "2026-08-09"\n'
        "description: >\n"
        "  Fixture plan used by F006 tests to exercise the lock-time advisory.\n"
        f"surfaces:{surface_lines}\n"
        "links:\n"
        "  features: ./features.json\n"
        "---\n\n"
        "# Fixture\n\n"
        "## Target\n\n"
        "```yaml\n"
        "target_env: dev\n"
        "target_project: none\n"
        "```\n"
    )
    (d / "features.json").write_text(
        json.dumps(
            {"task_id": PLAN_ID, "schema_version": "1.0", "features": features},
            indent=2,
        )
    )
    return d


def _feature(fid: str, *, impact: dict | None = None) -> dict:
    f = {
        "id": fid,
        "category": "functional",
        "description": f"Feature {fid} does something worth describing",
        "acceptance": "It works",
        "passes": False,
    }
    if impact is not None:
        f["user_impact"] = impact
    return f


# --------------------------------------------------------------------------
# AC1 — undeclared renders the exact sentence and invents nothing
# --------------------------------------------------------------------------


class TestUndeclaredRendersTheExactSentence:
    """Acceptance clause 1."""

    def test_undeclared_brief_renders_the_literal_sentence(self):
        r = event_copy.render(_event(brief=_brief(decision_brief.BriefStatus.UNDECLARED)))
        assert r is not None
        assert event_copy.UNDECLARED_IMPACT_SENTENCE in _rendered_text(r)

    def test_undeclared_invents_nothing_in_place_of_the_missing_summary(self):
        """The realistic shape: classify_status gives UNDECLARED for a feature
        with no ``user_impact``, and no summary exists to render."""
        b = _brief(decision_brief.BriefStatus.UNDECLARED, user_impact=None)
        text = _rendered_text(event_copy.render(_event(brief=b)))
        assert event_copy.UNDECLARED_IMPACT_SENTENCE in text
        assert "None" not in text  # not a stringified null standing in for prose

    def test_undeclared_status_comes_from_an_absent_declaration(self):
        """Anchors the above in the real classifier rather than a hand-built enum."""
        feature = {
            "id": "F001",
            "category": "functional",
            "description": "A feature that declares no user impact at all",
            "acceptance": "It works",
            "passes": False,
        }
        assert decision_brief.classify_status(feature) is (
            decision_brief.BriefStatus.UNDECLARED
        )
        assert decision_brief.classify_status(None) is (
            decision_brief.BriefStatus.UNDECLARED
        )

    def test_summary_content_currently_outranks_undeclared_status(self):
        """Documents observed precedence — not an endorsement of it.

        A brief carrying ``status=UNDECLARED`` *and* a non-empty summary is not
        reachable through :func:`decision_brief.classify_status`, because the
        summary and the status are derived from the same absent block. Should a
        future caller construct one by hand, the summary wins and the operator
        sees a claim rather than the undeclared sentence. Pinned here so that
        behaviour is a recorded fact rather than a surprise; if the renderer is
        later hardened to let status suppress content, this test is the one to
        invert.
        """
        b = _brief(
            decision_brief.BriefStatus.UNDECLARED,
            user_impact="A claim nobody actually declared.",
        )
        assert "A claim nobody actually declared." in _rendered_text(
            event_copy.render(_event(brief=b))
        )

    def test_plan_level_pause_uses_the_plan_level_sentence(self):
        """No feature in scope — "this feature" would name something absent."""
        b = _brief(decision_brief.BriefStatus.UNDECLARED)
        text = _rendered_text(event_copy.render(_event(brief=b, feature_id=None)))
        assert event_copy.PLAN_LEVEL_UNDECLARED_IMPACT_SENTENCE in text

    def test_the_sentence_is_a_module_constant_not_an_inline_literal(self):
        """Anti-vacuity: the assertions above must not be tautological.

        If the sentence were rebuilt inline at the render site, a reworded
        template would silently diverge from what this module asserts while
        every test above still passed against its own copy of the string.
        """
        src = Path(event_copy.__file__).read_text()
        assert src.count('"User impact not declared for this feature."') == 1


# --------------------------------------------------------------------------
# AC2 — a stale declaration is shown, but never as current
# --------------------------------------------------------------------------


class TestStaleIsShownButLabelled:
    """Acceptance clause 2."""

    def test_stale_summary_survives_verbatim(self):
        b = _brief(
            decision_brief.BriefStatus.POSSIBLY_STALE,
            user_impact="Operators see the outcome first.",
        )
        assert "Operators see the outcome first." in _rendered_text(
            event_copy.render(_event(brief=b))
        )

    def test_stale_summary_is_prefixed_with_the_staleness_label(self):
        b = _brief(decision_brief.BriefStatus.POSSIBLY_STALE)
        assert event_copy.STALE_IMPACT_PREFIX in _rendered_text(
            event_copy.render(_event(brief=b))
        )

    def test_declared_is_not_labelled_stale(self):
        """The label must discriminate, not decorate every render."""
        b = _brief(decision_brief.BriefStatus.DECLARED)
        assert event_copy.STALE_IMPACT_PREFIX not in _rendered_text(
            event_copy.render(_event(brief=b))
        )

    def test_stale_and_declared_render_differently(self):
        """Anti-vacuity: the two statuses must not collapse to one string."""
        declared = _rendered_text(
            event_copy.render(_event(brief=_brief(decision_brief.BriefStatus.DECLARED)))
        )
        stale = _rendered_text(
            event_copy.render(
                _event(brief=_brief(decision_brief.BriefStatus.POSSIBLY_STALE))
            )
        )
        assert declared != stale


# --------------------------------------------------------------------------
# AC3 — the source-level non-generative assertion
# --------------------------------------------------------------------------


class TestNonGenerativeScanner:
    """Acceptance clause 3."""

    def test_the_module_scans_clean(self):
        assert event_copy.scan_non_generative_copy().violations == ()

    def test_the_scan_is_not_vacuous(self):
        """A pass earned over zero expressions is not a pass."""
        scan = event_copy.scan_non_generative_copy()
        assert scan.copy_expressions_checked > 0
        assert scan.copy_keywords_checked > 0
        assert scan.brief_attributes_seen  # renders the brief, so must see it

    @pytest.mark.parametrize(
        "slot",
        ["what_changes", "user_impact", "affected_audience"],
    )
    def test_routing_a_brief_slot_to_an_unenumerated_attribute_is_caught(self, slot):
        """The mutation the i2 audit found escaping: read a non-brief field."""
        src = Path(event_copy.__file__).read_text()
        anchor = f'"{slot}": getattr(brief, "'
        assert anchor in src, f"anchor moved for {slot}"
        i = src.index(anchor) + len(anchor)
        j = src.index('"', i)
        mutated = src[:i] + "model_output" + src[j:]
        assert event_copy.scan_non_generative_copy(mutated).violations, (
            f"scanner did not catch {slot} -> brief.model_output"
        )


# --------------------------------------------------------------------------
# AC4 / AC5 — the lock-time advisory
# --------------------------------------------------------------------------


class TestPlanLockAdvisory:
    """Acceptance clauses 4 and 5."""

    def test_names_every_feature_that_owes_a_declaration(self, tmp_path, capsys):
        d = _write_plan(
            tmp_path,
            surfaces=["backend", "ux"],
            features=[_feature("F001"), _feature("F002")],
        )
        assert cli._emit_plan_lock_undeclared_impact_advisory(d) is None
        out = capsys.readouterr().out
        assert "F001" in out and "F002" in out

    def test_advisory_points_at_the_file_to_edit(self, tmp_path, capsys):
        d = _write_plan(tmp_path, surfaces=["ux"], features=[_feature("F001")])
        cli._emit_plan_lock_undeclared_impact_advisory(d)
        assert "features.json" in capsys.readouterr().out

    def test_silent_when_every_feature_declares(self, tmp_path, capsys):
        d = _write_plan(
            tmp_path,
            surfaces=["ux"],
            features=[
                _feature(
                    "F001",
                    impact={
                        "audience": "operator",
                        "summary": "Operators see the gate that is blocking.",
                        "surfaces": ["ux"],
                        # D005: the claim is bound to the description it was
                        # written against, so the schema requires the digest.
                        "description_hash": decision_brief.description_digest(
                            _feature("F001")["description"]
                        ),
                    },
                )
            ],
        )
        assert cli._emit_plan_lock_undeclared_impact_advisory(d) is None
        assert capsys.readouterr().out == ""

    def test_audience_none_is_a_complete_declaration(self, tmp_path, capsys):
        """D003: declaring "nobody feels this" answers the question."""
        d = _write_plan(
            tmp_path,
            surfaces=["ux"],
            features=[_feature("F001", impact={"audience": "none"})],
        )
        cli._emit_plan_lock_undeclared_impact_advisory(d)
        assert capsys.readouterr().out == ""

    def test_advisory_never_refuses_the_lock(self, tmp_path):
        """D004: it prints and returns; it must not raise or exit non-zero."""
        d = _write_plan(
            tmp_path, surfaces=["backend", "ux"], features=[_feature("F001")]
        )
        assert cli._emit_plan_lock_undeclared_impact_advisory(d) is None

    def test_advisory_helper_discriminates(self):
        """Anti-vacuity: silence must come from the data, not from never firing."""
        undeclared = decision_brief.undeclared_impact_advisory(
            plan_surfaces=["ux"], features=[_feature("F001")]
        )
        declared = decision_brief.undeclared_impact_advisory(
            plan_surfaces=["ux"],
            features=[_feature("F001", impact={"audience": "none"})],
        )
        assert decision_brief.render_undeclared_impact_advisory(
            undeclared, features_path="features.json"
        )
        assert (
            decision_brief.render_undeclared_impact_advisory(
                declared, features_path="features.json"
            )
            == ()
        )
