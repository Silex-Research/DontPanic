"""Plan 2026-08-09-004 F004 — token-valid is not operationally valid."""

from __future__ import annotations

from pathlib import Path

import pytest

from dontpanic_orchestrate import command_validation, completion_gate
from dontpanic_orchestrate.graders import (
    GraderVerdict,
    TrialArtifacts,
    TrialRecord,
    operational_validity_grader,
)


def _write_plan(tmp: Path, *, status: str) -> None:
    (tmp / "plan.md").write_text(
        "---\n"
        "id: 2026-08-09-004-feat-agent-graders-task-corpus\n"
        "title: Operational validity fixture\n"
        "type: feat\n"
        "tier: local\n"
        f"status: {status}\n"
        'date: "2026-08-09"\n'
        "description: Fixture for the recorded non-active close case.\n"
        "---\n\n# Fixture\n"
    )
    (tmp / "features.json").write_text(
        '{"task_id":"2026-08-09-004-feat-agent-graders-task-corpus",'
        '"schema_version":"1.0","features":[]}'
    )
    (tmp / "rendered_commands.json").write_text(
        '["dontpanic plan close 2026-08-09-004-feat-agent-graders-task-corpus"]'
    )


class TestOperationalValidity:
    def test_non_active_close_is_token_ok_operationally_fail(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, status="draft")
        tokens = [
            "plan",
            "close",
            "2026-08-09-004-feat-agent-graders-task-corpus",
        ]
        assert command_validation.validate_command_tokens(tokens).ok
        results = list(
            operational_validity_grader(
                TrialRecord(id="t0", expected_terminal="signed_off"),
                TrialArtifacts(root=tmp_path),
            )
        )
        token_ok = [r for r in results if r.grader_id == "operational_token"]
        op = [r for r in results if r.grader_id == "operational_dry_run"]
        assert token_ok and token_ok[0].verdict is GraderVerdict.PASS
        assert op and op[0].verdict is GraderVerdict.FAIL

    def test_active_close_passes_both(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, status="active")
        results = list(
            operational_validity_grader(
                TrialRecord(id="t0", expected_terminal="signed_off"),
                TrialArtifacts(root=tmp_path),
            )
        )
        assert any(
            r.grader_id == "operational_token" and r.verdict is GraderVerdict.PASS
            for r in results
        )
        assert any(
            r.grader_id == "operational_dry_run" and r.verdict is GraderVerdict.PASS
            for r in results
        )

    def test_unknown_handler_is_not_applicable(self, tmp_path: Path) -> None:
        (tmp_path / "rendered_commands.json").write_text(
            '["dontpanic mystery-subcommand --please"]'
        )
        results = list(
            operational_validity_grader(
                TrialRecord(id="t0", expected_terminal="signed_off"),
                TrialArtifacts(root=tmp_path),
            )
        )
        dry = [r for r in results if r.grader_id == "operational_dry_run"]
        assert dry
        assert all(r.verdict is GraderVerdict.NOT_APPLICABLE for r in dry)

    def test_no_real_execution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_plan(tmp_path, status="draft")
        original = completion_gate.close_plan

        def _guard(plan_dir: Path, **kwargs: object) -> object:
            if not kwargs.get("dry_run"):
                raise AssertionError("close_plan executed for real")
            return original(plan_dir, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(completion_gate, "close_plan", _guard)
        list(
            operational_validity_grader(
                TrialRecord(id="t0", expected_terminal="signed_off"),
                TrialArtifacts(root=tmp_path),
            )
        )
