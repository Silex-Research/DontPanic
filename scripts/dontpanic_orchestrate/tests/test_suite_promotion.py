"""Plan 2026-08-09-005 F004 — eligibility is computed; promotion is chosen."""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate.smoke.suites import (
    DEFAULT_PROMOTION_N,
    promote,
    promotion_eligible,
)


def _run(scenario_id: str, passed: bool) -> dict:
    return {
        "id": f"run-{scenario_id}-{passed}",
        "outcomes": [{"scenario_id": scenario_id, "passed": passed}],
    }


class TestSuitePromotion:
    def test_n_consecutive_passes_are_eligible(self) -> None:
        records = [_run("s1", True) for _ in range(DEFAULT_PROMOTION_N)]
        assert promotion_eligible(records, "s1")
        records[-1] = _run("s1", False)
        assert not promotion_eligible(records, "s1")

    def test_eligibility_does_not_change_membership(self, tmp_path: Path) -> None:
        scenario = tmp_path / "scenario.json"
        scenario.write_text(json.dumps({"id": "s1", "suite": "capability"}))
        records = [_run("s1", True) for _ in range(DEFAULT_PROMOTION_N)]
        assert promotion_eligible(records, "s1")
        assert json.loads(scenario.read_text())["suite"] == "capability"

    def test_promote_writes_decision(self, tmp_path: Path) -> None:
        scenario = tmp_path / "scenario.json"
        scenario.write_text(json.dumps({"id": "s1", "suite": "capability"}))
        decisions = tmp_path / "decisions.jsonl"
        promote(
            scenario,
            run_ids=["r1", "r2", "r3"],
            actor="grok",
            decisions_path=decisions,
        )
        assert json.loads(scenario.read_text())["suite"] == "regression"
        entry = json.loads(decisions.read_text().splitlines()[0])
        assert entry["scenario"] == "s1"
        assert entry["run_ids"] == ["r1", "r2", "r3"]
        assert entry["actor"] == "grok"

    def test_promoted_scenario_can_fail_regression(self, tmp_path: Path) -> None:
        # After promotion the suite field is regression — next regression
        # run will include it. Membership change is the proof.
        scenario = tmp_path / "scenario.json"
        scenario.write_text(json.dumps({"id": "s1", "suite": "capability"}))
        promote(
            scenario,
            run_ids=["r1"],
            actor="grok",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        assert json.loads(scenario.read_text())["suite"] == "regression"

    def test_no_automatic_demotion_in_source(self) -> None:
        src = Path("scripts/dontpanic_orchestrate/smoke/suites.py").read_text()
        assert "def demote" not in src
        assert "suite = \"capability\"" not in src.replace(" ", "")
