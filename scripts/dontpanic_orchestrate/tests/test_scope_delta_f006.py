"""Tests for plan-review F006 — mid-development scope-delta lint.

Covers the three change classes (sharpen / expand / split) and both
scope-change-protocol refusal paths (budget-busting expand on a locked feature;
lossy split), per acceptance #2/#3/#4/#5/#6.
"""

from __future__ import annotations

from dontpanic_orchestrate.plan_review import scope_delta as sd

# ─────────────────────────── changed-feature detection (acceptance #1) ──────


def test_changed_feature_ids_only_the_diff():
    prior = [
        {"id": "F1", "description": "a", "acceptance": "(1) x"},
        {"id": "F2", "description": "b", "acceptance": "(1) y"},
    ]
    current = [
        {"id": "F1", "description": "a", "acceptance": "(1) x"},  # unchanged
        {"id": "F2", "description": "b CHANGED", "acceptance": "(1) y"},
        {"id": "F3", "description": "new", "acceptance": "(1) z"},  # added
    ]
    assert sd.changed_feature_ids(prior, current) == {"F2", "F3"}


def test_no_change_yields_no_deltas():
    feats = [{"id": "F1", "description": "cli subcommand", "acceptance": "(1) runs"}]
    report = sd.review_scope_delta(feats, feats)
    assert report.deltas == ()
    assert not report.is_blocked


# ─────────────────────────── sharpen (acceptance #5) ────────────────────────


def test_sharpen_passes_without_friction():
    prior = [
        {
            "id": "F1",
            "description": "Add a cli subcommand",
            "acceptance": "(1) the command runs (2) exit code is 0",
        }
    ]
    current = [
        {
            "id": "F1",
            "description": "Add a cli subcommand",
            # concretised wording, SAME surface (cli), SAME ac count.
            "acceptance": "(1) the command runs and prints a report (2) exit code is non-zero only on block",
        }
    ]
    report = sd.review_scope_delta(prior, current, locked_ids={"F1"})
    assert len(report.deltas) == 1
    delta = report.deltas[0]
    assert delta.kind == "sharpen"
    assert delta.refused is False
    assert not report.is_blocked


# ─────────────────────────── expand (acceptance #2/#3) ──────────────────────


def test_expand_within_budget_is_allowed():
    prior = [
        {"id": "F1", "description": "cli subcommand", "acceptance": "(1) runs (2) exits 0"}
    ]
    current = [
        {
            "id": "F1",
            "description": "cli subcommand",
            "acceptance": "(1) runs (2) exits 0 (3) prints json",  # +1 AC, still 1 surface
        }
    ]
    report = sd.review_scope_delta(prior, current, locked_ids={"F1"})
    delta = report.deltas[0]
    assert delta.kind == "expand"
    assert delta.refused is False
    assert delta.evidence["added_acs"] == 1


def test_expand_past_budget_on_locked_feature_is_refused():
    prior = [
        {"id": "F1", "description": "Add a cli subcommand", "acceptance": "(1) runs"}
    ]
    current = [
        {
            "id": "F1",
            # now spans 3 surfaces: cli + dashboard (html) + doctor (preflight warn)
            "description": "Add a cli subcommand AND a dashboard html view AND a doctor preflight warn",
            "acceptance": "(1) runs (2) renders (3) warns",
        }
    ]
    report = sd.review_scope_delta(prior, current, locked_ids={"F1"})
    delta = report.deltas[0]
    assert delta.kind == "expand"
    assert delta.refused is True
    assert delta.evidence["crosses_size_budget"] is True
    assert report.is_blocked
    assert "F1" in sd.render_block_message(report)


def test_expand_past_budget_with_recorded_rationale_is_allowed():
    prior = [
        {"id": "F1", "description": "Add a cli subcommand", "acceptance": "(1) runs"}
    ]
    current = [
        {
            "id": "F1",
            "description": "Add a cli subcommand AND a dashboard html view AND a doctor preflight warn",
            "acceptance": "(1) runs (2) renders (3) warns",
        }
    ]
    report = sd.review_scope_delta(
        prior,
        current,
        locked_ids={"F1"},
        rationales={"F1": "intentional cross-surface widening approved by operator"},
    )
    delta = report.deltas[0]
    assert delta.kind == "expand"
    assert delta.refused is False
    assert not report.is_blocked
    assert delta.evidence["scope_change_rationale"].startswith("intentional")


