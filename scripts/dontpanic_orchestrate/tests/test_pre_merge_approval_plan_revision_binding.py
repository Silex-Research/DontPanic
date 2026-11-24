"""A per-feature ``pre_merge`` approval is bound to the plan and to the
feature's revision (Thanos ruling on Sentinel 6035083658 HIGH-Y).

Both the ``completed_stage_features`` entry (via ``completed_stage_bindings``)
and its approval event carry ``plan_id`` (the plan's ``features.json``
``task_id``) and ``feature_revision`` (sha256 of the canonical JSON of the
feature's ``features.json`` record, without the finalizer's outcome fields).
A completion counts only when both match the current plan and revision:

  (a) a gate-state copied from another plan loses authority;
  (b) an approved feature whose record is edited afterwards loses authority
      (the stop re-arms and finalize refuses).

The probe states are hand-built exactly as a legit approval writes them, with
a plan-wide ``pre_merge`` clearance: base fcee35d honors that clearance and
a1c93a3 honors the bare entry, so both sign off / finalize (red).
"""

from __future__ import annotations

import hashlib
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

_OUTCOME_FIELDS = {"passes", "evidence_refs", "verified_by", "verified_at"}


def _features(plan_dir: Path) -> dict:
    return json.loads((plan_dir / "features.json").read_text())


def _binding(plan_dir: Path, fid: str, *, plan_id: str | None = None) -> dict:
    """The documented binding, computed independently of gate_pause."""
    data = _features(plan_dir)
    record = next(f for f in data["features"] if f["id"] == fid)
    canonical = json.dumps(
        {k: v for k, v in record.items() if k not in _OUTCOME_FIELDS},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return {
        "plan_id": plan_id if plan_id is not None else data["task_id"],
        "feature_revision": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _approved_state(state_plan_id: str, fid: str, binding: dict) -> dict:
    """What a legit per-feature approval of ``fid`` leaves behind (single
    pending feature, so the plan-wide entry is cleared too)."""
    return {
        "plan_id": state_plan_id,
        "cleared_gates": ["pre_merge"],
        "completed_stages": ["pre_merge"],
        "completed_stage_features": {"pre_merge": [fid]},
        "completed_stage_bindings": {"pre_merge": {fid: binding}},
        "gate_events": [
            {
                "gate": "pre_merge",
                "stage": "pre_merge",
                "cleared_at": "2026-11-24T00:00:00Z",
                "cleared_by": "operator",
                "feature_id": fid,
                **binding,
            }
        ],
        "history": [],
    }


def _write_state(plan_dir: Path, state: dict) -> None:
    path = gate_pause.gate_state_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")


def _edit_f001(plan_dir: Path) -> None:
    data = _features(plan_dir)
    for f in data["features"]:
        if f["id"] == "F001":
            f["description"] = str(f.get("description", "")) + " (edited after approval)"
    (plan_dir / "features.json").write_text(json.dumps(data, indent=2) + "\n")


def _finalize_code(plan_dir: Path, plan_id: str, fid: str) -> str:
    with pytest.raises(signed_off_finalizer.FinalizeError) as exc:
        signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id=fid)
    return exc.value.code


# ── (a) copied from another plan ────────────────────────────────────────────


def test_state_copied_from_another_plan_pauses_dispatch(repo: Path, captured: list[Any]) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    other = _binding(plan_dir, "F001", plan_id="2026-01-01-999-other-plan")
    _write_state(plan_dir, _approved_state(plan_id, "F001", other))
    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert result.final_status == "paused_on_gate", result
    assert _r10_passes(plan_dir, "F001") is False


def test_state_copied_from_another_plan_finalize_refuses(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _r10_volley(plan_dir, plan_id, "F001")
    other = _binding(plan_dir, "F001", plan_id="2026-01-01-999-other-plan")
    _write_state(plan_dir, _approved_state(plan_id, "F001", other))
    assert _finalize_code(plan_dir, plan_id, "F001") == "pre_merge_uncleared"
    assert _r10_passes(plan_dir, "F001") is False


# ── (b) feature record edited after approval ────────────────────────────────


def test_record_edited_after_approval_rearms_the_stop(repo: Path, captured: list[Any]) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _write_state(plan_dir, _approved_state(plan_id, "F001", _binding(plan_dir, "F001")))
    _edit_f001(plan_dir)
    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert result.final_status == "paused_on_gate", result
    assert gate_pause.pending_features(plan_dir) == ["F001"]
    assert _r10_passes(plan_dir, "F001") is False


def test_record_edited_after_approval_finalize_refuses(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _r10_volley(plan_dir, plan_id, "F001")
    _write_state(plan_dir, _approved_state(plan_id, "F001", _binding(plan_dir, "F001")))
    _edit_f001(plan_dir)
    assert _finalize_code(plan_dir, plan_id, "F001") == "pre_merge_uncleared"
    assert _r10_passes(plan_dir, "F001") is False


def test_matching_binding_is_honored(repo: Path) -> None:
    """Control for (a)/(b): the same hand-built shape bound to THIS plan and
    the current revision is honored, so (a)/(b) fail on the binding alone."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _write_state(plan_dir, _approved_state(plan_id, "F001", _binding(plan_dir, "F001")))
    assert gate_pause.is_stage_completed(plan_dir, "pre_merge", feature_id="F001")
    assert gate_pause.approval_binding(plan_dir, "F001") == _binding(plan_dir, "F001")


# ── legit flow ──────────────────────────────────────────────────────────────


def test_legit_approve_dispatch_finalize_still_works(repo: Path, captured: list[Any]) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    assert supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1).final_status == "paused_on_gate"
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id, feature_id="F001")
    state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
    expected = _binding(plan_dir, "F001")
    assert state["completed_stage_bindings"]["pre_merge"]["F001"] == expected
    event = state["gate_events"][-1]
    assert {k: event.get(k) for k in ("feature_id", "plan_id", "feature_revision")} == {
        "feature_id": "F001",
        **expected,
    }
    assert supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1).final_status == "signed_off"
    out = signed_off_finalizer.finalize_signed_off_feature(
        plan_dir, plan_id=plan_id, feature_id="F001"
    )
    assert out.features_passes_flipped is True
    # The finalizer's own outcome fields (passes, evidence) do not void it.
    assert gate_pause.is_stage_completed(plan_dir, "pre_merge", feature_id="F001")


@pytest.mark.parametrize("stale", ["entry", "event"])
def test_both_entry_and_event_must_carry_the_current_binding(repo: Path, stale: str) -> None:
    """Re-binding only one half of a copied approval does not restore it."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    current = _binding(plan_dir, "F001")
    other = _binding(plan_dir, "F001", plan_id="2026-01-01-999-other-plan")
    state = _approved_state(plan_id, "F001", current)
    if stale == "entry":
        state["completed_stage_bindings"]["pre_merge"]["F001"] = other
    else:
        state["gate_events"][0].update(other)
    _write_state(plan_dir, state)
    assert not gate_pause.is_stage_completed(plan_dir, "pre_merge", feature_id="F001")
