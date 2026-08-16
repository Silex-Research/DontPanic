"""Plan 2026-08-09-005 F001 — suite membership is a deliberate choice."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate.smoke.corpus import discover_scenarios
from dontpanic_orchestrate.smoke.loader import ScenarioLoadError, load_scenario


def _write(tmp: Path, payload: dict) -> Path:
    src = json.loads(
        Path(
            "scripts/dontpanic_orchestrate/smoke/scenarios/"
            "2026-05-19-901-feat-smoke-synthetic/scenario.json"
        ).read_text()
    )
    src.update(payload)
    path = tmp / "scenario.json"
    path.write_text(json.dumps(src))
    # fixtures via relative path from tmp won't work; copy required files
    plan = Path(
        "scripts/dontpanic_orchestrate/smoke/scenarios/"
        "2026-05-19-901-feat-smoke-synthetic/plan.md"
    )
    feats = Path(
        "scripts/dontpanic_orchestrate/smoke/scenarios/"
        "2026-05-19-901-feat-smoke-synthetic/features.json"
    )
    (tmp / "plan.md").write_text(plan.read_text())
    (tmp / "features.json").write_text(feats.read_text())
    src["plan_fixture"] = "./plan.md"
    src["features_fixture"] = "./features.json"
    path.write_text(json.dumps(src))
    return path


class TestSuiteMembership:
    def test_missing_suite_is_rejected(self, tmp_path: Path) -> None:
        path = _write(tmp_path, {})
        payload = json.loads(path.read_text())
        payload.pop("suite", None)
        path.write_text(json.dumps(payload))
        with pytest.raises(ScenarioLoadError, match="suite"):
            load_scenario(path)

    def test_unknown_suite_is_rejected(self, tmp_path: Path) -> None:
        path = _write(tmp_path, {"suite": "experimental"})
        with pytest.raises(ScenarioLoadError):
            load_scenario(path)

    def test_every_on_disk_scenario_has_membership(self) -> None:
        scenarios = discover_scenarios()
        assert scenarios
        assert all(s.suite in {"regression", "capability"} for s in scenarios)

    def test_suite_change_is_in_the_scenario_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path, {"suite": "capability"})
        before = path.read_text()
        payload = json.loads(before)
        payload["suite"] = "regression"
        path.write_text(json.dumps(payload, indent=2) + "\n")
        after = path.read_text()
        assert before != after
        assert '"suite": "regression"' in after
        assert '"suite": "capability"' in before
