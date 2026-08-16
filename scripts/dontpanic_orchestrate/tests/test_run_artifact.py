"""Plan 2026-08-09-003 F005 — run artifact reliability and cost reporting.

Acceptance:
  (1) A 20-trial run writes one artifact containing 20 trial records
      and one aggregate block.
  (2) With 20 of 20 reaching the expected state the success fraction
      is exactly 1 and the all-succeed probability is exactly 1.
  (3) With 10 of 20 the artifact reports both the raw counts and the
      derived probabilities, and the raw counts are present rather
      than only a percentage.
  (4) Token and duration totals in the aggregate equal the sum over
      trial records.
  (5) Secret scrubbing passes over the artifact with a token-shaped
      string planted in a scenario id.

Run:
    PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_run_artifact.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate.smoke.artifact import write_run_artifact
from dontpanic_orchestrate.smoke.loader import DEFAULT_SCENARIO_PATH, load_scenario
from dontpanic_orchestrate.smoke.runner import TrialRecord, MultiTrialResult, run_scenario


def _record(
    index: int,
    *,
    reached: bool = True,
    tokens_in: int = 1,
    tokens_out: int = 2,
    duration_s: float = 0.25,
    scenario_id: str = "ok",
) -> TrialRecord:
    return TrialRecord(
        trial_index=index,
        terminal_state="signed_off" if reached else "blocked",
        expected_terminal_state="signed_off",
        reached_expected=reached,
        errored=False,
        error=None,
        iteration_count=1,
        perturbations_fired=[],
        duration_s=duration_s,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        scenario_id=scenario_id,
    )


def test_twenty_trial_run_writes_one_artifact_with_aggregate(tmp_path: Path) -> None:
    """Acceptance (1)."""
    scenario = load_scenario(DEFAULT_SCENARIO_PATH)
    artifact_path = tmp_path / "run.json"
    result = run_scenario(scenario, n=20, artifact_path=artifact_path)
    assert artifact_path.is_file()
    payload = json.loads(artifact_path.read_text())
    assert len(payload["trials"]) == 20
    assert len(result.trials) == 20
    assert isinstance(payload["aggregate"], dict)
    assert payload["aggregate"]["trials_run"] == 20


def test_twenty_of_twenty_success_fraction_and_all_succeed_are_one(
    tmp_path: Path,
) -> None:
    """Acceptance (2)."""
    trials = [_record(i) for i in range(20)]
    result = MultiTrialResult(scenario_id="all-pass", trials=trials)
    path = write_run_artifact(result, tmp_path / "all.json")
    payload = json.loads(path.read_text())
    agg = payload["aggregate"]
    assert agg["trials_run"] == 20
    assert agg["trials_reached_expected"] == 20
    assert agg["success_fraction"] == 1
    assert agg["pass_hat_k"] == 1


def test_ten_of_twenty_reports_raw_counts_and_probabilities(tmp_path: Path) -> None:
    """Acceptance (3)."""
    trials = [_record(i, reached=(i < 10)) for i in range(20)]
    result = MultiTrialResult(scenario_id="half", trials=trials)
    path = write_run_artifact(result, tmp_path / "half.json")
    payload = json.loads(path.read_text())
    agg = payload["aggregate"]
    assert agg["trials_run"] == 20
    assert agg["trials_reached_expected"] == 10
    assert "success_fraction" in agg
    assert "pass_at_k" in agg
    assert "pass_hat_k" in agg
    # Raw counts must be present, not only a percentage string.
    assert isinstance(agg["trials_run"], int)
    assert isinstance(agg["trials_reached_expected"], int)
    assert "%" not in str(agg["trials_reached_expected"])


def test_token_and_duration_totals_equal_sum_of_trials(tmp_path: Path) -> None:
    """Acceptance (4)."""
    trials = [
        _record(0, tokens_in=3, tokens_out=5, duration_s=0.10),
        _record(1, tokens_in=7, tokens_out=1, duration_s=0.20),
        _record(2, tokens_in=0, tokens_out=4, duration_s=0.05),
    ]
    result = MultiTrialResult(scenario_id="sums", trials=trials)
    path = write_run_artifact(result, tmp_path / "sums.json")
    agg = json.loads(path.read_text())["aggregate"]
    assert agg["tokens_in_total"] == 10
    assert agg["tokens_out_total"] == 10
    assert abs(agg["duration_s_total"] - 0.35) < 1e-9


def test_secret_scrubbing_redacts_planted_token_in_scenario_id(tmp_path: Path) -> None:
    """Acceptance (5)."""
    planted = "ghp_" + ("A" * 36)
    trials = [_record(0, scenario_id=f"planted-{planted}")]
    result = MultiTrialResult(scenario_id=f"planted-{planted}", trials=trials)
    path = write_run_artifact(result, tmp_path / "secret.json")
    text = path.read_text()
    assert planted not in text
    assert "[REDACTED]" in text
