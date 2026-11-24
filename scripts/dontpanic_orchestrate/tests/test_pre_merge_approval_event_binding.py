"""A per-feature ``pre_merge`` completion is trusted only when a matching
approval event exists in ``gate_events`` (Sentinel 6035083658 HIGH-Y).

Probe: a staged gate-state with a plan-wide ``pre_merge`` clearance and a
hand-written ``completed_stage_features["pre_merge"] = ["F001"]`` but NO
approval event. Base fcee35d trusts the plan-wide clearance; a1c93a3 trusts the
per-feature entry. Both let F001 sign off and finalize without a human stop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dontpanic_orchestrate import gate_pause, signed_off_finalizer, supervisor
from dontpanic_orchestrate.tests import test_dp003_signoff_integrity as _dp3
from dontpanic_orchestrate.tests.test_dp003_signoff_integrity import (
    _r10_passes,
    _r10_plan,
    _r10_volley,
)

repo = _dp3.repo
captured = _dp3.captured


def _write_state(plan_dir: Path, state: dict) -> None:
    path = gate_pause.gate_state_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")


def _state(plan_dir: Path) -> dict:
    return json.loads(gate_pause.gate_state_path(plan_dir).read_text())


def _hand_written_completion(plan_id: str) -> dict:
    """Staged schema, plan-wide pre_merge clearance, F001 listed as completed,
    no gate_events at all."""
    return {
        "plan_id": plan_id,
        "cleared_gates": ["pre_merge"],
        "completed_stages": ["pre_merge"],
        "completed_stage_features": {"pre_merge": ["F001"]},
        "history": [],
    }


def test_hand_written_completion_without_event_pauses_dispatch(
    repo: Path, captured: list[Any]
) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _write_state(plan_dir, _hand_written_completion(plan_id))
    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert result.final_status == "paused_on_gate", result
    assert _r10_passes(plan_dir, "F001") is False


def test_hand_written_completion_without_event_finalize_refuses(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _r10_volley(plan_dir, plan_id, "F001")
    _write_state(plan_dir, _hand_written_completion(plan_id))
    with pytest.raises(signed_off_finalizer.FinalizeError) as exc:
        signed_off_finalizer.finalize_signed_off_feature(
            plan_dir, plan_id=plan_id, feature_id="F001"
        )
    assert exc.value.code == "pre_merge_uncleared"
    assert _r10_passes(plan_dir, "F001") is False


def test_event_for_another_feature_does_not_back_the_entry(tmp_path: Path) -> None:
    state = _hand_written_completion("p")
    state["gate_events"] = [
        {"gate": "pre_merge", "stage": "pre_merge", "cleared_at": "x",
         "cleared_by": "operator", "feature_id": "F002"},
        # feature-less (old-style) event backs nothing either
        {"gate": "pre_merge", "stage": "pre_merge", "cleared_at": "x", "cleared_by": "operator"},
    ]
    _write_state(tmp_path, state)
    assert not gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F001")
    binding = gate_pause.approval_binding(tmp_path, "F001")  # also bound (r3 part 3)
    state["gate_events"].append(
        {"gate": "pre_merge", "stage": "pre_merge", "cleared_at": "x",
         "cleared_by": "operator", "feature_id": "F001", **binding}
    )
    state["completed_stage_bindings"] = {"pre_merge": {"F001": binding}}
    _write_state(tmp_path, state)
    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F001")


def test_legit_approve_records_feature_event_and_finalizes(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _r10_volley(plan_dir, plan_id, "F001")
    gate_pause.record_pause(
        plan_dir, plan_id=plan_id, pause_gates=["pre_merge"], stage="pre_merge", feature_id="F001"
    )
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id, feature_id="F001")
    event = _state(plan_dir)["gate_events"][-1]
    assert (event["gate"], event["stage"], event["feature_id"]) == ("pre_merge", "pre_merge", "F001")
    assert gate_pause.is_stage_completed(plan_dir, "pre_merge", feature_id="F001")
    out = signed_off_finalizer.finalize_signed_off_feature(
        plan_dir, plan_id=plan_id, feature_id="F001"
    )
    assert out.features_passes_flipped is True


def test_resume_all_single_pending_binds_its_event_to_the_feature(tmp_path: Path) -> None:
    gate_pause.record_pause(
        tmp_path, plan_id="p", pause_gates=["pre_merge"], stage="pre_merge", feature_id="F001"
    )
    gate_pause.resume_all(tmp_path, plan_id="p", declared_gates=["pre_merge"])
    assert _state(tmp_path)["gate_events"][-1]["feature_id"] == "F001"
    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F001")


def test_legacy_migration_records_its_own_event_per_feature(
    repo: Path, captured: list[Any]
) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _write_state(
        plan_dir,
        {"plan_id": plan_id, "cleared_gates": {"pre_merge": True}, "history": [{"action": "legacy_clear"}]},
    )
    for fid in ("F001", "F002"):
        assert supervisor.dispatch_volley(plan_dir, fid, max_iterations=1).final_status == "signed_off"
    events = [
        (e.get("cleared_by"), e.get("feature_id"))
        for e in _state(plan_dir)["gate_events"]
        if e.get("stage") == "pre_merge"
    ]
    assert events == [
        (gate_pause.LEGACY_MIGRATION_ACTOR, "F001"),
        (gate_pause.LEGACY_MIGRATION_ACTOR, "F002"),
    ]
    for fid in ("F001", "F002"):
        out = signed_off_finalizer.finalize_signed_off_feature(
            plan_dir, plan_id=plan_id, feature_id=fid
        )
        assert out.features_passes_flipped is True
