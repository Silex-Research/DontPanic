"""F1 (Sentinel review 6048538810): ``completed_stage_bindings`` is written only
by the staged gate code, so a gate-state carrying it is in the staged schema.
A file with ``cleared_gates: ["pre_merge"]`` plus only a (bad) binding must
NOT be classed as truly legacy and must get no plan-wide pre_merge authority.
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import gate_pause

_BAD_BINDING = {"pre_merge": {"F002": {"plan_id": "other", "feature_revision": "0" * 64}}}


def _write_state(plan_dir: Path, state: dict) -> None:
    path = gate_pause.gate_state_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def test_bindings_only_state_has_no_plan_wide_pre_merge_authority(tmp_path: Path) -> None:
    _write_state(
        tmp_path,
        {
            "plan_id": "p",
            "cleared_gates": ["pre_merge"],
            "completed_stage_bindings": _BAD_BINDING,
            "history": [],
        },
    )
    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F002") is False
    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F001") is False


def test_bindings_only_state_is_never_migrated_as_legacy(tmp_path: Path) -> None:
    _write_state(
        tmp_path,
        {"plan_id": "p", "cleared_gates": ["pre_merge"], "completed_stage_bindings": _BAD_BINDING},
    )
    before = gate_pause.gate_state_path(tmp_path).read_bytes()
    assert gate_pause.record_legacy_upfront_pre_merge(tmp_path, plan_id="p", feature_id="F002") is False
    assert gate_pause.gate_state_path(tmp_path).read_bytes() == before


def test_guard_plain_legacy_state_keeps_plan_wide_authority(tmp_path: Path) -> None:
    """GUARD (D004/D009): a truly-legacy upfront clearance still authorizes."""
    _write_state(tmp_path, {"plan_id": "p", "cleared_gates": ["pre_merge"], "history": []})
    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F002") is True
