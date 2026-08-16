"""Plan 2026-08-09-004 F001 — grader contract.

A grader returns a typed result, never writes the artifacts it inspects,
and cannot pretend silence is a pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dontpanic_orchestrate.graders import (
    GraderResult,
    GraderVerdict,
    TrialArtifacts,
    TrialRecord,
)


class TestResultConstruction:
    def test_omitting_required_field_is_rejected(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            GraderResult(  # type: ignore[call-arg]
                verdict=GraderVerdict.PASS,
                reason="ok",
                artifact="plan.md",
                grader_id="schema",
                # component omitted
            )

    def test_not_applicable_is_distinct_from_pass(self) -> None:
        na = GraderResult(
            verdict=GraderVerdict.NOT_APPLICABLE,
            reason="no plan artifacts in this trial",
            artifact="(none)",
            grader_id="schema",
            component="harness",
        )
        ok = GraderResult(
            verdict=GraderVerdict.PASS,
            reason="frontmatter valid",
            artifact="plan.md",
            grader_id="schema",
            component="system",
        )
        assert na.verdict != ok.verdict
        assert na.verdict is GraderVerdict.NOT_APPLICABLE


class TestPurityAndComponent:
    def test_write_attempt_fails_purity(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        artifact = tmp_path / "plan.md"
        artifact.write_text("id: x\n")
        trial = TrialRecord(id="t0", expected_terminal="signed_off")
        handle = TrialArtifacts(root=tmp_path)

        def _boom(*a: Any, **k: Any) -> None:
            raise AssertionError("grader wrote")

        monkeypatch.setattr(Path, "write_text", _boom)
        monkeypatch.setattr(Path, "write_bytes", _boom)

        def dirty_grader(_trial: TrialRecord, arts: TrialArtifacts) -> list[GraderResult]:
            arts.path("plan.md").write_text("mutated")
            return []

        with pytest.raises(AssertionError, match="grader wrote"):
            dirty_grader(trial, handle)

    def test_no_opinion_is_not_applicable(self, tmp_path: Path) -> None:
        trial = TrialRecord(id="empty", expected_terminal="signed_off")
        handle = TrialArtifacts(root=tmp_path)
        from dontpanic_orchestrate.graders import silent_grader, aggregate

        results = list(silent_grader(trial, handle))
        assert results
        assert all(r.verdict is GraderVerdict.NOT_APPLICABLE for r in results)
        summary = aggregate(results)
        assert summary.passed is False
        assert summary.not_applicable is True
        assert summary.failed is False
