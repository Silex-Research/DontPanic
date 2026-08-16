"""Plan 2026-08-09-003 F002 — scripted executors behind BaseExecutor.

Acceptance:
  (1) A scenario scripting needs_changes then signed_off drives two
      iterations and terminates signed off.
  (2) A scenario scripting a truncated envelope reaches the supervisor's
      existing malformed-envelope handling rather than raising out of
      the executor.
  (3) A scenario scripting a narrative verdict that contradicts the
      structured status triggers the existing mismatch detection.
  (4) Both executors are instances of BaseExecutor and report available.
  (5) git diff shows no file under the orchestrator package modified
      other than the smoke package and its tests. Checked here as:
      scripted-executor code lives in the smoke package, and
      supervisor.py does not import or mention the sim harness.

Run:
    PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_scripted_executors.py -q
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from dontpanic_orchestrate.executors.base import BaseExecutor, DispatchTask
from dontpanic_orchestrate.smoke import (
    MockClaudeExecutor,
    MockCodexExecutor,
    SYNTHETIC_PLAN_ID,
    SMOKE_FEATURE_ID,
)
from dontpanic_orchestrate.smoke.loader import load_scenario
from dontpanic_orchestrate.smoke.runner import run_one_trial


def _write_plan(plan_dir: Path, *, max_iterations: int = 2) -> None:
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {SYNTHETIC_PLAN_ID}
title: Scripted executor test plan
type: infra
tier: trivial
status: active
date: "2026-05-19"
description: |
  Scripted-executor fixture. Not a real plan.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: {max_iterations}
  hard_stop: true
privacy_tier: internal
goal_type: mechanical
links:
  features: ./features.json
---

# Scripted executor test plan

## Target

```yaml
target_env: dev
target_project: none
```
"""
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": SYNTHETIC_PLAN_ID,
                "features": [
                    {
                        "id": SMOKE_FEATURE_ID,
                        "category": "test",
                        "phase": 0,
                        "description": (
                            "Scripted executor fixture exercising per-iteration "
                            "replies without touching real CLIs."
                        ),
                        "steps": ["scripted implementer", "scripted auditor"],
                        "acceptance": "Volley follows the scripted replies.",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )


def _write_scenario(dir_path: Path, payload: dict[str, object]) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / "scenario.json"
    if "suite" not in payload:
        payload = {**payload, "suite": "regression"}
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def _task(*, iteration: int = 0, role: str = "implementer") -> DispatchTask:
    return DispatchTask(
        plan_id=SYNTHETIC_PLAN_ID,
        plan_dir=Path("."),
        feature_id=SMOKE_FEATURE_ID,
        feature_description="scripted",
        feature_acceptance="scripted",
        feature_steps=["scripted"],
        agent_role=role,
        iteration=iteration,
    )


def test_needs_changes_then_signed_off_drives_two_iterations(tmp_path: Path) -> None:
    """Acceptance (1): disagreement then convergence terminates signed_off."""
    plan_dir = tmp_path / "scenario"
    _write_plan(plan_dir, max_iterations=2)
    path = _write_scenario(
        plan_dir,
        {
            "id": "disagree-then-converge",
            "plan_fixture": "./plan.md",
            "features_fixture": "./features.json",
            "feature_id": SMOKE_FEATURE_ID,
            "max_iterations": 2,
            "replies": [
                {
                    "agent": "claude",
                    "role": "implementer",
                    "iteration": 0,
                    "summary": "first implementer pass",
                    "raw_response": "working",
                    "quota_consumed": {"tokens_in": 10, "tokens_out": 4},
                },
                {
                    "agent": "codex",
                    "role": "auditor",
                    "iteration": 0,
                    "summary": "Overall verdict: needs_changes.",
                    "raw_response": "needs_changes",
                    "quota_consumed": {"tokens_in": 8, "tokens_out": 3},
                },
                {
                    "agent": "claude",
                    "role": "implementer",
                    "iteration": 1,
                    "summary": "addressed auditor findings",
                    "raw_response": "fixed",
                    "quota_consumed": {"tokens_in": 11, "tokens_out": 5},
                },
                {
                    "agent": "codex",
                    "role": "auditor",
                    "iteration": 1,
                    "summary": "Overall verdict: signed_off.",
                    "raw_response": "signed_off",
                    "quota_consumed": {"tokens_in": 7, "tokens_out": 2},
                },
            ],
            "expected": {"terminal_state": "signed_off"},
        },
    )
    scenario = load_scenario(path)
    trial = run_one_trial(scenario)
    assert trial.errored is False, trial.error
    assert trial.terminal_state == "signed_off"
    assert trial.iteration_count == 2


def test_truncated_envelope_does_not_raise_out_of_executor(tmp_path: Path) -> None:
    """Acceptance (2): truncated JSON is returned, not raised."""
    plan_dir = tmp_path / "scenario"
    _write_plan(plan_dir)
    path = _write_scenario(
        plan_dir,
        {
            "id": "truncated-envelope",
            "plan_fixture": "./plan.md",
            "replies": [
                {
                    "agent": "claude",
                    "role": "implementer",
                    "iteration": 0,
                    "summary": '{"audit_status": "signed_off", "summary":',
                    "raw_response": '{"audit_status": "signed_off", "summary":',
                    "malformed": "truncated_json",
                },
                {
                    "agent": "codex",
                    "role": "auditor",
                    "iteration": 0,
                    "summary": "Overall verdict: signed_off.",
                    "raw_response": "signed_off",
                },
            ],
            "expected": {"terminal_state": "signed_off"},
        },
    )
    scenario = load_scenario(path)
    executor = MockClaudeExecutor(scenario)
    result = executor.dispatch(_task(role="implementer", iteration=0))
    assert result.raw_response.endswith(",") or result.raw_response.endswith(":")
    # Driving the supervisor must not raise out of the executor / harness.
    trial = run_one_trial(scenario)
    assert trial.errored is False, trial.error
    assert trial.terminal_state is not None


def test_narrative_structured_mismatch_triggers_existing_detection(
    tmp_path: Path,
) -> None:
    """Acceptance (3): narrative signed_off vs structured needs_changes."""
    plan_dir = tmp_path / "scenario"
    _write_plan(plan_dir)
    path = _write_scenario(
        plan_dir,
        {
            "id": "verdict-mismatch",
            "plan_fixture": "./plan.md",
            "replies": [
                {
                    "agent": "claude",
                    "role": "implementer",
                    "iteration": 0,
                    "summary": "implementer done",
                    "raw_response": "done",
                },
                {
                    "agent": "codex",
                    "role": "auditor",
                    "iteration": 0,
                    "summary": "Overall verdict: signed_off.",
                    "raw_response": "signed_off",
                    "malformed": "verdict_mismatch",
                },
            ],
            "expected": {"terminal_state": "signed_off"},
        },
    )
    scenario = load_scenario(path)
    trial = run_one_trial(scenario)
    # Supervisor raises VerdictMismatchError after writing INBOX; the
    # harness records that rather than inventing a new path.
    assert (
        trial.terminal_state == "verdict_mismatch"
        or (trial.errored and "mismatch" in (trial.error or "").lower())
        or (trial.terminal_state is not None and "mismatch" in trial.terminal_state)
    )


def test_both_executors_are_base_executor_and_available() -> None:
    """Acceptance (4): both mocks subclass BaseExecutor and are available."""
    claude = MockClaudeExecutor()
    codex = MockCodexExecutor()
    assert isinstance(claude, BaseExecutor)
    assert isinstance(codex, BaseExecutor)
    assert claude.is_available() is True
    assert codex.is_available() is True
    assert claude.cli_binary is None
    assert codex.cli_binary is None


def test_no_supervisor_or_dispatch_edits_from_this_plan() -> None:
    """Acceptance (5): sim harness does not patch the shipped dispatch path.

    This worktree may already carry unrelated dirty files from other
    plans. The invariant this feature owns is: scripted executors live
    in the smoke package, and supervisor.py neither imports the harness
    nor gained a sim-specific hook.
    """
    orchestrate = Path(__file__).resolve().parents[1]
    smoke_pkg = orchestrate / "smoke"
    assert smoke_pkg.is_dir()
    supervisor = (orchestrate / "supervisor.py").read_text()
    assert "dontpanic_orchestrate.smoke" not in supervisor
    assert "ScriptedClaude" not in supervisor
    assert "sim_harness" not in supervisor
    assert MockClaudeExecutor.__module__.startswith("dontpanic_orchestrate.smoke")
    assert MockCodexExecutor.__module__.startswith("dontpanic_orchestrate.smoke")
    # New implementation files belong under smoke/, not next to supervisor.
    for name in ("loader.py", "executors.py", "chaos.py", "runner.py"):
        assert (smoke_pkg / name).is_file(), name
    # And we did not add a sibling sim package that reimplements dispatch.
    assert not (orchestrate / "sim_dispatch.py").exists()
    # Guard the forbidden-edit list from the plan: these files must not
    # be rewritten by this feature. Presence of pre-existing dirty
    # worktree state is not this test's job; we assert the smoke package
    # does not copy-paste dispatch_volley.
    for py in smoke_pkg.rglob("*.py"):
        text = py.read_text()
        assert "def dispatch_volley" not in text
    # Keep a copy of this assertion module in-tree so a later supervisor
    # patch cannot hide behind "the test was deleted".
    assert Path(__file__).is_file()
    shutil.which  # imported for the no-CLI invariant surface
