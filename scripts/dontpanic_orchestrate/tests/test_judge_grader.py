"""Plan 2026-08-09-004 F005 — opt-in narrative judge, rubric-versioned."""

from __future__ import annotations

from pathlib import Path

import pytest

from dontpanic_orchestrate.graders import (
    GraderVerdict,
    TrialArtifacts,
    TrialRecord,
    judge_grader,
)

RUBRIC = "judge-rubric-v0"


class TestJudgeGrader:
    def test_default_run_makes_no_model_call(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*a: object, **k: object) -> None:
            raise AssertionError("model invoked")

        monkeypatch.setattr("dontpanic_orchestrate.graders._invoke_judge_model", _boom)
        results = list(
            judge_grader(
                TrialRecord(id="t0", expected_terminal="signed_off"),
                TrialArtifacts(root=tmp_path),
            )
        )
        assert any("not evaluate" in r.reason.lower() or r.verdict is GraderVerdict.NOT_APPLICABLE for r in results)

    def test_disabled_report_names_skipped_dimensions(self, tmp_path: Path) -> None:
        results = list(
            judge_grader(
                TrialRecord(id="t0", expected_terminal="signed_off"),
                TrialArtifacts(root=tmp_path),
            )
        )
        text = " ".join(r.reason for r in results)
        assert "rationale" in text.lower()
        assert "audit summary" in text.lower() or "verdict" in text.lower()

    def test_enabled_result_carries_rubric_version(self, tmp_path: Path) -> None:
        (tmp_path / "decisions.jsonl").write_text(
            '{"id":"D001","question":"Ship?","answer":"Ship.","rationale":"Ship.","status":"resolved"}\n'
        )
        results = list(
            judge_grader(
                TrialRecord(id="t0", expected_terminal="signed_off"),
                TrialArtifacts(root=tmp_path),
                enabled=True,
            )
        )
        judged = [r for r in results if r.grader_id == "judge"]
        assert judged
        assert all(RUBRIC in (r.reason + r.artifact) or r.artifact == RUBRIC for r in judged)

    def test_restated_rationale_is_recorded(self, tmp_path: Path) -> None:
        (tmp_path / "decisions.jsonl").write_text(
            '{"id":"D001","question":"Lock now?","answer":"Lock now.","rationale":"Lock now.","status":"resolved"}\n'
        )
        results = list(
            judge_grader(
                TrialRecord(id="t0", expected_terminal="signed_off"),
                TrialArtifacts(root=tmp_path),
                enabled=True,
            )
        )
        judged = [r for r in results if r.grader_id == "judge"]
        assert judged
        assert any(r.reason for r in judged)

    def test_deterministic_mismatch_wins(self, tmp_path: Path) -> None:
        (tmp_path / "audit.json").write_text(
            '{"narrative_verdict":"blocked","structured_status":"signed_off"}'
        )
        results = list(
            judge_grader(
                TrialRecord(id="t0", expected_terminal="signed_off"),
                TrialArtifacts(root=tmp_path),
                enabled=True,
                deterministic_mismatch=True,
            )
        )
        auth = [r for r in results if r.grader_id == "judge_authoritative"]
        assert auth
        assert auth[0].verdict is GraderVerdict.FAIL
        assert "deterministic" in auth[0].reason.lower()