def test_expand_past_budget_on_UNLOCKED_feature_not_refused():
    """The budget refusal only bites a LOCKED feature (acceptance #3)."""
    prior = [{"id": "F1", "description": "Add a cli subcommand", "acceptance": "(1) runs"}]
    current = [
        {
            "id": "F1",
            "description": "Add a cli subcommand AND a dashboard html view AND a doctor preflight warn",
            "acceptance": "(1) runs (2) renders (3) warns",
        }
    ]
    report = sd.review_scope_delta(prior, current, locked_ids=set())  # not locked
    assert report.deltas[0].kind == "expand"
    assert report.deltas[0].refused is False


# ─────────────────────────── split (acceptance #4) ─────────────────────────


def test_conserving_split_is_accepted():
    prior = [
        {"id": "F1", "description": "big feature", "acceptance": "(1) A (2) B (3) C"}
    ]
    current = [
        {"id": "F1a", "split_of": "F1", "description": "part a", "acceptance": "(1) A (2) B"},
        {"id": "F1b", "split_of": "F1", "description": "part b", "acceptance": "(3) C"},
    ]
    report = sd.review_scope_delta(prior, current)
    split = next(d for d in report.deltas if d.kind == "split")
    assert split.refused is False
    assert split.evidence["conservation_ok"] is True
    assert sorted(split.evidence["child_ids"]) == ["F1a", "F1b"]
    assert not report.is_blocked


def test_lossy_split_is_refused_naming_dropped_and_duplicated():
    prior = [
        {"id": "F1", "description": "big feature", "acceptance": "(1) A (2) B (3) C"}
    ]
    current = [
        # drops C, introduces Z (not in the parent) -> lossy
        {"id": "F1a", "split_of": "F1", "description": "part a", "acceptance": "(1) A (2) B"},
        {"id": "F1b", "split_of": "F1", "description": "part b", "acceptance": "(1) Z"},
    ]
    report = sd.review_scope_delta(prior, current)
    split = next(d for d in report.deltas if d.kind == "split")
    assert split.refused is True
    assert split.evidence["conservation_ok"] is False
    assert split.evidence["dropped"] == ["C"]
    assert split.evidence["duplicated"] == ["Z"]
    assert report.is_blocked
    msg = sd.render_block_message(report)
    assert "F1" in msg and "lossy" in msg.lower()


# ─────────────── codex F006 audit i0 follow-ups (post-audit fixes) ──────────


def test_pure_add_is_classified_as_expand():
    """A brand-new feature is a change and must be classified (acceptance #2);
    it is an expand of the plan, not silently skipped."""
    prior = [{"id": "F1", "description": "cli subcommand", "acceptance": "(1) runs"}]
    current = prior + [
        {"id": "F2", "description": "new cli feature", "acceptance": "(1) does X"}
    ]
    report = sd.review_scope_delta(prior, current)
    add = next(d for d in report.deltas if d.feature_id == "F2")
    assert add.kind == "expand"
    assert add.evidence["new_feature"] is True


def test_exemplar_added_is_not_frictionless_sharpen():
    """Adding an exemplar AC (no new surface, no new AC count) is NOT a
    frictionless sharpen — acceptance #5 grants that only with no exemplar."""
    prior = [
        {"id": "F1", "description": "cli subcommand", "acceptance": "(1) the command runs"}
    ]
    current = [
        {
            "id": "F1",
            "description": "cli subcommand",
            # same AC count + surface, but now an exemplar enumeration with no
            # co-located universal -> exemplar_ac flag fires.
            "acceptance": "(1) the command runs e.g. fast mode and slow mode",
        }
    ]
    report = sd.review_scope_delta(prior, current)
    delta = report.deltas[0]
    assert delta.evidence["new_exemplar"] is True
    assert delta.kind == "expand"  # NOT frictionless sharpen
