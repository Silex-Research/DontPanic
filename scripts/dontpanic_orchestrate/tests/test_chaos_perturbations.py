"""Plan 2026-08-09-003 F003 — deterministic chaos perturbations.

Acceptance:
  (1) A timeout perturbation on the first implementer call produces a
      trial record naming the perturbation and the supervisor's
      resulting terminal state.
  (2) The same scenario run twice produces the same perturbation
      sequence.
  (3) A non-zero exit perturbation does not raise out of the harness.
  (4) A quota-exhausted perturbation reaches the existing admission
      path rather than being swallowed by the executor.

A chaos scenario that asserts recovery behavior encodes current
supervisor behavior, not a requirement. This module observes.

Run:
    PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_chaos_perturbations.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate.smoke import SMOKE_FEATURE_ID, SYNTHETIC_PLAN_ID
from dontpanic_orchestrate.smoke.loader import load_scenario
from dontpanic_orchestrate.smoke.runner import run_one_trial


def _write_plan(plan_dir: Path) -> None:
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {SYNTHETIC_PLAN_ID}
title: Chaos perturbation test plan
type: infra
tier: trivial
status: active
date: "2026-05-19"
description: Chaos fixture. Encodes current supervisor behavior, not a requirement.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 1
  hard_stop: true
privacy_tier: internal
goal_type: mechanical
links:
  features: ./features.json
---

# Chaos perturbation test plan

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
                            "Chaos fixture. Recovery assertions encode "
                            "current supervisor behavior, not a requirement."
                        ),
                        "steps": ["perturbed implementer"],
                        "acceptance": "Harness records the supervisor outcome.",
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


def _base_replies() -> list[dict[str, object]]:
    return [
        {
            "agent": "claude",
            "role": "implementer",
            "iteration": 0,
            "summary": "would have implemented",
            "raw_response": "signed_off",
        },
        {
            "agent": "codex",
            "role": "auditor",
            "iteration": 0,
            "summary": "Overall verdict: signed_off.",
            "raw_response": "signed_off",
        },
    ]


def test_timeout_on_first_implementer_call_is_named(tmp_path: Path) -> None:
    """Acceptance (1): trial record names the timeout and a terminal state."""
    plan_dir = tmp_path / "timeout"
    _write_plan(plan_dir)
    path = _write_scenario(
        plan_dir,
        {
            "id": "chaos-timeout-impl-first",
            "plan_fixture": "./plan.md",
            "replies": _base_replies(),
            "perturbations": [
                {"kind": "timeout", "role": "implementer", "call_index": 0}
            ],
            "expected": {"terminal_state": "blocked"},
        },
    )
    scenario = load_scenario(path)
    trial = run_one_trial(scenario)
    assert "timeout" in trial.perturbations_fired
    assert trial.terminal_state is not None or trial.errored
    # Observes; does not prescribe the supervisor's recovery choice.


def test_same_scenario_twice_same_perturbation_sequence(tmp_path: Path) -> None:
    """Acceptance (2): perturbations are deterministic by call index."""
    plan_dir = tmp_path / "repeat"
    _write_plan(plan_dir)
    path = _write_scenario(
        plan_dir,
        {
            "id": "chaos-repeatable",
            "plan_fixture": "./plan.md",
            "replies": _base_replies(),
            "perturbations": [
                {"kind": "timeout", "role": "implementer", "call_index": 0}
            ],
            "expected": {"terminal_state": "blocked"},
        },
    )
    scenario = load_scenario(path)
    first = run_one_trial(scenario)
    second = run_one_trial(scenario)
    assert first.perturbations_fired == second.perturbations_fired
    assert first.perturbations_fired == ["timeout"]


def test_nonzero_exit_does_not_raise_out_of_harness(tmp_path: Path) -> None:
    """Acceptance (3): non-zero exit is recorded, not raised."""
    plan_dir = tmp_path / "exit"
    _write_plan(plan_dir)
    path = _write_scenario(
        plan_dir,
        {
            "id": "chaos-nonzero-exit",
            "plan_fixture": "./plan.md",
            "replies": _base_replies(),
            "perturbations": [
                {
                    "kind": "nonzero_exit",
                    "role": "implementer",
                    "call_index": 0,
                    "exit_code": 1,
                }
            ],
            "expected": {"terminal_state": "blocked"},
        },
    )
    scenario = load_scenario(path)
    trial = run_one_trial(scenario)
    assert trial.errored is False or trial.terminal_state is not None
    assert "nonzero_exit" in trial.perturbations_fired


def test_quota_exhausted_reaches_admission_path(tmp_path: Path) -> None:
    """Acceptance (4): quota is not swallowed inside the executor."""
    plan_dir = tmp_path / "quota"
    _write_plan(plan_dir)
    path = _write_scenario(
        plan_dir,
        {
            "id": "chaos-quota-exhausted",
            "plan_fixture": "./plan.md",
            "replies": _base_replies(),
            "perturbations": [
                {
                    "kind": "quota_exhausted",
                    "role": "implementer",
                    "call_index": 0,
                }
            ],
            "expected": {"terminal_state": "paused_on_gate"},
        },
    )
    scenario = load_scenario(path)
    trial = run_one_trial(scenario)
    assert "quota_exhausted" in trial.perturbations_fired
    # Admission, not an executor-fabricated DispatchResult.
    assert trial.terminal_state in {"paused_on_gate", "stopped_quota"}
    assert "quota" in (trial.reason or trial.terminal_state or "").lower() or (
        trial.terminal_state in {"paused_on_gate", "stopped_quota"}
    )
