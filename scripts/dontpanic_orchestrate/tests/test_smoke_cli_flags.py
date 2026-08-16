"""Plan 2026-08-09-003 F006 — opt-in smoke flags, default preserved.

Acceptance:
  (1) With no flags, the command's terminal state and exit code match
      a baseline recorded before this feature.
  (2) A trial count below one is rejected before any trial starts.
  (3) A scenario path that does not exist is rejected before any
      trial starts.

Run:
    PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_smoke_cli_flags.py -q
"""

from __future__ import annotations

from typing import Any

import pytest

from dontpanic_orchestrate.smoke import (
    EXIT_ENV_BLOCKER,
    EXIT_PASS,
    smoke_main,
)
from dontpanic_orchestrate.smoke import runner as runner_mod


# Baseline recorded against the pre-flag `dontpanic smoke --mode=mocked`
# contract (plan 2026-05-19-002 F003): exit 0, volley signed_off, eight
# named surfaces. The no-flag path must keep this.
_BASELINE_EXIT = EXIT_PASS
_BASELINE_VOLLEY = "signed_off"


def test_no_flags_matches_recorded_baseline(capsys: pytest.CaptureFixture[str]) -> None:
    """Acceptance (1)."""
    from dontpanic_orchestrate.smoke import run_smoke

    result = run_smoke(mode="mocked")
    assert result.exit_code == _BASELINE_EXIT
    assert result.volley_status == _BASELINE_VOLLEY
    exit_code = smoke_main([])
    assert exit_code == _BASELINE_EXIT
    captured = capsys.readouterr().out
    assert "signed_off" in captured or "exit=0" in captured


def test_trial_count_below_one_rejected_before_any_trial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance (2)."""
    started = {"n": 0}

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        started["n"] += 1
        raise AssertionError("trial started after invalid --trials")

    monkeypatch.setattr(runner_mod, "run_scenario", _boom)
    monkeypatch.setattr(runner_mod, "run_one_trial", _boom)

    def _invoke(argv: list[str]) -> int:
        try:
            return smoke_main(argv)
        except SystemExit as exc:
            return int(exc.code or 1)

    assert _invoke(["--trials", "0"]) != EXIT_PASS
    assert started["n"] == 0
    assert _invoke(["--trials", "-3"]) != EXIT_PASS
    assert started["n"] == 0


def test_missing_scenario_path_rejected_before_any_trial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Acceptance (3)."""
    started = {"n": 0}

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        started["n"] += 1
        raise AssertionError("trial started after missing --scenario")

    monkeypatch.setattr(runner_mod, "run_scenario", _boom)
    monkeypatch.setattr(runner_mod, "run_one_trial", _boom)
    missing = tmp_path / "does-not-exist" / "scenario.json"
    code = smoke_main(["--scenario", str(missing)])
    assert code != EXIT_PASS
    assert code in {EXIT_ENV_BLOCKER, 2} or code != 0
    assert started["n"] == 0
