"""pre_merge is a per-FEATURE human stop.

Approving pre_merge for F001 used to write plan-wide ``pre_merge`` into
``cleared_gates`` + ``completed_stages``, so F002's candidate-success path
skipped its own stop and wrote a success signoff unreviewed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import gate_pause, signoff_writer, supervisor
from dontpanic_orchestrate.tests import test_lifecycle_staged_gates as staged

DECLARED = ["pre_impl", "pre_merge"]


def _pause_and_approve(plan_dir: Path, stage: str, feature_id: str | None) -> None:
    gate_pause.record_pause(
        plan_dir, plan_id="p", pause_gates=[stage], stage=stage, feature_id=feature_id
    )
    assert gate_pause.approve_gate(plan_dir, stage, plan_id="p")


def test_f001_approval_does_not_clear_pre_merge_for_f002(tmp_path: Path) -> None:
    _pause_and_approve(tmp_path, "pre_impl", None)
    _pause_and_approve(tmp_path, "pre_merge", "F001")

    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F001")
    assert not gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F002")
    info = gate_pause.evaluate_human_gates(tmp_path, DECLARED, "pre_merge", feature_id="F002")
    assert info.paused and info.pending == ["pre_merge"]
    # Same feature resumes without re-pausing (idempotent within the feature).
    assert not gate_pause.evaluate_human_gates(
        tmp_path, DECLARED, "pre_merge", feature_id="F001"
    ).paused

    # F002 reaches the stop: it re-arms and can be approved through the normal
    # path, for F002 only; F001 stays completed.
    gate_pause.record_pause(
        tmp_path, plan_id="p", pause_gates=["pre_merge"], stage="pre_merge", feature_id="F002"
    )
    assert gate_pause.is_gate_currently_pending(tmp_path, "pre_merge")
    assert not gate_pause.is_gate_cleared(tmp_path, "pre_merge")
    assert gate_pause.approve_gate(tmp_path, "pre_merge", plan_id="p")
    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F002")
    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F001")
    assert not gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F003")
    state = json.loads(gate_pause.gate_state_path(tmp_path).read_text())
    assert state["completed_stage_features"] == {"pre_merge": ["F001", "F002"]}
    # Plan-wide fields are still written for other readers.
    assert "pre_merge" in state["cleared_gates"]
    assert "pre_merge" in state["completed_stages"]


def test_no_feature_id_fails_closed_for_pre_merge(tmp_path: Path) -> None:
    _pause_and_approve(tmp_path, "pre_merge", "F001")
    assert not gate_pause.is_stage_completed(tmp_path, "pre_merge")
    assert gate_pause.evaluate_human_gates(tmp_path, DECLARED, "pre_merge").paused


def test_resume_all_completes_pre_merge_for_the_pending_feature(tmp_path: Path) -> None:
    _pause_and_approve(tmp_path, "pre_merge", "F001")
    gate_pause.record_pause(
        tmp_path, plan_id="p", pause_gates=["pre_merge"], stage="pre_merge", feature_id="F002"
    )
    assert gate_pause.resume_all(tmp_path, plan_id="p", declared_gates=DECLARED) == ["pre_merge"]
    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F002")


def test_legacy_plan_wide_pre_merge_fails_closed(tmp_path: Path) -> None:
    path = gate_pause.gate_state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "plan_id": "p",
                "cleared_gates": ["pre_impl", "pre_merge"],
                "completed_stages": ["pre_impl", "pre_merge"],
                "history": [],
            }
        )
    )
    assert gate_pause.is_stage_completed(tmp_path, "pre_impl")
    assert not gate_pause.evaluate_human_gates(tmp_path, DECLARED, "pre_impl").paused
    assert not gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F002")
    assert gate_pause.evaluate_human_gates(
        tmp_path, DECLARED, "pre_merge", feature_id="F002"
    ).paused


def _add_feature(plan_dir: Path, feature_id: str) -> None:
    features_path = plan_dir / "features.json"
    data = json.loads(features_path.read_text())
    data["features"].append({**data["features"][0], "id": feature_id})
    features_path.write_text(json.dumps(data, indent=2) + "\n")


def test_supervisor_f002_pauses_after_f001_pre_merge_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    impl = staged._ScriptedExecutor("claude", order=order)
    aud = staged._ScriptedExecutor("codex", order=order)
    staged._install_runtime(monkeypatch, impl, aud)
    plan_id = "2026-11-23-910-infra-pre-merge-per-feature"
    plan_dir = staged._make_plan(tmp_path, plan_id, DECLARED)
    _add_feature(plan_dir, "F002")
    staged._preclear_stage(plan_dir, plan_id, "pre_impl")

    first = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert first.final_status == "paused_on_gate", first
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id)
    f001 = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert f001.final_status == "signed_off", f001

    signoffs: list[str] = []
    original = signoff_writer.write_signoff

    def record(*args, **kwargs):
        signoffs.append("write_signoff")
        return original(*args, **kwargs)

    monkeypatch.setattr(signoff_writer, "write_signoff", record)
    f002 = supervisor.dispatch_volley(plan_dir, "F002", max_iterations=1)

    assert f002.final_status == "paused_on_gate", f002
    assert "pre_merge" in f002.reason
    assert signoffs == []
    state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
    assert state["pending_stage"] == "pre_merge"
    assert state["pending_feature_id"] == "F002"
