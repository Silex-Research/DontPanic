"""``what-now`` guidance for ``pre_merge`` reads the per-feature state and its
approve command always names the feature (Sentinel 6035083658 LOW, Thanos
ruling item ``operations_guidance``).

Before: guidance read the plan-wide ``is_gate_cleared(pre_merge)`` and offered
``dontpanic approve <plan> pre_merge`` with no ``--feature`` — refused by the
CLI when two features are paused, and a plan-wide clearance offered a finalize
the finalizer then refuses.
"""

from __future__ import annotations

import json
import shlex

from dontpanic_orchestrate import command_validation, gate_pause
from dontpanic_orchestrate import operations_guidance as og
from dontpanic_orchestrate.tests.test_operations_guidance_f007 import (
    COLLECT_PLAN_ID,
    _by_kind,
    _kinds,
    _make_plan,
)


def _pause(plan_dir, fid: str) -> None:
    gate_pause.record_pause(
        plan_dir,
        plan_id=COLLECT_PLAN_ID,
        pause_gates=["pre_merge"],
        stage="pre_merge",
        feature_id=fid,
    )


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    plan_dir = _make_plan(tmp_path)  # F001 signed_off
    assert gate_pause.approve_gate(plan_dir, "pre_impl", plan_id=COLLECT_PLAN_ID)
    return plan_dir


def test_approve_command_names_the_pending_feature_and_validates(tmp_path, monkeypatch):
    plan_dir = _setup(tmp_path, monkeypatch)
    _pause(plan_dir, "F001")
    _pause(plan_dir, "F002")
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    approve = _by_kind(g, og.KIND_APPROVE_GATE)
    assert approve.exact_command == f"dontpanic approve {COLLECT_PLAN_ID} pre_merge --feature F001"
    tokens = shlex.split(approve.exact_command)[1:]
    assert command_validation.validate_command_tokens(tokens).ok
    # The command it emits is the one the CLI accepts for this state.
    assert gate_pause.approval_refusal(plan_dir, "pre_merge", "F001") is None
    assert gate_pause.approval_refusal(plan_dir, "pre_merge", None) is not None


def test_plan_wide_clearance_is_not_per_feature_cleared(tmp_path, monkeypatch):
    """A staged plan-wide ``pre_merge`` entry with no per-feature approval is
    NOT cleared for F001: no finalize offered (the finalizer would refuse)."""
    plan_dir = _setup(tmp_path, monkeypatch)
    path = gate_pause.gate_state_path(plan_dir)
    state = json.loads(path.read_text())
    state["cleared_gates"] = sorted(set(state.get("cleared_gates") or []) | {"pre_merge"})
    path.write_text(json.dumps(state))
    assert gate_pause.is_gate_cleared(plan_dir, "pre_merge")
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    assert og.KIND_FINALIZE not in _kinds(g)


def test_other_features_approval_does_not_clear_this_one(tmp_path, monkeypatch):
    plan_dir = _setup(tmp_path, monkeypatch)
    _pause(plan_dir, "F001")
    _pause(plan_dir, "F002")
    assert gate_pause.approve_gate(
        plan_dir, "pre_merge", plan_id=COLLECT_PLAN_ID, feature_id="F002"
    )
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    assert og.KIND_FINALIZE not in _kinds(g)
    approve = _by_kind(g, og.KIND_APPROVE_GATE)
    assert approve.exact_command.endswith("pre_merge --feature F001")
    # Once F001's own approval is recorded, finalize is offered.
    assert gate_pause.approve_gate(
        plan_dir, "pre_merge", plan_id=COLLECT_PLAN_ID, feature_id="F001"
    )
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    assert og.KIND_FINALIZE in _kinds(g)
