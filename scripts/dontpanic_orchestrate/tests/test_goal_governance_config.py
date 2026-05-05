"""Plan 2026-05-05-002 F0 — goal-governance nested-orchestration config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from dontpanic_orchestrate.nested_orchestration import (
    DEFAULT_DEPTH_LIMIT,
    GOAL_GAP_MAX_CHILD_PLANS_PER_PARENT_PASS,
    GOAL_GAP_MAX_NESTING_DEPTH,
    GOAL_GOVERNANCE_EVIDENCE_PREFIX,
    ChildCharter,
    GoalGapClusterContext,
    GoalGapFinding,
    NestedOrchestrationError,
    ReturnConditionError,
    build_goal_gap_charter,
    check_cycle,
    check_depth,
    check_repeated_finding,
    classify_goal_gap_cluster,
    compute_finding_signature,
    goal_governance_evidence_path,
    parse_goal_gap_fan_in_memo_fields,
    parse_return_condition_section,
    validate_goal_gap_child_plan_caps,
)


def _finding(
    severity: str = "medium",
    *,
    subsystem: str = "creator-hub",
    journey: str = "publish",
    issue: str = "gap",
) -> GoalGapFinding:
    return GoalGapFinding(
        severity=severity,
        finding_id=issue.replace(" ", "-"),
        issue=issue,
        subsystem=subsystem,
        journey=journey,
    )


def _cluster(**overrides: object) -> GoalGapClusterContext:
    data: dict[str, object] = {
        "subsystem": "creator-hub",
        "journey": "publish",
        "coherence_rule": "subsystem_and_journey",
    }
    data.update(overrides)
    return GoalGapClusterContext.model_validate(data)


def _write_plan(
    plans_root: Path,
    plan_id: str,
    *,
    parent: str | None = None,
    signature: str | None = None,
    depth_limit: int = DEFAULT_DEPTH_LIMIT,
) -> Path:
    plan_dir = plans_root / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    orchestration = ""
    if parent is not None:
        spawn = ""
        if signature is not None:
            spawn = f"""
  spawn_finding:
    parent_audit_id: "{parent}#codex#0"
    finding_id: "finding-1"
    finding_code: "GOV"
    finding_class: "goal_gap"
    finding_signature: "{signature}"
"""
        orchestration = f"""
orchestration:
  parent_plan_id: "{parent}"
  spawn_reason: {"auditor_finding" if signature else "operator_manual"}
  depth_limit: {depth_limit}
{spawn if signature else ""}
"""

    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: {plan_id}
type: infra
tier: trivial
status: active
date: "2026-05-05"
description: synthetic F0 test plan
agents_required:
  - claude
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
{orchestration}---

# Synthetic
"""
    )
    (plan_dir / "features.json").write_text(json.dumps({"features": []}))
    return plan_dir


def test_classifier_returns_child_plan_for_threshold_cluster() -> None:
    findings = [
        _finding("low", issue="gap 1"),
        _finding("medium", issue="gap 2"),
        _finding("advisory", issue="gap 3"),
    ]
    assert classify_goal_gap_cluster(findings, _cluster()) == "child_plan"


def test_classifier_does_not_child_plan_for_advisory_only_cluster() -> None:
    findings = [_finding("advisory", issue=f"gap {i}") for i in range(5)]
    assert classify_goal_gap_cluster(findings, _cluster()) == "operator_deferred"


def test_classifier_requires_subsystem_and_journey_coherence() -> None:
    findings = [_finding("high", issue=f"gap {i}") for i in range(5)]
    assert (
        classify_goal_gap_cluster(findings, _cluster(coherence_rule="same_subsystem"))
        == "operator_deferred"
    )


def test_classifier_inline_fix_for_small_low_scope_fit() -> None:
    findings = [_finding("low", issue="minor gap")]
    assert (
        classify_goal_gap_cluster(
            findings,
            _cluster(fits_existing_feature_scope=True),
        )
        == "inline_fix"
    )


def test_classifier_follow_up_for_out_of_scope_cluster() -> None:
    findings = [_finding("critical", issue="future scope")]
    assert (
        classify_goal_gap_cluster(findings, _cluster(explicitly_out_of_scope=True))
        == "follow_up_plan"
    )


def test_unknown_severity_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown goal-gap severity"):
        _finding("urgent")


def test_cap_helper_rejects_fourth_child() -> None:
    with pytest.raises(ValueError, match="child-plan cap exceeded"):
        validate_goal_gap_child_plan_caps(
            ["a", "b", "c"],
            max_children=GOAL_GAP_MAX_CHILD_PLANS_PER_PARENT_PASS,
        )


def test_cap_helper_rejects_depth_beyond_goal_gap_cap() -> None:
    with pytest.raises(ValueError, match="nesting depth cap exceeded"):
        validate_goal_gap_child_plan_caps(
            [],
            current_depth=GOAL_GAP_MAX_NESTING_DEPTH,
        )


