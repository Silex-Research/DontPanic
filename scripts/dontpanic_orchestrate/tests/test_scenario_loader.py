"""Plan 2026-08-09-003 F001 — scenario file format and loader.

Acceptance:
  (1) A scenario file that omits a required key is rejected at load with
      a message naming the key.
  (2) A scenario referencing a fixture path that does not exist is
      rejected at load, not at run time.
  (3) The ported existing synthetic plan loads and its parsed form
      carries the same plan id, feature count, and scripted replies as
      the hardcoded version.
  (4) A scenario directory copied to a different absolute path still
      loads.

Run:
    PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_scenario_loader.py -q
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dontpanic_orchestrate.smoke import SYNTHETIC_PLAN_ID, SMOKE_FEATURE_ID
from dontpanic_orchestrate.smoke.loader import (
    DEFAULT_SCENARIO_PATH,
    ScenarioLoadError,
    load_scenario,
)


def _write_min_plan(plan_dir: Path, plan_id: str = SYNTHETIC_PLAN_ID) -> None:
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        f'---\nid: {plan_id}\ntitle: loader test\ntype: infra\n'
        'tier: trivial\nstatus: active\ndate: "2026-05-19"\n'
        "description: loader fixture\n"
        "agents_required:\n  - claude\n  - codex\n"
        "links:\n  features: ./features.json\n---\n\n# loader\n"
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": plan_id,
                "features": [
                    {
                        "id": SMOKE_FEATURE_ID,
                        "category": "test",
                        "phase": 0,
                        "description": "Synthetic loader fixture for scenario validation.",
                        "steps": ["load"],
                        "acceptance": "Loads.",
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
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def test_missing_required_key_is_rejected_with_key_name(tmp_path: Path) -> None:
    """Acceptance (1): omit a required key → load fails naming the key."""
    _write_min_plan(tmp_path)
    path = _write_scenario(
        tmp_path,
        {
            # "id" omitted
            "plan_fixture": "./plan.md",
            "replies": [
                {
                    "agent": "claude",
                    "role": "implementer",
                    "iteration": 0,
                    "summary": "ok",
                }
            ],
            "expected": {"terminal_state": "signed_off"},
        },
    )
    with pytest.raises(ScenarioLoadError, match=r"\bid\b") as exc_info:
        load_scenario(path)
    assert "id" in str(exc_info.value)


def test_missing_fixture_path_is_rejected_at_load(tmp_path: Path) -> None:
    """Acceptance (2): missing fixture fails at load, not later."""
    path = _write_scenario(
        tmp_path,
        {
            "id": "missing-fixture",
            "suite": "regression",
            "plan_fixture": "./plan.md",
            "replies": [
                {
                    "agent": "claude",
                    "role": "implementer",
                    "iteration": 0,
                    "summary": "ok",
                }
            ],
            "expected": {"terminal_state": "signed_off"},
        },
    )
    with pytest.raises(ScenarioLoadError, match="plan.md") as exc_info:
        load_scenario(path)
    message = str(exc_info.value).lower()
    assert "not exist" in message or "missing" in message or "not found" in message


def test_ported_synthetic_plan_matches_hardcoded_smoke() -> None:
    """Acceptance (3): first scenario is the ported hardcoded synthetic plan."""
    scenario = load_scenario(DEFAULT_SCENARIO_PATH)
    assert scenario.plan_id == SYNTHETIC_PLAN_ID
    assert scenario.feature_count == 1
    assert scenario.feature_id == SMOKE_FEATURE_ID

    impl = scenario.reply_for("claude", "implementer", 0)
    aud = scenario.reply_for("codex", "auditor", 0)
    assert impl is not None
    assert aud is not None
    assert impl.raw_response == "signed_off"
    assert aud.raw_response == "signed_off"
    assert "synthetic implementer envelope" in impl.summary
    assert "Overall verdict: signed_off" in aud.summary
    assert "No real CLI invoked" in impl.summary
    assert "no real cli invoked" in aud.summary.lower()


def test_copied_scenario_directory_still_loads(tmp_path: Path) -> None:
    """Acceptance (4): fixtures resolve relative to the scenario file."""
    source_dir = DEFAULT_SCENARIO_PATH.parent
    dest_dir = tmp_path / "relocated" / "2026-05-19-901-feat-smoke-synthetic"
    shutil.copytree(source_dir, dest_dir)
    relocated = dest_dir / "scenario.json"
    assert relocated.resolve() != DEFAULT_SCENARIO_PATH.resolve()

    scenario = load_scenario(relocated)
    assert scenario.plan_id == SYNTHETIC_PLAN_ID
    assert scenario.feature_count == 1
    assert scenario.plan_fixture.is_file()
    assert scenario.plan_fixture.is_relative_to(dest_dir)
