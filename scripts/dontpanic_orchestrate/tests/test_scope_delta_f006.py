"""Tests for plan-review F006 — mid-development scope-delta lint.

Covers the three change classes (sharpen / expand / split), both
scope-change-protocol refusal paths (budget-busting expand on a locked feature;
lossy split), the post-audit fixes (pure-add → expand; exemplar → not-sharpen),
and the F006 `plan-review --since` CLI integration wiring (operator D019).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from dontpanic_orchestrate import cli
from dontpanic_orchestrate.plan_review import scope_delta as sd

_ACTIVE_PLAN_MD = """---
id: {pid}
title: scope-delta wiring test
type: feat
tier: trivial
status: active
date: "2026-06-01"
description: F006 --since wiring test.
agents_required: [claude, codex]
loop_caps: {{max_iterations: 1, hard_stop: false}}
privacy_tier: internal
links: {{features: ./features.json}}
---
# scope-delta wiring test
## Target
```yaml
target_env: dev
target_project: none
```
"""


def _make_plan(tmp_path, pid, features):
    plan_dir = tmp_path / "docs" / "plans" / pid
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_ACTIVE_PLAN_MD.format(pid=pid))
    (plan_dir / "features.json").write_text(
        json.dumps({"task_id": pid, "schema_version": "1.0", "features": features}, indent=2)
        + "\n"
    )
    return plan_dir


# ─────────────────────────── changed-feature detection (acceptance #1) ──────


def test_changed_feature_ids_only_the_diff():
    prior = [
        {"id": "F001", "description": "a", "acceptance": "(1) x"},
        {"id": "F002", "description": "b", "acceptance": "(1) y"},
    ]
    current = [
        {"id": "F001", "description": "a", "acceptance": "(1) x"},  # unchanged
        {"id": "F002", "description": "b CHANGED", "acceptance": "(1) y"},
        {"id": "F003", "description": "new", "acceptance": "(1) z"},  # added
    ]
    assert sd.changed_feature_ids(prior, current) == {"F002", "F003"}


def test_no_change_yields_no_deltas():
    feats = [{"id": "F001", "description": "cli subcommand", "acceptance": "(1) runs"}]
    report = sd.review_scope_delta(feats, feats)
    assert report.deltas == ()
    assert not report.is_blocked


# ─────────────────────────── sharpen (acceptance #5) ────────────────────────


def test_sharpen_passes_without_friction():
    prior = [
        {
            "id": "F001",
            "description": "Add a cli subcommand",
            "acceptance": "(1) the command runs (2) exit code is 0",
        }
    ]
    current = [
        {
            "id": "F001",
            "description": "Add a cli subcommand",
            "acceptance": "(1) the command runs and prints a report (2) exit code is non-zero only on block",
        }
    ]
    report = sd.review_scope_delta(prior, current, locked_ids={"F001"})
    assert len(report.deltas) == 1
    delta = report.deltas[0]
    assert delta.kind == "sharpen"
    assert delta.refused is False
    assert not report.is_blocked


# ─────────────────────────── expand (acceptance #2/#3) ──────────────────────


def test_expand_within_budget_is_allowed():
    prior = [
        {"id": "F001", "description": "cli subcommand", "acceptance": "(1) runs (2) exits 0"}
    ]
    current = [
        {
            "id": "F001",
            "description": "cli subcommand",
            "acceptance": "(1) runs (2) exits 0 (3) prints json",
        }
    ]
    report = sd.review_scope_delta(prior, current, locked_ids={"F001"})
    delta = report.deltas[0]
    assert delta.kind == "expand"
    assert delta.refused is False
    assert delta.evidence["added_acs"] == 1


def test_expand_past_budget_on_locked_feature_is_refused():
    prior = [{"id": "F001", "description": "Add a cli subcommand", "acceptance": "(1) runs"}]
    current = [
        {
            "id": "F001",
            "description": "Add a cli subcommand AND a dashboard html view AND a doctor preflight warn",
            "acceptance": "(1) runs (2) renders (3) warns",
        }
    ]
    report = sd.review_scope_delta(prior, current, locked_ids={"F001"})
    delta = report.deltas[0]
    assert delta.kind == "expand"
    assert delta.refused is True
    assert delta.evidence["crosses_size_budget"] is True
    assert report.is_blocked
    assert "F001" in sd.render_block_message(report)


def test_expand_past_budget_with_recorded_rationale_is_allowed():
    prior = [{"id": "F001", "description": "Add a cli subcommand", "acceptance": "(1) runs"}]
    current = [
        {
            "id": "F001",
            "description": "Add a cli subcommand AND a dashboard html view AND a doctor preflight warn",
            "acceptance": "(1) runs (2) renders (3) warns",
        }
    ]
    report = sd.review_scope_delta(
        prior,
        current,
        locked_ids={"F001"},
        rationales={"F001": "intentional cross-surface widening approved by operator"},
    )
    delta = report.deltas[0]
    assert delta.kind == "expand"
    assert delta.refused is False
    assert not report.is_blocked
    assert delta.evidence["scope_change_rationale"].startswith("intentional")


def test_expand_past_budget_on_UNLOCKED_feature_not_refused():
    """The budget refusal only bites a LOCKED feature (acceptance #3)."""
    prior = [{"id": "F001", "description": "Add a cli subcommand", "acceptance": "(1) runs"}]
    current = [
        {
            "id": "F001",
            "description": "Add a cli subcommand AND a dashboard html view AND a doctor preflight warn",
            "acceptance": "(1) runs (2) renders (3) warns",
        }
    ]
    report = sd.review_scope_delta(prior, current, locked_ids=set())
    assert report.deltas[0].kind == "expand"
    assert report.deltas[0].refused is False


# ─────────────────────────── split (acceptance #4) ─────────────────────────


def test_conserving_split_is_accepted():
    prior = [{"id": "F001", "description": "big feature", "acceptance": "(1) A (2) B (3) C"}]
    current = [
        {"id": "F002", "split_of": "F001", "description": "part a", "acceptance": "(1) A (2) B"},
        {"id": "F003", "split_of": "F001", "description": "part b", "acceptance": "(3) C"},
    ]
    report = sd.review_scope_delta(prior, current)
    split = next(d for d in report.deltas if d.kind == "split")
    assert split.refused is False
    assert split.evidence["conservation_ok"] is True
    assert sorted(split.evidence["child_ids"]) == ["F002", "F003"]
    assert not report.is_blocked


def test_lossy_split_is_refused_naming_dropped_and_duplicated():
    prior = [{"id": "F001", "description": "big feature", "acceptance": "(1) A (2) B (3) C"}]
    current = [
        {"id": "F002", "split_of": "F001", "description": "part a", "acceptance": "(1) A (2) B"},
        {"id": "F003", "split_of": "F001", "description": "part b", "acceptance": "(1) Z"},
    ]
    report = sd.review_scope_delta(prior, current)
    split = next(d for d in report.deltas if d.kind == "split")
    assert split.refused is True
    assert split.evidence["conservation_ok"] is False
    assert split.evidence["dropped"] == ["C"]
    assert split.evidence["duplicated"] == ["Z"]
    assert report.is_blocked
    msg = sd.render_block_message(report)
    assert "F001" in msg and "lossy" in msg.lower()


# ─────────────── codex F006 audit i0 follow-ups (post-audit fixes) ──────────


def test_pure_add_is_classified_as_expand():
    """A brand-new feature is a change and must be classified (acceptance #2);
    it is an expand of the plan, not silently skipped."""
    prior = [{"id": "F001", "description": "cli subcommand", "acceptance": "(1) runs"}]
    current = prior + [
        {"id": "F002", "description": "new cli feature", "acceptance": "(1) does X"}
    ]
    report = sd.review_scope_delta(prior, current)
    add = next(d for d in report.deltas if d.feature_id == "F002")
    assert add.kind == "expand"
    assert add.evidence["new_feature"] is True


def test_exemplar_added_is_not_frictionless_sharpen():
    """Adding an exemplar AC (no new surface/AC count) is NOT a frictionless
    sharpen — acceptance #5 grants that only with no exemplar."""
    prior = [
        {"id": "F001", "description": "cli subcommand", "acceptance": "(1) the command runs"}
    ]
    current = [
        {
            "id": "F001",
            "description": "cli subcommand",
            "acceptance": "(1) the command runs e.g. fast mode and slow mode",
        }
    ]
    report = sd.review_scope_delta(prior, current)
    delta = report.deltas[0]
    assert delta.evidence["new_exemplar"] is True
    assert delta.kind == "expand"


# ─────────── F006 CLI wiring: plan-review --since (D019, operator-chosen) ────


def _feature(fid, desc, acc):
    return {
        "id": fid,
        "category": "tooling",
        "phase": 0,
        "description": desc,
        "steps": [],
        "acceptance": acc,
        "passes": False,
        "depends_on": [],
    }


def test_plan_review_since_runs_scope_delta_and_refuses_budget_expand(tmp_path):
    """The concrete integration path: `plan-review <plan> --since <prior>` runs
    review_scope_delta on a plan-artifact change and exits non-zero when the
    scope-change protocol refuses (budget-busting expand on an active plan)."""
    prior_feat = _feature("F001", "Add a cli subcommand", "(1) runs")
    current_feat = _feature(
        "F001",
        "Add a cli subcommand AND a dashboard html view AND a doctor preflight warn",
        "(1) runs (2) renders (3) warns",
    )
    plan_dir = _make_plan(tmp_path, "2026-06-01-901-feat-since", [current_feat])
    prior = tmp_path / "prior-features.json"
    prior.write_text(json.dumps({"features": [prior_feat]}) + "\n")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli.main(["plan-review", str(plan_dir), "--since", str(prior)])
    text = out.getvalue()
    assert rc == 1
    assert "scope-delta" in text
    assert "expand" in text and "REFUSED" in text
    assert "F001" in text


def test_plan_review_since_sharpen_passes(tmp_path):
    """A sharpen (no new surface/AC/exemplar) on an active plan passes (exit 0)."""
    prior_feat = _feature("F001", "Add a cli subcommand", "(1) the command runs")
    current_feat = _feature(
        "F001", "Add a cli subcommand", "(1) the command runs and prints a report"
    )
    plan_dir = _make_plan(tmp_path, "2026-06-01-902-feat-since-ok", [current_feat])
    prior = tmp_path / "prior-features.json"
    prior.write_text(json.dumps({"features": [prior_feat]}) + "\n")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli.main(["plan-review", str(plan_dir), "--since", str(prior)])
    assert rc == 0
    assert "sharpen" in out.getvalue()
