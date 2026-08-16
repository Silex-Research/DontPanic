"""Plan 2026-08-09-004 F003 — gate-agreement and target-boundary graders."""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate.graders import (
    GraderVerdict,
    TrialArtifacts,
    TrialRecord,
    gate_agreement_grader,
    target_boundary_grader,
)


def _trial(tmp: Path) -> tuple[TrialRecord, TrialArtifacts]:
    return TrialRecord(id="t0", expected_terminal="signed_off"), TrialArtifacts(root=tmp)


class TestGateAgreement:
    def test_cleared_gate_missing_from_log_fails(self, tmp_path: Path) -> None:
        (tmp_path / "gate-state.json").write_text(
            json.dumps({"cleared_gates": ["pre_merge"]})
        )
        (tmp_path / "events.jsonl").write_text("")
        results = list(gate_agreement_grader(*_trial(tmp_path)))
        assert any(r.verdict is GraderVerdict.FAIL for r in results)

    def test_event_without_gate_state_entry_fails(self, tmp_path: Path) -> None:
        (tmp_path / "gate-state.json").write_text(json.dumps({"cleared_gates": []}))
        (tmp_path / "events.jsonl").write_text(
            json.dumps({"event": "gate_cleared", "gate": "pre_merge", "actor": "operator"})
            + "\n"
        )
        results = list(gate_agreement_grader(*_trial(tmp_path)))
        assert any(r.verdict is GraderVerdict.FAIL for r in results)

    def test_clean_agreement_passes(self, tmp_path: Path) -> None:
        (tmp_path / "gate-state.json").write_text(
            json.dumps({"cleared_gates": ["pre_merge"]})
        )
        (tmp_path / "events.jsonl").write_text(
            json.dumps({"event": "gate_cleared", "gate": "pre_merge", "actor": "operator"})
            + "\n"
        )
        results = list(gate_agreement_grader(*_trial(tmp_path)))
        assert results
        assert all(r.verdict is GraderVerdict.PASS for r in results)


class TestTargetBoundary:
    def test_write_outside_declared_repos_names_path(self, tmp_path: Path) -> None:
        (tmp_path / "declared_repos.json").write_text(json.dumps(["DontPanic"]))
        (tmp_path / "written_files.json").write_text(
            json.dumps(["/tmp/other-repo/secret.py"])
        )
        results = list(target_boundary_grader(*_trial(tmp_path)))
        failed = [r for r in results if r.verdict is GraderVerdict.FAIL]
        assert failed
        assert any("/tmp/other-repo/secret.py" in r.reason for r in failed)

    def test_writes_inside_declared_repo_pass(self, tmp_path: Path) -> None:
        (tmp_path / "declared_repos.json").write_text(json.dumps(["DontPanic"]))
        (tmp_path / "written_files.json").write_text(
            json.dumps(["DontPanic/scripts/foo.py"])
        )
        results = list(target_boundary_grader(*_trial(tmp_path)))
        assert results
        assert all(r.verdict is GraderVerdict.PASS for r in results)
