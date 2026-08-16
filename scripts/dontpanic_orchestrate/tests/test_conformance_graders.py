"""Plan 2026-08-09-004 F002 — schema and evidence discipline graders."""

from __future__ import annotations

from pathlib import Path

from dontpanic_orchestrate.graders import (
    GraderVerdict,
    TrialArtifacts,
    TrialRecord,
    evidence_grader,
    schema_grader,
)


def _trial(tmp: Path) -> tuple[TrialRecord, TrialArtifacts]:
    return TrialRecord(id="t0", expected_terminal="signed_off"), TrialArtifacts(root=tmp)


class TestSchemaGrader:
    def test_missing_frontmatter_key_is_named(self, tmp_path: Path) -> None:
        (tmp_path / "plan.md").write_text("---\ntitle: x\n---\n\n# x\n")
        results = list(schema_grader(*_trial(tmp_path)))
        failed = [r for r in results if r.verdict is GraderVerdict.FAIL]
        assert failed
        assert any("id" in r.reason or "required" in r.reason.lower() for r in failed)

    def test_clean_plan_passes(self, tmp_path: Path) -> None:
        (tmp_path / "plan.md").write_text(
            "---\n"
            "id: 2026-08-09-004-feat-agent-graders-task-corpus\n"
            "title: Graders fixture\n"
            "type: feat\n"
            "tier: local\n"
            "status: draft\n"
            'date: "2026-08-09"\n'
            "description: Fixture plan used only by the conformance grader tests.\n"
            "---\n\n# Fixture\n"
        )
        (tmp_path / "features.json").write_text(
            '{"task_id":"2026-08-09-004-feat-agent-graders-task-corpus",'
            '"schema_version":"1.0","features":[]}'
        )
        results = list(schema_grader(*_trial(tmp_path)))
        assert results
        assert all(r.verdict is GraderVerdict.PASS for r in results)


class TestEvidenceGrader:
    def test_passing_feature_without_evidence_fails(self, tmp_path: Path) -> None:
        (tmp_path / "features.json").write_text(
            '{"task_id":"x","schema_version":"1.0","features":['
            '{"id":"F001","category":"test","phase":0,'
            '"description":"Flip without proof.",'
            '"steps":["x"],"acceptance":"x","passes":true,"depends_on":[]}]}'
        )
        results = list(evidence_grader(*_trial(tmp_path)))
        failed = [r for r in results if r.verdict is GraderVerdict.FAIL]
        assert failed

    def test_clean_passing_feature_passes(self, tmp_path: Path) -> None:
        (tmp_path / "features.json").write_text(
            '{"task_id":"x","schema_version":"1.0","features":['
            '{"id":"F001","category":"test","phase":0,'
            '"description":"Flip with proof.",'
            '"steps":["x"],"acceptance":"x","passes":true,"depends_on":[],'
            '"verified_by":["grok"],"verified_at":"2026-08-15T00:00:00Z",'
            '"evidence_refs":[{"type":"file","uri":"evidence/x.txt"}]}]}'
        )
        results = list(evidence_grader(*_trial(tmp_path)))
        assert results
        assert all(r.verdict is GraderVerdict.PASS for r in results)
