"""Plan 2026-05-02-003 F002 — child_charter + commit_policy parsing/validation,
return-condition section parsing (D004), and signoff-time compliance check.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_child_charter.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import plan_loader, signoff_writer  # noqa: E402
from jarvis_orchestrate.nested_orchestration import (  # noqa: E402
    ChildCharter,
    ChildCharterViolation,
    CommitPolicy,
    ReturnConditionError,
    check_child_charter_compliance,
    parse_return_condition_section,
    validate_charter_policy_consistency,
)

# ──────────────────────────────  fixtures  ──────────────────────────────


def _valid_charter_kwargs(**overrides):
    base = dict(
        kind="implementation",
        parent_objective="resolve EC5 finding from parent audit",
        parent_acceptance_item="parent acceptance #3 (EC5 severity gate)",
        allowed_paths=["scripts/jarvis_orchestrate/**", "docs/plans/**"],
        forbidden_decisions=[],
        return_condition_summary="EC5 finding closed with passing audits",
        may_edit_product_code=True,
        may_spawn_children=False,
    )
    base.update(overrides)
    return base


def _make_plan_dir(
    tmp_path: Path,
    plan_id: str,
    *,
    orchestration_block: str = "",
    charter_block: str = "",
    commit_policy_block: str = "",
    target_project: str = "jarvis-a6ee1",
) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)

    extra_blocks = ""
    if orchestration_block:
        extra_blocks += orchestration_block
    if charter_block:
        extra_blocks += charter_block
    if commit_policy_block:
        extra_blocks += commit_policy_block

    plan_md = f"""---
id: {plan_id}
title: F002 charter test plan
type: infra
tier: trivial
status: active
date: "2026-05-02"
description: Synthetic plan for child_charter/commit_policy tests.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
{extra_blocks}---

# F002 charter test plan

## Target

```yaml
target_env: dev
target_project: {target_project}
```
"""
    (plan_dir / "plan.md").write_text(plan_md)
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001",
                "category": "test",
                "phase": 0,
                "description": "synthetic feature for charter tests",
                "steps": ["scripted single step"],
                "acceptance": "synthetic acceptance text for charter tests",
                "passes": False,
                "depends_on": [],
            }
        ],
    }
    (plan_dir / "features.json").write_text(json.dumps(features))
    return plan_dir


def _orchestration_yaml(parent_plan_id: str = "2026-05-02-001-feat-parent") -> str:
    return f"""orchestration:
  parent_plan_id: {parent_plan_id}
  spawn_reason: operator_manual
  depth_limit: 3
"""


def _charter_yaml(**overrides) -> str:
    kw = _valid_charter_kwargs(**overrides)
    paths = "\n".join(f"    - {p!r}" for p in kw["allowed_paths"])
    forbidden = "\n".join(f"    - {f!r}" for f in kw["forbidden_decisions"]) or "    []"
    if kw["forbidden_decisions"]:
        forbidden_yaml = f"  forbidden_decisions:\n{forbidden}"
    else:
        forbidden_yaml = "  forbidden_decisions: []"
    return f"""child_charter:
  kind: {kw["kind"]}
  parent_objective: {kw["parent_objective"]!r}
  parent_acceptance_item: {kw["parent_acceptance_item"]!r}
  allowed_paths:
{paths}
{forbidden_yaml}
  return_condition_summary: {kw["return_condition_summary"]!r}
  may_edit_product_code: {str(kw["may_edit_product_code"]).lower()}
  may_spawn_children: {str(kw["may_spawn_children"]).lower()}
