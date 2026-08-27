"""Remaining-ceremony print: false ledger + green tests vs a real code fail.

A ``passes=false`` ledger after local tests already passed is missing
ceremony, not a rewrite. These tests pin that distinction on the renderer
and the inspect helper — the cheapest equivalent of the F017 leftover.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.remaining_ceremony import (  # noqa: E402
    inspect_feature,
    render,
)

_PLAN_ID = "2026-08-27-001-feat-remaining-ceremony"


def _feature(**overrides):
    row = {
        "id": "F017",
        "category": "test",
        "description": "Photo containment leftover: tests green, ledger false.",
        "acceptance": (
            "Local tests pass and evidence/F017.xcresult is present; "
            "auditor envelope + supervisor receipt still required for passes=true."
        ),
        "passes": False,
    }
    row.update(overrides)
    return row


def _write_verification(plan_dir: Path, status: str, iteration: int = 0) -> None:
    evidence = plan_dir / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"regression-{iteration}-implementer.json").write_text(
        json.dumps(
            {
                "status": status,
                "command": "pytest",
                "cwd": ".",
                "exit_code": 0 if status == "passed" else 1,
                "iteration": iteration,
                "role": "implementer",
            }
        )
        + "\n"
    )


def test_green_tests_false_ledger_prints_do_not_rewrite(tmp_path):
    """False ledger + passed verification: ceremony remains, do not recode."""
    plan_dir = tmp_path / _PLAN_ID
    plan_dir.mkdir()
    _write_verification(plan_dir, "passed")
    report = inspect_feature(
        plan_dir,
        _feature(),
        plan_id=_PLAN_ID,
        human_gates=["pre_merge"],
    )
    assert report is not None
    assert report.tests_status == "passed"
    text = render(report)
    assert "[remaining-ceremony] F017 ledger passes=false" in text
    assert "already passed locally — do not rewrite the feature" in text
    assert "auditor envelope missing" in text
    assert "supervisor receipt missing" in text
    assert "human gate pending: pre_merge" in text
    assert "missing evidence path from AC: evidence/F017.xcresult" in text
    assert "implementation still open" not in text


def test_failed_tests_false_ledger_prints_code_fail(tmp_path):
    """False ledger + failed verification: this is still a code fail."""
    plan_dir = tmp_path / _PLAN_ID
    plan_dir.mkdir()
    _write_verification(plan_dir, "failed")
    report = inspect_feature(
        plan_dir,
        _feature(id="F001", acceptance="pytest scripts/dontpanic_orchestrate/tests"),
        plan_id=_PLAN_ID,
    )
    assert report is not None
    assert report.tests_status == "failed"
    text = render(report)
    assert "[remaining-ceremony] F001 ledger passes=false" in text
    assert "tests: failed — implementation still open" in text
    assert "do not rewrite the feature" not in text
    assert "auditor envelope missing" in text


def test_passes_true_is_silent(tmp_path):
    report = inspect_feature(
        tmp_path,
        _feature(passes=True),
        plan_id=_PLAN_ID,
    )
    assert report is None


def test_xcresult_on_disk_counts_as_local_pass(tmp_path):
    """F017-shaped leftover: AC-named xcresult exists, no verification sidecar."""
    plan_dir = tmp_path / _PLAN_ID
    xcresult = plan_dir / "evidence" / "F017.xcresult"
    xcresult.parent.mkdir(parents=True)
    xcresult.write_text("ok\n")
    report = inspect_feature(plan_dir, _feature(), plan_id=_PLAN_ID)
    assert report is not None
    assert report.tests_status == "passed"
    text = render(report)
    assert "already passed locally — do not rewrite the feature" in text
    assert "missing evidence path from AC" not in text
