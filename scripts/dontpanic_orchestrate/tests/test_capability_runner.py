"""Plan 2026-08-09-005 F003 — capability suite never gates."""

from __future__ import annotations

from dontpanic_orchestrate.smoke.suites import run_capability, run_regression


class TestCapabilityRunner:
    def test_all_failing_exits_zero(self, tmp_path) -> None:
        import json

        d = tmp_path / "c"
        d.mkdir()
        (d / "plan.md").write_text("---\ntitle: x\n---\n")
        (d / "features.json").write_text(
            '{"task_id":"c","schema_version":"1.0","features":[]}'
        )
        (d / "scenario.json").write_text(
            json.dumps(
                {
                    "id": "cap-all-fail",
                    "suite": "capability",
                    "plan_fixture": "./plan.md",
                    "features_fixture": "./features.json",
                    "replies": [
                        {
                            "agent": "claude",
                            "role": "implementer",
                            "iteration": 0,
                            "summary": "x",
                        }
                    ],
                    "expected": {"terminal_state": "signed_off"},
                }
            )
        )
        run = run_capability(tmp_path, execute=False)
        assert run.exit_code == 0
        assert not any(o.passed for o in run.outcomes)

    def test_counts_not_only_percentage(self) -> None:
        run = run_capability(execute=False)
        assert f"{run.passed_count}/{len(run.outcomes)}" in run.text or (
            str(run.passed_count) in run.text and str(len(run.outcomes)) in run.text
        )

    def test_per_scenario_outcomes(self) -> None:
        run = run_capability(execute=False)
        assert run.outcomes
        ids = {o.scenario_id for o in run.outcomes}
        assert ids

    def test_judge_disabled_is_named(self) -> None:
        run = run_capability(execute=False, judge=False)
        assert "not evaluated" in run.text.lower()

    def test_capability_failure_does_not_change_regression_exit(self) -> None:
        reg = run_regression(execute=False)
        _ = run_capability(execute=False)
        again = run_regression(execute=False)
        assert again.exit_code == reg.exit_code
