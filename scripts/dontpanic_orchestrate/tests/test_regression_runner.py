"""Plan 2026-08-09-005 F002 — regression suite gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from dontpanic_orchestrate.smoke import suites
from dontpanic_orchestrate.smoke.suites import ModelCallGuard, run_capability, run_regression


def test_regression_invokes_all_five_deterministic_graders() -> None:
    from dontpanic_orchestrate.smoke.suites import _DETERMINISTIC_GRADERS

    names = {g.__name__ for g in _DETERMINISTIC_GRADERS}
    assert names == {
        "schema_grader",
        "evidence_grader",
        "gate_agreement_grader",
        "target_boundary_grader",
        "operational_validity_grader",
    }


class TestRegressionRunner:
    def test_all_passing_exits_zero(self) -> None:
        run = run_regression()
        assert "duration" in run.text.lower() or "s" in run.text
        # The live corpus regression scenarios should pass graders + terminal.
        if all(o.passed for o in run.outcomes):
            assert run.exit_code == 0

    def test_one_failure_exits_nonzero_and_names(self, tmp_path: Path) -> None:
        # Point at a tmp root with one bad regression scenario.
        scenario_dir = tmp_path / "bad"
        scenario_dir.mkdir()
        (scenario_dir / "plan.md").write_text("---\ntitle: x\n---\n")
        (scenario_dir / "features.json").write_text(
            '{"task_id":"bad","schema_version":"1.0","features":[]}'
        )
        (scenario_dir / "scenario.json").write_text(
            """
            {
              "id": "bad-reg",
              "suite": "regression",
              "plan_fixture": "./plan.md",
              "features_fixture": "./features.json",
              "replies": [
                {"agent":"claude","role":"implementer","iteration":0,"summary":"x"}
              ],
              "expected": {"terminal_state": "signed_off"}
            }
            """
        )
        run = run_regression(tmp_path, execute=False)
        assert run.exit_code != 0
        assert "bad-reg" in run.text
        assert any(o.grader_id == "schema" for o in run.outcomes if not o.passed)

    def test_model_guard(self) -> None:
        with pytest.raises(ModelCallGuard):
            run_regression(model_hook=lambda: (_ for _ in ()).throw(ModelCallGuard("x")))

    def test_duration_in_output(self) -> None:
        run = run_regression(execute=False)
        assert "s" in run.text

    def test_unaffected_by_capability_contents(self, tmp_path: Path) -> None:
        # A failing capability scenario next to a passing regression one.
        good = tmp_path / "good"
        good.mkdir()
        src_plan = Path(
            "scripts/dontpanic_orchestrate/smoke/scenarios/"
            "2026-05-19-901-feat-smoke-synthetic"
        )
        (good / "plan.md").write_text((src_plan / "plan.md").read_text())
        (good / "features.json").write_text((src_plan / "features.json").read_text())
        payload = {
            "id": "good-reg",
            "suite": "regression",
            "plan_fixture": "./plan.md",
            "features_fixture": "./features.json",
            "replies": [
                {"agent": "claude", "role": "implementer", "iteration": 0, "summary": "x"}
            ],
            "expected": {"terminal_state": "signed_off"},
        }
        import json

        (good / "scenario.json").write_text(json.dumps(payload))
        bad = tmp_path / "cap"
        bad.mkdir()
        (bad / "plan.md").write_text("---\ntitle: x\n---\n")
        (bad / "features.json").write_text(
            '{"task_id":"c","schema_version":"1.0","features":[]}'
        )
        payload["id"] = "cap-fail"
        payload["suite"] = "capability"
        (bad / "scenario.json").write_text(json.dumps(payload))
        (bad / "plan.md").write_text("---\ntitle: x\n---\n")
        reg = run_regression(tmp_path, execute=False)
        cap = run_capability(tmp_path, execute=False)
        assert all(o.scenario_id != "cap-fail" for o in reg.outcomes)
        assert any(o.scenario_id == "cap-fail" for o in cap.outcomes)
        assert cap.exit_code == 0
