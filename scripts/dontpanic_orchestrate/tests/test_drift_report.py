"""Plan 2026-08-09-005 F005 — newly-failing vs still-failing."""

from __future__ import annotations

from dontpanic_orchestrate.smoke.suites import drift_report


def _run(suite: str, outcomes: list[dict]) -> dict:
    return {"suite": suite, "outcomes": outcomes}


class TestDriftReport:
    def test_still_failing_vs_newly_failing(self) -> None:
        prev = _run(
            "regression",
            [
                {"scenario_id": "a", "passed": False, "duration_s": 1.0},
                {"scenario_id": "b", "passed": True, "duration_s": 1.0},
            ],
        )
        curr = _run(
            "regression",
            [
                {"scenario_id": "a", "passed": False, "duration_s": 1.0},
                {"scenario_id": "b", "passed": False, "duration_s": 1.0},
            ],
        )
        report = drift_report(prev, curr)
        assert report["classifications"]["a"] == "still-failing"
        assert report["classifications"]["b"] == "newly-failing"

    def test_duration_flag_on_still_passing(self) -> None:
        prev = _run(
            "regression",
            [{"scenario_id": "a", "passed": True, "duration_s": 1.0}],
        )
        curr = _run(
            "regression",
            [{"scenario_id": "a", "passed": True, "duration_s": 3.0}],
        )
        report = drift_report(prev, curr)
        assert "a" in report["duration_flagged"]

    def test_missing_previous_is_honest(self) -> None:
        curr = _run("regression", [{"scenario_id": "a", "passed": False}])
        report = drift_report(None, curr)
        assert report["comparison"] is False
        assert "no comparison" in report["note"]

    def test_covers_both_suites(self) -> None:
        prev = _run("capability", [{"scenario_id": "a", "passed": True, "duration_s": 1}])
        curr = _run("regression", [{"scenario_id": "a", "passed": True, "duration_s": 1}])
        report = drift_report(prev, curr)
        assert set(report["suites"]) == {"capability", "regression"}
