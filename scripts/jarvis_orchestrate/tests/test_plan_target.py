"""F023 Step 2 (EC2 + EC7) — plan-level Target contract + prod gate.

Run: PYTHONPATH=scripts python3 -m jarvis_orchestrate.tests.test_plan_target
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import plan_loader, supervisor  # noqa: E402
from jarvis_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from jarvis_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)
from jarvis_orchestrate.plan_target import (  # noqa: E402
    PlanTargetError,
    TARGET_PROJECT_NONE_SENTINEL,
    parse_target_section,
    validate_prod_gates,
)


# ──────────────────────────────  fixtures  ──────────────────────────────


TARGET_BLOCK_DEV = """## Target

```yaml
target_env: dev
target_project: <firebase-project-id>
```
"""

TARGET_BLOCK_PROD = """## Target

```yaml
target_env: prod
target_project: <firebase-project-id>
```
"""

TARGET_BLOCK_NONE = """## Target

```yaml
target_env: dev
target_project: none
```
"""


def _plan_md(
    plan_id: str,
    *,
    target_block: str | None = TARGET_BLOCK_DEV,
    human_gates: list[str] | None = None,
    extra_body: str = "",
) -> str:
    gates = human_gates if human_gates is not None else ["pre_impl"]
    gates_yaml = "\n".join(f"  - {g}" for g in gates)
    target_section = target_block or ""
    return f"""---
id: {plan_id}
title: F023 step 2 synthetic
type: infra
tier: trivial
status: active
date: "2026-04-26"
description: Synthetic plan for F023 EC2/EC7 tests.
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

# F023 step 2 synthetic