"""


def _commit_policy_yaml(mode: str = "child_commit", requires=None) -> str:
    if requires is None:
        requires = []
    if requires:
        req_lines = "\n".join(f"    - {r}" for r in requires)
        req_yaml = f"  requires:\n{req_lines}"
    else:
        req_yaml = "  requires: []"
    return f"""commit_policy:
  mode: {mode}
{req_yaml}
"""


# ──────────────────────────────  ChildCharter model  ──────────────────────────────


class TestChildCharterModel:
    def test_valid_charter_parses(self):
        charter = ChildCharter(**_valid_charter_kwargs())
        assert charter.kind == "implementation"
        assert charter.may_edit_product_code is True
        assert charter.may_spawn_children is False
        assert "scripts/jarvis_orchestrate/**" in charter.allowed_paths

    def test_kind_governance_design_rejected_with_deferral_message(self):
        with pytest.raises(ValidationError) as exc:
            ChildCharter(**_valid_charter_kwargs(kind="governance_design"))
        msg = str(exc.value)
        assert "governance_design" in msg
        assert "v2" in msg or "deferred" in msg.lower()

    def test_kind_other_value_rejected(self):
        with pytest.raises(ValidationError):
            ChildCharter(**_valid_charter_kwargs(kind="rogue_kind"))

    def test_may_edit_product_code_required_no_default(self):
        # Per D003: explicit only.
        kw = _valid_charter_kwargs()
        kw.pop("may_edit_product_code")
        with pytest.raises(ValidationError) as exc:
            ChildCharter(**kw)
        assert "may_edit_product_code" in str(exc.value)

    def test_may_spawn_children_defaults_false(self):
        kw = _valid_charter_kwargs()
        kw.pop("may_spawn_children")
        charter = ChildCharter(**kw)
        assert charter.may_spawn_children is False

    def test_allowed_paths_must_be_non_empty(self):
        with pytest.raises(ValidationError):
            ChildCharter(**_valid_charter_kwargs(allowed_paths=[]))

    def test_parent_objective_max_length_500(self):
        with pytest.raises(ValidationError):
            ChildCharter(**_valid_charter_kwargs(parent_objective="x" * 501))

    def test_return_condition_summary_must_be_non_empty(self):
        with pytest.raises(ValidationError):
            ChildCharter(**_valid_charter_kwargs(return_condition_summary=""))

    def test_extra_field_rejected(self):
        kw = _valid_charter_kwargs()
        kw["unexpected_field"] = "nope"
        with pytest.raises(ValidationError):
            ChildCharter(**kw)


# ──────────────────────────────  CommitPolicy model  ──────────────────────────────


class TestCommitPolicyModel:
    def test_default_mode_is_evidence_only(self):
        # D003: code-writing authority must be explicit.
        policy = CommitPolicy()
        assert policy.mode == "evidence_only"
        assert policy.requires == []

    def test_valid_modes_parse(self):
        assert CommitPolicy(mode="child_commit").mode == "child_commit"
        assert CommitPolicy(mode="evidence_only").mode == "evidence_only"

    def test_parent_squash_mode_rejected_with_deferral_message(self):
        with pytest.raises(ValidationError) as exc:
            CommitPolicy(mode="parent_squash")
        msg = str(exc.value)
        assert "parent_squash" in msg
        assert "v2" in msg or "deferred" in msg.lower()

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValidationError):
            CommitPolicy(mode="rogue_mode")

    def test_valid_requires_items_parse(self):
        policy = CommitPolicy(
            mode="evidence_only",
            requires=["tests_pass", "evidence_packaged"],
        )
        assert "tests_pass" in policy.requires
        assert "evidence_packaged" in policy.requires

    def test_invalid_requires_item_rejected(self):
        with pytest.raises(ValidationError):
            CommitPolicy(requires=["rogue_requirement"])

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            CommitPolicy.model_validate({"mode": "evidence_only", "extra": "x"})


# ──────────────────────────────  Cross-field invariant  ──────────────────────────────


class TestCharterPolicyCrossFieldInvariant:
    def test_child_commit_with_may_edit_true_passes(self):
        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=True))
        policy = CommitPolicy(mode="child_commit")
        validate_charter_policy_consistency(charter, policy)  # no raise

    def test_evidence_only_with_may_edit_false_passes(self):
        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="evidence_only")
        validate_charter_policy_consistency(charter, policy)  # no raise

    def test_child_commit_with_may_edit_false_rejected(self):
        # D003 cross-field: child_commit requires may_edit_product_code=True.
        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="child_commit")
        with pytest.raises(ValueError) as exc:
            validate_charter_policy_consistency(charter, policy)
        msg = str(exc.value)
        assert "child_commit" in msg
        assert "may_edit_product_code" in msg

    def test_evidence_only_with_may_edit_true_rejected(self):
        # D003 cross-field: evidence_only requires may_edit_product_code=False.
        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=True))
        policy = CommitPolicy(mode="evidence_only")
        with pytest.raises(ValueError) as exc:
            validate_charter_policy_consistency(charter, policy)
        msg = str(exc.value)
        assert "evidence_only" in msg
        assert "may_edit_product_code" in msg


# ──────────────────────────────  parse_return_condition_section (D004)  ──────────────────────────────


def _write_memo(plan_dir: Path, body: str) -> Path:
    evidence = plan_dir / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    memo = evidence / "closeout-memo.md"
    memo.write_text(body)
    return memo


class TestParseReturnConditionSection:
    def test_status_satisfied_parsed(self, tmp_path):
        memo = _write_memo(
            tmp_path,
            "# Memo\n\n## Return Condition\n\nstatus: satisfied\n\nbody...\n",
        )
        assert parse_return_condition_section(memo) == "satisfied"

    def test_status_blocked_parsed(self, tmp_path):
        memo = _write_memo(
            tmp_path,
            "## Return Condition\nstatus: blocked\n",
        )
        assert parse_return_condition_section(memo) == "blocked"

    def test_status_superseded_parsed(self, tmp_path):
        memo = _write_memo(
            tmp_path,
            "## Return Condition\nstatus: superseded\n",
        )
        assert parse_return_condition_section(memo) == "superseded"

    def test_keyword_case_insensitive(self, tmp_path):
        memo = _write_memo(
            tmp_path,
            "## Return Condition\nSTATUS: Satisfied\n",
        )
        assert parse_return_condition_section(memo) == "satisfied"

    def test_value_case_insensitive(self, tmp_path):
        memo = _write_memo(
            tmp_path,
            "## Return Condition\nstatus: BLOCKED\n",
        )
        assert parse_return_condition_section(memo) == "blocked"

    def test_section_inside_subsection_followed_by_other_section(self, tmp_path):
        memo = _write_memo(
            tmp_path,
            "## Other\nirrelevant\n## Return Condition\nstatus: satisfied\n## Notes\nstatus: blocked\n",
        )
        # Status from Notes section must NOT leak into Return Condition.
        assert parse_return_condition_section(memo) == "satisfied"

    def test_missing_memo_raises(self, tmp_path):
        ghost = tmp_path / "evidence" / "closeout-memo.md"
        with pytest.raises(ReturnConditionError) as exc:
            parse_return_condition_section(ghost)
        assert "not found" in str(exc.value).lower() or "missing" in str(exc.value).lower()

    def test_missing_return_condition_section_raises(self, tmp_path):
        memo = _write_memo(tmp_path, "# Memo\n\nNo return condition here.\n")
        with pytest.raises(ReturnConditionError) as exc:
            parse_return_condition_section(memo)
        assert "Return Condition" in str(exc.value)

    def test_missing_status_line_raises(self, tmp_path):
        memo = _write_memo(
            tmp_path,
            "## Return Condition\n\nWe forgot the status line.\n",
        )
        with pytest.raises(ReturnConditionError) as exc:
            parse_return_condition_section(memo)
        assert "status" in str(exc.value).lower()

    def test_illegal_status_value_raises(self, tmp_path):
        memo = _write_memo(
            tmp_path,
            "## Return Condition\nstatus: partial\n",
        )
        with pytest.raises(ReturnConditionError) as exc:
            parse_return_condition_section(memo)
        assert "partial" in str(exc.value)

    def test_multiple_status_lines_raises(self, tmp_path):
        memo = _write_memo(
            tmp_path,
            "## Return Condition\nstatus: satisfied\nstatus: blocked\n",
        )
        with pytest.raises(ReturnConditionError) as exc:
            parse_return_condition_section(memo)
        assert "multiple" in str(exc.value).lower() or "more than" in str(exc.value).lower()

    def test_h3_heading_does_not_count(self, tmp_path):
        # Heading must be `##` (h2) exactly — not `###`.
        memo = _write_memo(
            tmp_path,
            "### Return Condition\nstatus: satisfied\n",
        )
        with pytest.raises(ReturnConditionError):
            parse_return_condition_section(memo)


# ──────────────────────────────  check_child_charter_compliance  ──────────────────────────────


def _signoff_payload(*, signoff: bool = True, audits: list[str] | None = None) -> dict:
    """Minimal signoff_data shape that compliance check reads from."""
    if audits is None:
        audits = ["audit/codex-auditor-F001-i0.json"]
    return {
        "task_id": "2026-05-02-003-feat-nested-orchestration-v1",
        "signoff": signoff,
        "audits": audits,
    }


class TestCheckChildCharterCompliance:
    def test_evidence_only_passes_with_satisfied_status(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        _write_memo(plan_dir, "## Return Condition\nstatus: satisfied\n")

        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="evidence_only")
        compliance = check_child_charter_compliance(
            plan_dir=plan_dir,
            child_charter=charter,
            commit_policy=policy,
            signoff_data=_signoff_payload(),
            modified_files=[],
        )
        assert compliance["return_condition_status"] == "satisfied"
        assert compliance["compliance_checks_satisfied"] == []

    def test_blocked_status_recorded_does_not_raise(self, tmp_path):
        # Per AC#6: signoff-time compliance records the status; F003 is what
        # refuses parent re-entry on non-satisfied. Compliance does NOT raise.
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        _write_memo(plan_dir, "## Return Condition\nstatus: blocked\n")

        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="evidence_only")
        compliance = check_child_charter_compliance(
            plan_dir=plan_dir,
            child_charter=charter,
            commit_policy=policy,
            signoff_data=_signoff_payload(),
            modified_files=[],
        )
        assert compliance["return_condition_status"] == "blocked"

    def test_superseded_status_recorded_does_not_raise(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        _write_memo(plan_dir, "## Return Condition\nstatus: superseded\n")

        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="evidence_only")
        compliance = check_child_charter_compliance(
            plan_dir=plan_dir,
            child_charter=charter,
            commit_policy=policy,
            signoff_data=_signoff_payload(),
            modified_files=[],
        )
        assert compliance["return_condition_status"] == "superseded"

    def test_missing_return_condition_section_raises(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        _write_memo(plan_dir, "# Memo\nno return condition section\n")

        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="evidence_only")
        with pytest.raises(ChildCharterViolation):
            check_child_charter_compliance(
                plan_dir=plan_dir,
                child_charter=charter,
                commit_policy=policy,
                signoff_data=_signoff_payload(),
                modified_files=[],
            )

    def test_child_commit_allowed_paths_pass(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        _write_memo(plan_dir, "## Return Condition\nstatus: satisfied\n")

        charter = ChildCharter(
            **_valid_charter_kwargs(
                may_edit_product_code=True,
                allowed_paths=["scripts/jarvis_orchestrate/*", "docs/plans/*"],
            )
        )
        policy = CommitPolicy(mode="child_commit")
        compliance = check_child_charter_compliance(
            plan_dir=plan_dir,
            child_charter=charter,
            commit_policy=policy,
            signoff_data=_signoff_payload(),
            modified_files=[
                "scripts/jarvis_orchestrate/foo.py",
                "docs/plans/some-plan",
            ],
        )
        assert compliance["return_condition_status"] == "satisfied"

    def test_child_commit_path_outside_allowed_paths_raises(self, tmp_path):
        # AC#5: file outside allowed_paths is HARD blocker; message names path.
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        _write_memo(plan_dir, "## Return Condition\nstatus: satisfied\n")

        charter = ChildCharter(
            **_valid_charter_kwargs(
                may_edit_product_code=True,
                allowed_paths=["scripts/jarvis_orchestrate/*"],
            )
        )
        policy = CommitPolicy(mode="child_commit")
        with pytest.raises(ChildCharterViolation) as exc:
            check_child_charter_compliance(
                plan_dir=plan_dir,
                child_charter=charter,
                commit_policy=policy,
                signoff_data=_signoff_payload(),
                modified_files=[
                    "scripts/jarvis_orchestrate/foo.py",
                    "claude/PORTABILITY.md",  # outside
                    "dashboard/state/costs.json",  # outside
                ],
            )
        msg = str(exc.value)
        assert "claude/PORTABILITY.md" in msg or "dashboard/state/costs.json" in msg

    def test_evidence_only_skips_path_check(self, tmp_path):
        # AC#5: mode='evidence_only' does NOT invoke git diff / path enforcement.
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        _write_memo(plan_dir, "## Return Condition\nstatus: satisfied\n")

        charter = ChildCharter(
            **_valid_charter_kwargs(
                may_edit_product_code=False,
                allowed_paths=["scripts/jarvis_orchestrate/*"],  # narrow
            )
        )
        policy = CommitPolicy(mode="evidence_only")
        # Even if "modified_files" includes things outside allowed_paths,
        # evidence_only mode must not enforce the path check.
        compliance = check_child_charter_compliance(
            plan_dir=plan_dir,
            child_charter=charter,
            commit_policy=policy,
            signoff_data=_signoff_payload(),
            modified_files=["random/whatever.txt", "outside.md"],
        )
        assert compliance["return_condition_status"] == "satisfied"

    def test_requires_tests_pass_satisfied(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        _write_memo(plan_dir, "## Return Condition\nstatus: satisfied\n")

        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="evidence_only", requires=["tests_pass"])
        compliance = check_child_charter_compliance(
            plan_dir=plan_dir,
            child_charter=charter,
            commit_policy=policy,
            signoff_data=_signoff_payload(signoff=True),
            modified_files=[],
        )
        assert "tests_pass" in compliance["compliance_checks_satisfied"]

    def test_requires_tests_pass_unsatisfied_raises(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        _write_memo(plan_dir, "## Return Condition\nstatus: satisfied\n")

        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="evidence_only", requires=["tests_pass"])
        with pytest.raises(ChildCharterViolation) as exc:
            check_child_charter_compliance(
                plan_dir=plan_dir,
                child_charter=charter,
                commit_policy=policy,
                signoff_data=_signoff_payload(signoff=False),
                modified_files=[],
            )
        assert "tests_pass" in str(exc.value)

    def test_requires_patch_completeness_unsatisfied_raises(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        _write_memo(plan_dir, "## Return Condition\nstatus: satisfied\n")

        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="evidence_only", requires=["patch_completeness"])
        with pytest.raises(ChildCharterViolation) as exc:
            check_child_charter_compliance(
                plan_dir=plan_dir,
                child_charter=charter,
                commit_policy=policy,
                signoff_data=_signoff_payload(audits=[]),
                modified_files=[],
            )
        assert "patch_completeness" in str(exc.value)

    def test_requires_evidence_packaged_unsatisfied_raises(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        # No evidence/ dir written at all.
        memo_dir = plan_dir / "evidence"
        memo_dir.mkdir()
        (memo_dir / "closeout-memo.md").write_text("## Return Condition\nstatus: satisfied\n")
        # Now remove other evidence — only memo present, but evidence_packaged
        # passes because evidence/ has at least one file.

        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="evidence_only", requires=["evidence_packaged"])
        compliance = check_child_charter_compliance(
            plan_dir=plan_dir,
            child_charter=charter,
            commit_policy=policy,
            signoff_data=_signoff_payload(),
            modified_files=[],
        )
        assert "evidence_packaged" in compliance["compliance_checks_satisfied"]


# ──────────────────────────────  plan_loader integration  ──────────────────────────────


class TestPlanLoaderIntegration:
    def test_top_level_plan_unchanged_no_charter_no_policy(self, tmp_path):
        plan_id = "2026-05-02-099-feat-toplevel"
        plan_dir = _make_plan_dir(tmp_path, plan_id)
        loaded = plan_loader.load(plan_dir)
        assert loaded.orchestration is None
        assert loaded.child_charter is None
        assert loaded.commit_policy is None

    def test_child_plan_with_charter_and_policy_loads(self, tmp_path):
        plan_id = "2026-05-02-099-feat-childplan"
        plan_dir = _make_plan_dir(
            tmp_path,
            plan_id,
            orchestration_block=_orchestration_yaml(),
            charter_block=_charter_yaml(may_edit_product_code=True),
            commit_policy_block=_commit_policy_yaml(mode="child_commit", requires=["tests_pass"]),
        )
        loaded = plan_loader.load(plan_dir)
        assert loaded.orchestration is not None
        assert loaded.child_charter is not None
        assert loaded.child_charter.kind == "implementation"
        assert loaded.commit_policy is not None
        assert loaded.commit_policy.mode == "child_commit"
        assert loaded.commit_policy.requires == ["tests_pass"]

    def test_child_plan_default_commit_policy_when_absent(self, tmp_path):
        # AC#11: charter present, commit_policy absent → synthesize
        # CommitPolicy(mode='evidence_only', requires=[]).
        plan_id = "2026-05-02-099-feat-childdefault"
        plan_dir = _make_plan_dir(
            tmp_path,
            plan_id,
            orchestration_block=_orchestration_yaml(),
            charter_block=_charter_yaml(may_edit_product_code=False),
        )
        loaded = plan_loader.load(plan_dir)
        assert loaded.child_charter is not None
        assert loaded.commit_policy is not None
        assert loaded.commit_policy.mode == "evidence_only"
        assert loaded.commit_policy.requires == []

    def test_charter_without_parent_plan_id_rejected(self, tmp_path):
        # AC#9: top-level plan with child_charter → raise at load time.
        plan_id = "2026-05-02-099-feat-orphancharter"
        plan_dir = _make_plan_dir(
            tmp_path,
            plan_id,
            charter_block=_charter_yaml(may_edit_product_code=False),
        )
        with pytest.raises((ValueError, ValidationError)) as exc:
            plan_loader.load(plan_dir)
        assert "child_charter" in str(exc.value) or "parent_plan_id" in str(exc.value)

    def test_charter_policy_consistency_enforced_at_load(self, tmp_path):
        # mode='child_commit' + may_edit_product_code=False → reject.
        plan_id = "2026-05-02-099-feat-mismatch"
        plan_dir = _make_plan_dir(
            tmp_path,
            plan_id,
            orchestration_block=_orchestration_yaml(),
            charter_block=_charter_yaml(may_edit_product_code=False),
            commit_policy_block=_commit_policy_yaml(mode="child_commit"),
        )
        with pytest.raises((ValueError, ValidationError)) as exc:
            plan_loader.load(plan_dir)
        assert "child_commit" in str(exc.value) or "may_edit_product_code" in str(exc.value)


# ──────────────────────────────  signoff_writer integration  ──────────────────────────────


class TestSignoffWriterIntegration:
    """AC#4 — write_signoff runs charter compliance BEFORE persisting; raise
    blocks the envelope (no-partial-artifact) and writes the side-car file
    on success."""

    def _stage_audit(self, plan_dir: Path, plan_id: str) -> Path:
        """Create a minimal audit envelope so build_signoff_dict has data."""
        audit = {
            "task_id": plan_id,
            "audit_id": f"{plan_id}#claude#0",
            "agent": "claude",
            "agent_role": "implementer",
            "iteration": 0,
            "decided_at": "2026-05-02T20:00:00Z",
            "audit_status": "signed_off",
            "feature_id": "F001",
            "summary": "synthetic stub",
            "validation_performed": ["stub"],
            "blocking_findings": [],
            "non_blocking_findings": [],
            "patch_completeness": "complete",
            "next_action": "merge",
        }
        audit_dir = plan_dir / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        path = audit_dir / "claude-implementer-F001-i0.json"
        path.write_text(json.dumps(audit))
        return path

    def test_compliance_passes_writes_signoff_and_sidecar(self, tmp_path):
        plan_id = "2026-05-02-099-feat-okflow"
        plan_dir = tmp_path / plan_id
        plan_dir.mkdir()
        _write_memo(plan_dir, "## Return Condition\nstatus: satisfied\n")
        audit_path = self._stage_audit(plan_dir, plan_id)

        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="evidence_only", requires=["tests_pass"])
        out = signoff_writer.write_signoff(
            plan_id=plan_id,
            tier="trivial",
            iteration=0,
            agents_in_panel=["claude"],
            audit_paths=[audit_path],
            plan_dir=plan_dir,
            volley_status="signed_off",
            child_charter=charter,
            commit_policy=policy,
            modified_files=[],
        )
        assert out.is_file()
        side_car = plan_dir / "audit" / f"charter-compliance-{plan_id}.json"
        assert side_car.is_file()
        compliance = json.loads(side_car.read_text())
        assert compliance["return_condition_status"] == "satisfied"
        assert "tests_pass" in compliance["compliance_checks_satisfied"]

    def test_compliance_violation_blocks_signoff_write(self, tmp_path):
        # AC#4: signoff envelope NOT written on raise.
        plan_id = "2026-05-02-099-feat-violation"
        plan_dir = tmp_path / plan_id
        plan_dir.mkdir()
        # No `## Return Condition` section → ChildCharterViolation.
        _write_memo(plan_dir, "# Just a memo, no section\n")
        audit_path = self._stage_audit(plan_dir, plan_id)

        charter = ChildCharter(**_valid_charter_kwargs(may_edit_product_code=False))
        policy = CommitPolicy(mode="evidence_only")
        with pytest.raises(ChildCharterViolation):
            signoff_writer.write_signoff(
                plan_id=plan_id,
                tier="trivial",
                iteration=0,
                agents_in_panel=["claude"],
                audit_paths=[audit_path],
                plan_dir=plan_dir,
                volley_status="signed_off",
                child_charter=charter,
                commit_policy=policy,
                modified_files=[],
            )
        # Neither signoff nor side-car landed.
        assert not (plan_dir / "audit" / f"signoff-{plan_id}.json").is_file()
        assert not (plan_dir / "audit" / f"charter-compliance-{plan_id}.json").is_file()

    def test_no_charter_means_no_compliance_no_sidecar(self, tmp_path):
        # AC#12: existing top-level plans (no charter) signoff unchanged —
        # no compliance check, no side-car.
        plan_id = "2026-05-02-099-feat-toplevel"
        plan_dir = tmp_path / plan_id
        plan_dir.mkdir()
        audit_path = self._stage_audit(plan_dir, plan_id)

        signoff_writer.write_signoff(
            plan_id=plan_id,
            tier="trivial",
            iteration=0,
            agents_in_panel=["claude"],
            audit_paths=[audit_path],
            plan_dir=plan_dir,
            volley_status="signed_off",
        )
        assert (plan_dir / "audit" / f"signoff-{plan_id}.json").is_file()
        assert not (plan_dir / "audit" / f"charter-compliance-{plan_id}.json").is_file()
