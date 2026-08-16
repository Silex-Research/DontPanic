"""Plan 2026-08-09-003 F007 — multi-trial exit contract and summary line.

Acceptance:
  (1) A run where one trial misses its expected terminal state exits
      non-zero.
  (2) A run where every trial reaches it exits zero.
  (3) All three previously shipping exit codes remain reachable with
      unchanged meanings.
  (4) The summary line names an artifact path and that path exists on
      disk.

Run:
    PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_smoke_exit_contract.py -q
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from dontpanic_orchestrate.smoke import (
    EXIT_ENV_BLOCKER,
    EXIT_PASS,
    EXIT_SUPERVISOR_DEFECT,
    SYNTHETIC_PLAN_ID,
    SMOKE_FEATURE_ID,
    smoke_main,
)
from dontpanic_orchestrate.smoke.loader import DEFAULT_SCENARIO_PATH


def _write_plan(plan_dir: Path) -> None:
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {SYNTHETIC_PLAN_ID}
title: Exit contract test plan
type: infra
tier: trivial
status: active
date: "2026-05-19"
description: Exit-contract fixture.
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

# Exit contract

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
                        "description": "Exit-contract fixture for multi-trial smoke.",
                        "steps": ["mocked"],
                        "acceptance": "Exit codes keep their meanings.",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )


def test_missed_expected_state_exits_nonzero(tmp_path: Path) -> None:
    """Acceptance (1)."""
    _write_plan(tmp_path)
    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps(
            {
                "id": "expect-blocked-but-signs-off",
                "suite": "regression",
                "plan_fixture": "./plan.md",
                "replies": [
                    {
                        "agent": "claude",
                        "role": "implementer",
                        "iteration": 0,
                        "summary": "[smoke mock claude/implementer] synthetic",
                        "raw_response": "signed_off",
                    },
                    {
                        "agent": "codex",
                        "role": "auditor",
                        "iteration": 0,
                        "summary": "Overall verdict: signed_off.",
                        "raw_response": "signed_off",
                    },
                ],
                "expected": {"terminal_state": "blocked"},
            },
            indent=2,
        )
        + "\n"
    )
    code = smoke_main(["--scenario", str(scenario), "--trials", "1"])
    assert code != EXIT_PASS
    assert code == EXIT_SUPERVISOR_DEFECT


def test_all_trials_reaching_expected_exits_zero() -> None:
    """Acceptance (2)."""
    code = smoke_main(
        ["--scenario", str(DEFAULT_SCENARIO_PATH), "--trials", "2"]
    )
    assert code == EXIT_PASS


def test_three_shipping_exit_codes_remain_reachable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Acceptance (3): 0 pass / 1 supervisor defect / 2 env blocker."""
    assert smoke_main([]) == EXIT_PASS
    assert smoke_main(["--mode=live"]) == EXIT_ENV_BLOCKER
    # Supervisor-defect remains the miss-expected path (acceptance 1)
    # and the default run_smoke defect mapping. Reachability of 1 is
    # asserted by constructing a miss; reused here via a reserved mode
    # is not 1. Call the miss scenario's meaning via the constant.
    assert EXIT_SUPERVISOR_DEFECT == 1
    assert EXIT_ENV_BLOCKER == 2
    assert EXIT_PASS == 0
    capsys.readouterr()


def test_summary_line_names_existing_artifact_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Acceptance (4)."""
    code = smoke_main(
        ["--scenario", str(DEFAULT_SCENARIO_PATH), "--trials", "1"]
    )
    assert code == EXIT_PASS
    output = capsys.readouterr().out
    match = re.search(r"artifact=(\S+)", output)
    assert match is not None, output
    artifact = Path(match.group(1))
    assert artifact.is_file(), artifact
    payload = json.loads(artifact.read_text())
    assert "trials" in payload
    assert "aggregate" in payload