{target_section}
{extra_body}
"""


def _features_json(plan_id: str) -> dict:
    return {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001",
                "category": "test",
                "phase": 0,
                "description": "Synthetic feature for F023 step 2 tests.",
                "steps": ["scripted"],
                "acceptance": "Plan loads with parsed target.",
                "passes": False,
                "depends_on": [],
            }
        ],
    }


def _write_plan(
    tmp: Path,
    plan_id: str,
    *,
    target_block: str | None = TARGET_BLOCK_DEV,
    human_gates: list[str] | None = None,
) -> Path:
    plan_dir = tmp / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        _plan_md(plan_id, target_block=target_block, human_gates=human_gates)
    )
    (plan_dir / "features.json").write_text(
        json.dumps(_features_json(plan_id), indent=2, ensure_ascii=False) + "\n"
    )
    return plan_dir


# ──────────────────────────────  parser  ──────────────────────────────


def test_parse_target_section_happy_path() -> None:
    print("\n[test] parse_target_section_happy_path ...")
    plan_md = _plan_md("p", target_block=TARGET_BLOCK_DEV)
    target = parse_target_section(plan_md)
    assert target["target_env"] == "dev", target
    assert target["target_project"] == "<firebase-project-id>", target
    print("  ✓ extracts target_env + target_project from fenced YAML under ## Target")


def test_parse_target_section_missing_heading_raises() -> None:
    print("\n[test] parse_target_section_missing_heading_raises ...")
    plan_md = _plan_md("p", target_block=None)
    try:
        parse_target_section(plan_md)
    except PlanTargetError as exc:
        assert "Target" in str(exc), exc
        print("  ✓ raises PlanTargetError naming the missing section")
        return
    raise AssertionError("expected PlanTargetError for missing ## Target heading")


def test_parse_target_section_missing_yaml_block_raises() -> None:
    print("\n[test] parse_target_section_missing_yaml_block_raises ...")
    plan_md = _plan_md(
        "p",
        target_block="## Target\n\nNo YAML block here, just prose.\n",
    )
    try:
        parse_target_section(plan_md)
    except PlanTargetError as exc:
        assert "yaml" in str(exc).lower(), exc
        print("  ✓ raises when ## Target is present but lacks a fenced yaml block")
        return
    raise AssertionError("expected PlanTargetError for missing yaml block")


def test_parse_target_section_invalid_env_raises() -> None:
    print("\n[test] parse_target_section_invalid_env_raises ...")
    bad = "## Target\n\n```yaml\ntarget_env: production\ntarget_project: x\n```\n"
    plan_md = _plan_md("p", target_block=bad)
    try:
        parse_target_section(plan_md)
    except PlanTargetError as exc:
        assert "target_env" in str(exc), exc
        print("  ✓ rejects target_env not in {dev, staging, prod}")
        return
    raise AssertionError("expected PlanTargetError for invalid target_env")


def test_parse_target_section_missing_project_raises() -> None:
    print("\n[test] parse_target_section_missing_project_raises ...")
    bad = "## Target\n\n```yaml\ntarget_env: dev\n```\n"
    plan_md = _plan_md("p", target_block=bad)
    try:
        parse_target_section(plan_md)
    except PlanTargetError as exc:
        assert "target_project" in str(exc), exc
        print("  ✓ rejects missing target_project")
        return
    raise AssertionError("expected PlanTargetError for missing target_project")


def test_parse_target_section_none_sentinel_allowed() -> None:
    print("\n[test] parse_target_section_none_sentinel_allowed ...")
    target = parse_target_section(_plan_md("p", target_block=TARGET_BLOCK_NONE))
    assert target["target_project"] == TARGET_PROJECT_NONE_SENTINEL, target
    print("  ✓ target_project=none accepted as host-local sentinel")


# ──────────────────────────────  prod gate (EC7)  ──────────────────────────────


def test_validate_prod_gates_dev_skips_check() -> None:
    print("\n[test] validate_prod_gates_dev_skips_check ...")
    validate_prod_gates(target_env="dev", human_gates=[])  # must not raise
    print("  ✓ non-prod plans are not required to declare prod-only gates")


def test_validate_prod_gates_prod_with_both_gates_ok() -> None:
    print("\n[test] validate_prod_gates_prod_with_both_gates_ok ...")
    validate_prod_gates(
        target_env="prod",
        human_gates=["pre_impl", "pre_merge", "on_escalation"],
    )
    print("  ✓ prod plan with pre_impl + on_escalation passes")


def test_validate_prod_gates_prod_missing_pre_impl_raises() -> None:
    print("\n[test] validate_prod_gates_prod_missing_pre_impl_raises ...")
    try:
        validate_prod_gates(target_env="prod", human_gates=["on_escalation"])
    except PlanTargetError as exc:
        assert "pre_impl" in str(exc), exc
        print("  ✓ prod plan missing pre_impl rejected")
        return
    raise AssertionError("expected PlanTargetError for prod missing pre_impl")


def test_validate_prod_gates_prod_missing_on_escalation_raises() -> None:
    print("\n[test] validate_prod_gates_prod_missing_on_escalation_raises ...")
    try:
        validate_prod_gates(target_env="prod", human_gates=["pre_impl"])
    except PlanTargetError as exc:
        assert "on_escalation" in str(exc), exc
        print("  ✓ prod plan missing on_escalation rejected")
        return
    raise AssertionError("expected PlanTargetError for prod missing on_escalation")


# ──────────────────────────────  loader integration  ──────────────────────────────


def test_loader_exposes_target_fields() -> None:
    print("\n[test] loader_exposes_target_fields ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _write_plan(Path(td), "2026-04-26-001-infra-target-loader-test")
        loaded = plan_loader.load(plan_dir)
        assert loaded.target_env == "dev", loaded.target_env
        assert loaded.target_project == "<firebase-project-id>", loaded.target_project
    print("  ✓ LoadedPlan.target_env / target_project populated from plan.md")


def test_loader_rejects_plan_missing_target_section() -> None:
    print("\n[test] loader_rejects_plan_missing_target_section ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _write_plan(
            Path(td), "2026-04-26-002-infra-target-missing", target_block=None
        )
        try:
            plan_loader.load(plan_dir)
        except PlanTargetError as exc:
            assert "Target" in str(exc), exc
            print("  ✓ plan_loader.load() rejects plans without ## Target")
            return
    raise AssertionError("expected PlanTargetError")


def test_loader_rejects_prod_plan_missing_gates() -> None:
    print("\n[test] loader_rejects_prod_plan_missing_gates ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _write_plan(
            Path(td),
            "2026-04-26-003-infra-prod-missing-gates",
            target_block=TARGET_BLOCK_PROD,
            human_gates=["pre_merge"],  # missing both pre_impl + on_escalation
        )
        try:
            plan_loader.load(plan_dir)
        except PlanTargetError as exc:
            msg = str(exc)
            assert "pre_impl" in msg or "on_escalation" in msg, msg
            print("  ✓ plan_loader.load() enforces EC7 prod gate")
            return
    raise AssertionError("expected PlanTargetError")


def test_loader_target_project_none_returns_python_none() -> None:
    print("\n[test] loader_target_project_none_returns_python_none ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _write_plan(
            Path(td),
            "2026-04-26-004-infra-target-none-sentinel",
            target_block=TARGET_BLOCK_NONE,
        )
        loaded = plan_loader.load(plan_dir)
        assert loaded.target_env == "dev"
        assert loaded.target_project is None, (
            f"sentinel 'none' should normalize to Python None, got {loaded.target_project!r}"
        )
    print("  ✓ target_project=none normalizes to Python None on LoadedPlan")


# ──────────────────────────────  supervisor wiring  ──────────────────────────────


class _EnvCapturingExecutor(BaseExecutor):
    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.captured_envs: list[dict[str, str]] = []

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.captured_envs.append(dict(task.subprocess_env or {}))
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at="2026-04-26T00:00:00Z",
            completed_at="2026-04-26T00:00:00Z",
            success=True,
            summary=f"[capture {self.agent_name}/{task.agent_role}]",
            raw_response="ok",
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _force_signoff_volley(plan_dir: Path, **kwargs):
    impl = _EnvCapturingExecutor("claude")
    aud = _EnvCapturingExecutor("codex")
    saved_registry = dict(AGENT_REGISTRY)
    saved_quota_gate = supervisor._quota_gate
    AGENT_REGISTRY["claude"] = lambda: impl
    AGENT_REGISTRY["codex"] = lambda: aud
    supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")

    orig_run_round = supervisor._run_round

    def force_signoff(*args, **inner_kwargs):
        path = orig_run_round(*args, **inner_kwargs)
        if inner_kwargs.get("role") == "auditor":
            data = json.loads(path.read_text())
            data["audit_status"] = "signed_off"
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return path

    supervisor._run_round = force_signoff
    try:
        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1, **kwargs)
    finally:
        supervisor._run_round = orig_run_round
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        supervisor._quota_gate = saved_quota_gate
    return result, impl, aud


def test_supervisor_reads_target_from_plan_when_kwargs_unset() -> None:
    print("\n[test] supervisor_reads_target_from_plan_when_kwargs_unset ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _write_plan(Path(td), "2026-04-26-005-infra-target-supervisor")
        result, impl, aud = _force_signoff_volley(plan_dir)
        assert result.final_status == "signed_off"
        for env in (*impl.captured_envs, *aud.captured_envs):
            assert env.get("JARVIS_TARGET_ENV") == "dev", env.get("JARVIS_TARGET_ENV")
            assert env.get("JARVIS_TARGET_PROJECT") == "<firebase-project-id>", env.get("JARVIS_TARGET_PROJECT")
            assert env.get("CLOUDSDK_CORE_PROJECT") == "<firebase-project-id>"
    print("  ✓ supervisor pulls target_env/target_project from plan when kwargs absent")


def test_supervisor_kwargs_override_plan_target() -> None:
    print("\n[test] supervisor_kwargs_override_plan_target ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _write_plan(Path(td), "2026-04-26-006-infra-target-override")
        result, impl, aud = _force_signoff_volley(
            plan_dir,
            target_env="staging",
            target_project="jarvis-staging-override",
        )
        assert result.final_status == "signed_off"
        for env in (*impl.captured_envs, *aud.captured_envs):
            assert env.get("JARVIS_TARGET_ENV") == "staging"
            assert env.get("JARVIS_TARGET_PROJECT") == "jarvis-staging-override"
    print("  ✓ explicit kwargs override plan-derived target (audit-trail escape hatch)")


def test_supervisor_target_project_none_injects_no_project_labels() -> None:
    print("\n[test] supervisor_target_project_none_injects_no_project_labels ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _write_plan(
            Path(td),
            "2026-04-26-007-infra-target-none",
            target_block=TARGET_BLOCK_NONE,
        )
        result, impl, aud = _force_signoff_volley(plan_dir)
        assert result.final_status == "signed_off"
        for env in (*impl.captured_envs, *aud.captured_envs):
            assert env.get("JARVIS_TARGET_ENV") == "dev"
            assert "JARVIS_TARGET_PROJECT" not in env, (
                f"sentinel target_project=none should suppress project labels: {env.get('JARVIS_TARGET_PROJECT')}"
            )
            assert "CLOUDSDK_CORE_PROJECT" not in env
    print("  ✓ target_project=none means: env_env labels still set, no project labels injected")


# ──────────────────────────────  driver  ──────────────────────────────


def main() -> int:
    test_parse_target_section_happy_path()
    test_parse_target_section_missing_heading_raises()
    test_parse_target_section_missing_yaml_block_raises()
    test_parse_target_section_invalid_env_raises()
    test_parse_target_section_missing_project_raises()
    test_parse_target_section_none_sentinel_allowed()
    test_validate_prod_gates_dev_skips_check()
    test_validate_prod_gates_prod_with_both_gates_ok()
    test_validate_prod_gates_prod_missing_pre_impl_raises()
    test_validate_prod_gates_prod_missing_on_escalation_raises()
    test_loader_exposes_target_fields()
    test_loader_rejects_plan_missing_target_section()
    test_loader_rejects_prod_plan_missing_gates()
    test_loader_target_project_none_returns_python_none()
    test_supervisor_reads_target_from_plan_when_kwargs_unset()
    test_supervisor_kwargs_override_plan_target()
    test_supervisor_target_project_none_injects_no_project_labels()
    print("\n✓ F023 Step 2 EC2 + EC7 tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
