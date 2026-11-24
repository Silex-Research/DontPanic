"""One ``pre_merge`` approval credits exactly one feature (Sentinel r2 HIGH 1),
the per-feature authority is visible to drift detection (HIGH 2), and the
D004/D009 legacy-resume contract still holds for truly-legacy gate-state.

Sentinel's probe at f2ba0d70: F001 and F002 both paused at ``pre_merge``; one
unnamed ``approve pre_merge`` credited F002 (the last pause) and the finalizer
then flipped BOTH features through the plan-wide ``is_gate_cleared`` bit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dontpanic_orchestrate import cli, gate_pause, plan_drift, signed_off_finalizer, supervisor
from dontpanic_orchestrate.executors import AGENT_REGISTRY
from dontpanic_orchestrate.tests import test_dp003_signoff_integrity as _dp3
from dontpanic_orchestrate.tests.test_dp003_signoff_integrity import (
    _r10_passes,
    _r10_plan,
    _r10_volley,
    _ScriptedExecutor,
)

# Shared fixtures from the DP-003 suite (deterministic executors, temp repo).
repo = _dp3.repo
captured = _dp3.captured


def _pause(plan_dir: Path, plan_id: str, fid: str) -> None:
    gate_pause.record_pause(
        plan_dir, plan_id=plan_id, pause_gates=["pre_merge"], stage="pre_merge", feature_id=fid
    )


def _finalize(plan_dir: Path, plan_id: str, fid: str) -> Any:
    return signed_off_finalizer.finalize_signed_off_feature(
        plan_dir, plan_id=plan_id, feature_id=fid
    )


def _refused_code(plan_dir: Path, plan_id: str, fid: str) -> str:
    with pytest.raises(signed_off_finalizer.FinalizeError) as exc:
        _finalize(plan_dir, plan_id, fid)
    return exc.value.code


def _state(plan_dir: Path) -> dict:
    return json.loads(gate_pause.gate_state_path(plan_dir).read_text())


def _write_state(plan_dir: Path, state: dict) -> None:
    path = gate_pause.gate_state_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")


def _two_signed_off(repo: Path) -> tuple[Path, str]:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _r10_volley(plan_dir, plan_id, "F001", offset=0)
    _r10_volley(plan_dir, plan_id, "F002", offset=10)
    return plan_dir, plan_id


# ─────────────────────────── HIGH 1: one approval, one feature ───────────────


def test_sentinel_probe_one_approval_never_finalizes_two_features(repo: Path) -> None:
    plan_dir, plan_id = _two_signed_off(repo)
    _pause(plan_dir, plan_id, "F001")
    _pause(plan_dir, plan_id, "F002")
    assert gate_pause.pending_features(plan_dir) == ["F001", "F002"]

    # A single unnamed approval is ambiguous: refused, nothing written.
    before = gate_pause.gate_state_path(plan_dir).read_bytes()
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id) is False
    assert gate_pause.gate_state_path(plan_dir).read_bytes() == before

    # A named approval credits F001 only.
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id, feature_id="F001")
    assert gate_pause.is_stage_completed(plan_dir, "pre_merge", feature_id="F001")
    assert not gate_pause.is_stage_completed(plan_dir, "pre_merge", feature_id="F002")
    # The stage stays pending for F002; no plan-wide clearance was written.
    state = _state(plan_dir)
    assert state["pending_stage"] == "pre_merge"
    assert gate_pause.pending_features(plan_dir) == ["F002"]
    assert "pre_merge" not in state["cleared_gates"]
    assert gate_pause.is_gate_currently_pending(plan_dir, "pre_merge")
    assert state["gate_events"][-1]["feature_id"] == "F001"

    assert _refused_code(plan_dir, plan_id, "F002") == "pre_merge_uncleared"
    assert _r10_passes(plan_dir, "F002") is False
    assert _finalize(plan_dir, plan_id, "F001").features_passes_flipped is True
    assert _r10_passes(plan_dir, "F002") is False

    # F002 is now the only pending feature: an unnamed approval credits it.
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id)
    assert gate_pause.pending_features(plan_dir) == []
    assert gate_pause.pending_stage(plan_dir) is None
    assert _finalize(plan_dir, plan_id, "F002").features_passes_flipped is True


def test_named_feature_not_pending_is_refused_and_writes_nothing(repo: Path) -> None:
    plan_dir, plan_id = _two_signed_off(repo)
    _pause(plan_dir, plan_id, "F001")
    before = gate_pause.gate_state_path(plan_dir).read_bytes()
    assert gate_pause.approval_refusal(plan_dir, "pre_merge", "F002")
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id, feature_id="F002") is False
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id, feature_id="F999") is False
    assert gate_pause.gate_state_path(plan_dir).read_bytes() == before
    assert not gate_pause.is_stage_completed(plan_dir, "pre_merge", feature_id="F002")
    # Re-approving an already-credited feature is refused too (no longer pending).
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id, feature_id="F001")
    after = gate_pause.gate_state_path(plan_dir).read_bytes()
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id, feature_id="F001") is False
    assert gate_pause.gate_state_path(plan_dir).read_bytes() == after


def test_two_paused_plus_plan_wide_clearance_finalizes_neither(repo: Path) -> None:
    """Two failing together: two pending features AND a staged plan-wide
    pre_merge clearance in cleared_gates/completed_stages."""
    plan_dir, plan_id = _two_signed_off(repo)
    _pause(plan_dir, plan_id, "F001")
    _pause(plan_dir, plan_id, "F002")
    state = _state(plan_dir)
    state["cleared_gates"] = ["pre_merge"]
    state["completed_stages"] = ["pre_merge"]
    _write_state(plan_dir, state)
    assert gate_pause.is_gate_cleared(plan_dir, "pre_merge")
    for fid in ("F001", "F002"):
        assert _refused_code(plan_dir, plan_id, fid) == "pre_merge_uncleared"
        assert _r10_passes(plan_dir, fid) is False


def test_resume_all_with_two_pending_features_credits_neither(tmp_path: Path) -> None:
    _pause(tmp_path, "p", "F001")
    _pause(tmp_path, "p", "F002")
    assert gate_pause.resume_all(tmp_path, plan_id="p", declared_gates=["pre_merge"]) == []
    assert not gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F001")
    assert not gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F002")
    assert gate_pause.pending_features(tmp_path) == ["F001", "F002"]


def test_old_single_slot_pending_feature_is_still_read(tmp_path: Path) -> None:
    """Gate-state written by the r1 code (single ``pending_feature_id`` slot)."""
    _write_state(
        tmp_path,
        {
            "plan_id": "p",
            "cleared_gates": [],
            "gate_events": [],
            "pause_gates": ["pre_merge"],
            "pending_stage": "pre_merge",
            "pending_feature_id": "F001",
            "history": [],
        },
    )
    assert gate_pause.pending_features(tmp_path) == ["F001"]
    assert gate_pause.approve_gate(tmp_path, "pre_merge", plan_id="p", feature_id="F002") is False
    assert gate_pause.approve_gate(tmp_path, "pre_merge", plan_id="p")
    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F001")
    assert "pending_feature_id" not in _state(tmp_path)


def test_cli_approve_requires_feature_when_two_pending(repo: Path, capsys) -> None:
    plan_dir, plan_id = _two_signed_off(repo)
    _pause(plan_dir, plan_id, "F001")
    _pause(plan_dir, plan_id, "F002")
    before = gate_pause.gate_state_path(plan_dir).read_bytes()
    assert cli._approve_main([str(plan_dir), "pre_merge"]) == 2
    assert "--feature" in capsys.readouterr().err
    assert cli._approve_main([str(plan_dir), "pre_merge", "--feature", "F003"]) == 2
    assert gate_pause.gate_state_path(plan_dir).read_bytes() == before
    assert cli._approve_main([str(plan_dir), "pre_merge", "--feature", "F002"]) == 0
    assert gate_pause.is_stage_completed(plan_dir, "pre_merge", feature_id="F002")
    assert not gate_pause.is_stage_completed(plan_dir, "pre_merge", feature_id="F001")
    assert cli._resume_main([str(plan_dir), "--gate", "pre_merge", "--feature", "F002"]) == 2
    assert cli._resume_main([str(plan_dir), "--gate", "pre_merge", "--feature", "F001"]) == 0
    assert gate_pause.is_stage_completed(plan_dir, "pre_merge", feature_id="F001")


def test_mcp_approve_refuses_ambiguous_and_credits_named(repo: Path) -> None:
    from dontpanic_orchestrate import mcp_server

    plan_dir, plan_id = _two_signed_off(repo)
    _pause(plan_dir, plan_id, "F001")
    _pause(plan_dir, plan_id, "F002")
    dry = mcp_server.tool_approve_gate({"plan": str(plan_dir), "gate": "pre_merge"})
    assert dry["intent"]["would_clear"] is False and "refused" in dry["intent"]
    out = mcp_server.tool_approve_gate({"plan": str(plan_dir), "gate": "pre_merge", "confirm": True})
    assert out["result"]["changed"] is False
    out = mcp_server.tool_approve_gate(
        {"plan": str(plan_dir), "gate": "pre_merge", "confirm": True, "feature_id": "F001"}
    )
    assert out["result"]["changed"] is True
    assert gate_pause.pending_features(plan_dir) == ["F002"]


# ───────────────────── D004/D009 legacy-resume contract ──────────────────────


def _legacy_two_feature_plan(repo: Path) -> tuple[Path, str]:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    # Truly legacy: written before staged gates (legacy dict cleared_gates; no
    # gate_events / completed_stages / pending_stage / completed_stage_features).
    _write_state(
        plan_dir,
        {"plan_id": plan_id, "cleared_gates": {"pre_merge": True}, "history": [{"action": "legacy_clear"}]},
    )
    return plan_dir, plan_id


def test_guard_legacy_upfront_clearance_signs_off_and_finalizes_both_features(
    repo: Path, captured: list[Any]
) -> None:
    """GUARD (passes on base by design): D004/D009 legacy upfront plans resume."""
    plan_dir, plan_id = _legacy_two_feature_plan(repo)
    for fid in ("F001", "F002"):
        result = supervisor.dispatch_volley(plan_dir, fid, max_iterations=1)
        assert result.final_status == "signed_off", (fid, result)
    for fid in ("F001", "F002"):
        assert _finalize(plan_dir, plan_id, fid).features_passes_flipped is True


def test_legacy_migration_records_each_feature_and_marker(repo: Path, captured: list[Any]) -> None:
    plan_dir, plan_id = _legacy_two_feature_plan(repo)
    assert supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1).final_status == "signed_off"
    state = _state(plan_dir)
    assert state["completed_stage_features"] == {"pre_merge": ["F001"]}
    assert state[gate_pause.LEGACY_UPFRONT_PRE_MERGE] is True
    # The migration converted the file to the staged schema; F002 of the same
    # legacy plan is still honored through the marker.
    assert supervisor.dispatch_volley(plan_dir, "F002", max_iterations=1).final_status == "signed_off"
    assert _state(plan_dir)["completed_stage_features"] == {"pre_merge": ["F001", "F002"]}


def test_staged_plan_wide_pre_merge_clearance_does_not_authorize_f002(
    repo: Path, captured: list[Any]
) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _write_state(
        plan_dir,
        {
            "plan_id": plan_id,
            "cleared_gates": ["pre_merge"],
            "completed_stages": ["pre_merge"],
            "gate_events": [
                {"gate": "pre_merge", "stage": "pre_merge", "cleared_at": "x", "cleared_by": "operator"}
            ],
            "history": [],
        },
    )
    result = supervisor.dispatch_volley(plan_dir, "F002", max_iterations=1)
    assert result.final_status == "paused_on_gate", result
    assert gate_pause.pending_features(plan_dir) == ["F002"]
    assert _refused_code(plan_dir, plan_id, "F002") == "pre_merge_uncleared"
    assert gate_pause.LEGACY_UPFRONT_PRE_MERGE not in _state(plan_dir)


def test_record_legacy_migration_never_marks_a_staged_file(tmp_path: Path) -> None:
    _write_state(
        tmp_path,
        {"plan_id": "p", "cleared_gates": ["pre_merge"], "completed_stages": ["pre_merge"]},
    )
    before = gate_pause.gate_state_path(tmp_path).read_bytes()
    assert gate_pause.record_legacy_upfront_pre_merge(tmp_path, plan_id="p", feature_id="F001") is False
    assert gate_pause.gate_state_path(tmp_path).read_bytes() == before


# ─────────────────── HIGH 2: per-feature authority is drift-visible ──────────


def test_sentinel_probe_s2_completed_stage_features_edit_is_gate_drift(tmp_path: Path) -> None:
    _pause(tmp_path, "p", "F001")
    _pause(tmp_path, "p", "F002")
    gate_pause.approve_gate(tmp_path, "pre_merge", plan_id="p", feature_id="F001")
    text = gate_pause.gate_state_path(tmp_path).read_text()
    before = plan_drift._gate_semantics(text)
    st = json.loads(text)
    st.setdefault("completed_stage_features", {}).setdefault("pre_merge", []).append("F003")
    assert plan_drift._gate_semantics(json.dumps(st)) != before
    # Contrast (base behaviour kept): a cleared_gates edit is drift too.
    st2 = json.loads(text)
    st2["cleared_gates"] = list(st2["cleared_gates"]) + ["pre_impl"]
    assert plan_drift._gate_semantics(json.dumps(st2)) != before
    # Order-only differences are not drift.
    st3 = json.loads(text)
    st3["completed_stage_features"]["pre_merge"] = list(
        reversed(st3["completed_stage_features"]["pre_merge"])
    )
    assert plan_drift._gate_semantics(json.dumps(st3)) == before


def test_hand_added_legacy_marker_is_gate_drift(tmp_path: Path) -> None:
    _pause(tmp_path, "p", "F001")
    text = gate_pause.gate_state_path(tmp_path).read_text()
    st = json.loads(text)
    st[gate_pause.LEGACY_UPFRONT_PRE_MERGE] = True
    assert plan_drift._gate_semantics(json.dumps(st)) != plan_drift._gate_semantics(text)


@pytest.mark.parametrize(
    "tamper",
    ["completed_stage_features", "legacy_marker", "cleared_gates"],
)
def test_mid_run_gate_tamper_pauses_on_drift_and_finalize_refuses(
    repo: Path, captured: list[Any], monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    """A hand edit made while the auditor runs (F002 paused + staged state) is
    caught at the signoff boundary; no success signoff, and the no-paid
    finalize refuses on drift (exit 6) instead of honoring the edit."""
    plan_dir, plan_id = _r10_plan(repo, child=False)

    class _TamperingAuditor(_ScriptedExecutor):
        def dispatch(self, task):  # type: ignore[override]
            st = _state(plan_dir)
            if tamper == "completed_stage_features":
                st.setdefault("completed_stage_features", {}).setdefault("pre_merge", []).append("F002")
            elif tamper == "legacy_marker":
                st[gate_pause.LEGACY_UPFRONT_PRE_MERGE] = True
            else:
                st["cleared_gates"] = list(st.get("cleared_gates") or []) + ["pre_merge"]
            _write_state(plan_dir, st)
            return super().dispatch(task)

    monkeypatch.setitem(AGENT_REGISTRY, "codex", lambda: _TamperingAuditor("codex"))
    _write_state(plan_dir, {"plan_id": plan_id, "cleared_gates": [], "gate_events": [], "history": []})

    result = supervisor.dispatch_volley(plan_dir, "F002", max_iterations=1)

    assert result.final_status in ("paused_on_drift", "paused_on_gate"), result
    assert _r10_passes(plan_dir, "F002") is False
    if tamper == "legacy_marker":
        # The edit grants F002 authority on its face, so only drift stops it.
        # (A bare completed_stage_features entry no longer does: it has no
        # matching approval event, so the gate itself stays pending — HIGH-Y.)
        assert result.final_status == "paused_on_drift", result
    rc = cli._finalize_main([str(plan_dir), "--feature", "F002"])
    assert rc != 0
    assert _r10_passes(plan_dir, "F002") is False
