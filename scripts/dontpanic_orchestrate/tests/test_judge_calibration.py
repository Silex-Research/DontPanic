"""Plan 2026-08-09-004 F006 — judge calibration against a labeled subset."""

from __future__ import annotations

from pathlib import Path

from dontpanic_orchestrate.graders import calibrate_judge

LABELS = (
    Path(__file__).resolve().parents[3]
    / "docs/plans/2026-08-09-004-feat-agent-graders-task-corpus/evidence/judge-labels-v0.json"
)


class TestJudgeCalibration:
    def test_report_states_rate_and_sample_size(self) -> None:
        report = calibrate_judge(LABELS)
        assert report.sample_size == 3
        assert "3" in report.text
        assert "%" in report.text or "rate" in report.text.lower()
        assert str(report.sample_size) in report.text.split("rate")[0] or str(
            report.sample_size
        ) in report.text

    def test_divergent_cases_listed(self) -> None:
        report = calibrate_judge(LABELS)
        for case in report.divergent:
            assert case.human_verdict
            assert case.judge_verdict
            assert case.human_reason
            assert case.judge_reason

    def test_every_label_names_assigner_and_date(self) -> None:
        report = calibrate_judge(LABELS)
        assert report.labels
        for label in report.labels:
            assert label.labeled_by
            assert label.labeled_at

    def test_sample_size_caveat(self) -> None:
        report = calibrate_judge(LABELS)
        assert "indication, not a guarantee" in report.text.lower() or (
            "indication" in report.text.lower() and "not a guarantee" in report.text.lower()
        )

    def test_rerun_reproduces_rate(self) -> None:
        first = calibrate_judge(LABELS)
        second = calibrate_judge(LABELS)
        assert first.agreement_rate == second.agreement_rate
        assert first.sample_size == second.sample_size