def test_goal_governance_evidence_path() -> None:
    path = goal_governance_evidence_path(
        Path("/repo/docs/plans/p"),
        "pre_impl",
        "sufficiency-findings.json",
    )
    assert str(path).endswith(
        f"docs/plans/p/{GOAL_GOVERNANCE_EVIDENCE_PREFIX}/pre_impl/sufficiency-findings.json"
    )


def test_goal_governance_evidence_path_rejects_escape() -> None:
    with pytest.raises(ValueError, match="stay under evidence prefix"):
        goal_governance_evidence_path(Path("/repo/p"), "post_impl", "../escape.json")


def test_build_goal_gap_charter_rejects_short_rationale() -> None:
    with pytest.raises(ValueError, match="why_child_plan_not_feature"):
        build_goal_gap_charter(
            parent_objective_contract_id="obj-creator-hub",
            gap_class="journey_coverage",
            cluster_scope={"subsystem": "creator-hub", "journey": "publish"},
            severity="medium",
            surfaces_affected=["web"],
            why_child_plan_not_feature="too short",
            existing_goal_gap_children=[],
        )


def test_build_goal_gap_charter_renders_required_fields() -> None:
    rendered = build_goal_gap_charter(
        parent_objective_contract_id="obj-creator-hub",
        gap_class="journey_coverage",
        cluster_scope={"subsystem": "creator-hub", "journey": "publish"},
        severity="high",
        surfaces_affected=["web", "backend"],
        why_child_plan_not_feature=(
            "The publish journey spans frontend, backend, and approval state."
        ),
        existing_goal_gap_children=[],
        allowed_paths=["apps/web/**", "functions/**"],
    )
    parsed = yaml.safe_load(rendered)
    charter = ChildCharter.model_validate(parsed["child_charter"])
    assert "goal_gap" not in parsed["child_charter"]
    assert charter.allowed_paths == ["apps/web/**", "functions/**"]
    assert "journey_coverage" in charter.return_condition_summary
    assert '# parent_objective_contract_id: "obj-creator-hub"' in rendered
    assert '# gap_class: "journey_coverage"' in rendered
    assert '# severity: "high"' in rendered
    assert "# why_child_plan_not_feature:" in rendered


def test_build_goal_gap_charter_enforces_cap() -> None:
    with pytest.raises(ValueError, match="child-plan cap exceeded"):
        build_goal_gap_charter(
            parent_objective_contract_id="obj-creator-hub",
            gap_class="journey_coverage",
            cluster_scope={"subsystem": "creator-hub", "journey": "publish"},
            severity="medium",
            surfaces_affected=["web"],
            why_child_plan_not_feature=(
                "The publish journey spans enough surfaces to need a child plan."
            ),
            existing_goal_gap_children=["a", "b", "c"],
        )


def test_goal_gap_fan_in_parser_requires_objective_contract_id(tmp_path: Path) -> None:
    memo = tmp_path / "memo.md"
    memo.write_text(
        """# Fan-in

gap_class_closed: journey_coverage

## Return Condition

status: satisfied
"""
    )
    with pytest.raises(ReturnConditionError, match="objective_contract_id"):
        parse_goal_gap_fan_in_memo_fields(memo)


def test_goal_gap_fan_in_parser_reads_fields_and_status(tmp_path: Path) -> None:
    memo = tmp_path / "memo.md"
    memo.write_text(
        """# Fan-in

objective_contract_id: obj-creator-hub
gap_class_closed: journey_coverage

## Return Condition

status: satisfied
"""
    )
    assert parse_return_condition_section(memo) == "satisfied"
    assert parse_goal_gap_fan_in_memo_fields(memo) == {
        "objective_contract_id": "obj-creator-hub",
        "gap_class_closed": "journey_coverage",
    }


def test_goal_gap_child_still_hits_depth_guard(tmp_path: Path) -> None:
    root = tmp_path / "plans"
    parent = _write_plan(root, "parent")
    child = _write_plan(root, "child", parent=parent.name, depth_limit=1)

    with pytest.raises(NestedOrchestrationError, match="depth"):
        check_depth(child, plans_root=root)


def test_goal_gap_child_still_hits_cycle_guard(tmp_path: Path) -> None:
    root = tmp_path / "plans"
    _write_plan(root, "a", parent="b")
    b = _write_plan(root, "b", parent="a")

    with pytest.raises(NestedOrchestrationError, match="cycle"):
        check_cycle(b, plans_root=root)


def test_goal_gap_child_still_hits_repeated_finding_guard(tmp_path: Path) -> None:
    root = tmp_path / "plans"
    sig = compute_finding_signature("GOV", "goal_gap", "same goal gap")
    _write_plan(root, "grandparent")
    _write_plan(root, "parent", parent="grandparent", signature=sig)
    child = _write_plan(root, "child", parent="parent", signature=sig)

    with pytest.raises(NestedOrchestrationError, match="repeated finding"):
        check_repeated_finding(child, plans_root=root)
