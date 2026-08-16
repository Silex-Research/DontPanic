"""Plan 2026-08-09-003 F004 — multi-trial runner with per-trial isolation.

Acceptance:
  (1) A scenario run with N=20 produces 20 trial records.
  (2) A scenario whose fixture is mutated during trial 3 leaves trial
      4's outcome unchanged.
  (3) A trial that raises is recorded as errored and later trials still
      run.
  (4) Each trial record carries terminal state, iteration count,
      duration, and token counts.
  (5) Default invocation runs exactly one trial.

Run:
    PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_multi_trial_runner.py -q
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dontpanic_orchestrate.smoke.loader import DEFAULT_SCENARIO_PATH, load_scenario
from dontpanic_orchestrate.smoke import runner as runner_mod
from dontpanic_orchestrate.smoke.runner import run_one_trial, run_scenario


def test_n_20_produces_20_trial_records() -> None:
    """Acceptance (1)."""
    scenario = load_scenario(DEFAULT_SCENARIO_PATH)
    result = run_scenario(scenario, n=20)
    assert len(result.trials) == 20


def test_fixture_mutation_in_trial_3_does_not_affect_trial_4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance (2): each trial copies the fixture independently."""
    from dontpanic_orchestrate.smoke.executors import MockClaudeExecutor

    scenario = load_scenario(DEFAULT_SCENARIO_PATH)
    original = scenario.plan_fixture.read_text()
    real_dispatch = MockClaudeExecutor.dispatch
    calls = {"n": 0}

    def _mutating_dispatch(self: Any, task: Any) -> Any:
        calls["n"] += 1
        # Third implementer call is trial 3 (one implementer dispatch
        # per default-scenario trial). Mutate the working copy only.
        if calls["n"] == 3:
            plan_md = Path(task.plan_dir) / "plan.md"
            plan_md.write_text(plan_md.read_text() + "\n# mutated in trial 3\n")
        return real_dispatch(self, task)

    monkeypatch.setattr(MockClaudeExecutor, "dispatch", _mutating_dispatch)
    result = run_scenario(scenario, n=4)

    assert scenario.plan_fixture.read_text() == original
    assert len(result.trials) == 4
    assert result.trials[3].reached_expected is True
    assert result.trials[3].errored is False


def test_errored_trial_does_not_abort_remaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance (3)."""
    scenario = load_scenario(DEFAULT_SCENARIO_PATH)
    real = runner_mod.run_one_trial
    calls = {"n": 0}

    def _flaky(scenario_arg: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("injected trial boom")
        return real(scenario_arg, **kwargs)

    monkeypatch.setattr(runner_mod, "run_one_trial", _flaky)
    result = run_scenario(scenario, n=4)
    assert len(result.trials) == 4
    assert result.trials[1].errored is True
    assert "boom" in (result.trials[1].error or "")
    assert result.trials[2].errored is False
    assert result.trials[3].errored is False
    assert result.trials[3].terminal_state is not None


def test_each_trial_record_carries_required_fields() -> None:
    """Acceptance (4)."""
    scenario = load_scenario(DEFAULT_SCENARIO_PATH)
    result = run_scenario(scenario, n=1)
    assert len(result.trials) == 1
    trial = result.trials[0]
    assert trial.terminal_state is not None
    assert isinstance(trial.iteration_count, int)
    assert trial.iteration_count >= 0
    assert isinstance(trial.duration_s, float)
    assert trial.duration_s >= 0.0
    assert isinstance(trial.tokens_in, int)
    assert isinstance(trial.tokens_out, int)
    assert trial.tokens_in >= 0
    assert trial.tokens_out >= 0


def test_default_invocation_runs_exactly_one_trial() -> None:
    """Acceptance (5)."""
    scenario = load_scenario(DEFAULT_SCENARIO_PATH)
    result = run_scenario(scenario)
    assert len(result.trials) == 1
    single = run_one_trial(scenario)
    assert single.trial_index == 0
