"""F023 Expansion B — requires_gates[] enforcement bridge to EC7.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_expansion_b_requires_gates.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate.plan_target import PlanTargetError, validate_prod_gates  # noqa: E402


# ──────────────────────────────  validate_prod_gates with override  ──────────────────────────────


def test_no_override_keeps_hardcoded_prod_gate() -> None:
    print("\n[test] no_override_keeps_hardcoded_prod_gate ...")
    # No required_override; non-prod tier → no enforcement
    validate_prod_gates("dev", [])
    validate_prod_gates("staging", ["any_gate"])
    # Prod still requires both
    try:
        validate_prod_gates("prod", ["pre_impl"])
    except PlanTargetError as exc:
        assert "on_escalation" in str(exc)
        print("  ✓ unchanged hardcoded prod-gate semantics when override absent")
        return
    raise AssertionError("expected PlanTargetError for prod missing on_escalation")


def test_override_supersedes_for_prod() -> None:
    print("\n[test] override_supersedes_for_prod ...")
    # registry says prod only needs ['custom_gate']; user-provided gates omit pre_impl
    validate_prod_gates("prod", ["custom_gate"], required_override=["custom_gate"])
    # registry override missing
    try:
        validate_prod_gates("prod", ["custom_gate"], required_override=["custom_gate", "missing_gate"])
    except PlanTargetError as exc:
        assert "missing_gate" in str(exc) and "environments.json" in str(exc)
        print("  ✓ registry override replaces hardcoded set for prod and is enforced")
        return
    raise AssertionError("expected PlanTargetError for missing override gate")


def test_override_applies_to_non_prod_tier() -> None:
    print("\n[test] override_applies_to_non_prod_tier ...")
    # staging tier with explicit requires_gates
    validate_prod_gates("staging", ["pre_impl", "security_review"],
                        required_override=["pre_impl", "security_review"])
    try:
        validate_prod_gates("staging", ["pre_impl"], required_override=["pre_impl", "security_review"])
    except PlanTargetError as exc:
        assert "security_review" in str(exc) and "staging" in str(exc)
        print("  ✓ non-prod tier with override gates still enforced")
        return
    raise AssertionError("expected PlanTargetError for staging missing required gate")


def test_empty_override_means_no_gates() -> None:
    print("\n[test] empty_override_means_no_gates ...")
    # registry declares requires_gates: []  → loader passes [] override → no enforcement
    validate_prod_gates("prod", [], required_override=[])
    print("  ✓ explicit empty override silences gate enforcement (registry says 'no gates')")


# ──────────────────────────────  plan_loader integration  ──────────────────────────────


def _write_plan(tmp: Path, plan_id: str, target_env: str, target_project: str, human_gates: list[str]) -> Path:
    plan_dir = tmp / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    gates_yaml = "\n".join(f"  - {g}" for g in human_gates)
    plan_md = f"""---
id: {plan_id}
title: ExpB synthetic
type: infra
tier: trivial
status: active
date: "2026-04-26"
description: Synthetic plan for Expansion B tests.
agents_required:
  - claude
  - codex
human_gates:
{gates_yaml}
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# ExpB synthetic

## Target

```yaml
target_env: {target_env}
target_project: {target_project}
```
"""
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001",
                "category": "test",
                "phase": 0,
                "description": "Synthetic feature for ExpB tests.",
                "steps": ["scripted"],
                "acceptance": "Plan loads with declared gates set.",
                "passes": False,
                "depends_on": [],
            }
        ],
    }
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(json.dumps(features, indent=2) + "\n")
    return plan_dir


def _write_environments(repo: Path, payload: dict) -> None:
    (repo / "environments.json").write_text(json.dumps(payload, indent=2) + "\n")


def test_loader_consults_registry_requires_gates() -> None:
    print("\n[test] loader_consults_registry_requires_gates ...")
    from jarvis_orchestrate import plan_loader
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _write_environments(repo, {
            "repo": "Test",
            "staging": {
                "firebase_project": "test-staging",
                "requires_gates": ["pre_impl", "security_review"],
            },
        })
        # plan declares pre_impl only — loader should reject because registry
        # demands security_review for staging
        plan_dir = _write_plan(repo, "2026-04-26-300-infra-exp-b-loader", "staging", "test-staging", ["pre_impl"])
        try:
            plan_loader.load(plan_dir)
        except PlanTargetError as exc:
            assert "security_review" in str(exc)
            assert "environments.json" in str(exc)
            print("  ✓ plan_loader.load propagates registry requires_gates as override")
            return
    raise AssertionError("expected PlanTargetError from plan_loader.load")


def test_loader_falls_back_to_hardcoded_when_no_registry() -> None:
    print("\n[test] loader_falls_back_to_hardcoded_when_no_registry ...")
    from jarvis_orchestrate import plan_loader
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        # No environments.json — prod still requires pre_impl + on_escalation
        plan_dir = _write_plan(repo, "2026-04-26-301-infra-exp-b-no-reg",
                                "prod", "no-reg-proj", ["pre_impl"])
        try:
            plan_loader.load(plan_dir)
        except PlanTargetError as exc:
            assert "on_escalation" in str(exc)
            print("  ✓ no environments.json → hardcoded prod gate still enforced")
            return
    raise AssertionError("expected PlanTargetError from hardcoded prod gate")


def test_loader_registry_no_requires_gates_falls_back() -> None:
    print("\n[test] loader_registry_no_requires_gates_falls_back ...")
    from jarvis_orchestrate import plan_loader
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _write_environments(repo, {
            "repo": "Test",
            "prod": {"firebase_project": "test-prod"},  # no requires_gates declared
        })
        plan_dir = _write_plan(repo, "2026-04-26-302-infra-exp-b-no-reqgates",
                                "prod", "test-prod", ["pre_impl"])
        try:
            plan_loader.load(plan_dir)
        except PlanTargetError as exc:
            assert "on_escalation" in str(exc)
            print("  ✓ registry without requires_gates → hardcoded prod gate enforced")
            return
    raise AssertionError("expected PlanTargetError from hardcoded prod gate")
