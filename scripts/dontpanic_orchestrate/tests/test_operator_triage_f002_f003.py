"""F002 (dedupe by dedupe_key) + F003 (gate reconciliation vs plan status),
verified against the real 313-item fleet fixture and synthetic gate items.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import operator_triage as ot

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "docs/plans/2026-06-06-001-feat-operator-triage-surface-v0"
    / "evidence/fleet-fixture-real.json"
)


@pytest.fixture(scope="module")
def real_items() -> list[dict]:
    return json.loads(_FIXTURE.read_text())["items"]


# --- F002 dedupe ----------------------------------------------------------

def test_dedupe_collapses_duplicated_real_approvals(real_items):
    approvals = [it for it in real_items if "approval needed" in str(it.get("title") or "").lower()]
    assert len(approvals) > 1, "fixture should contain the duplicated approval items"
    deduped = ot.dedupe_items(approvals)
    # the 6-8x duplicated approvals collapse to fewer unique representatives...
    assert len(deduped) < len(approvals)
    # ...and the collapse is accounted for, not silently dropped
    assert sum(r["duplicate_count"] for r in deduped) == len(approvals)
    # one representative per unique dedupe_key
    assert len(deduped) == len({str(it["dedupe_key"]) for it in approvals})


def test_dedupe_passes_through_unkeyed_items():
    items = [{"id": "a"}, {"id": "b", "dedupe_key": "k"}, {"id": "c", "dedupe_key": "k"}]
    out = ot.dedupe_items(items)
    keyed = [o for o in out if o.get("dedupe_key") == "k"]
    assert len(keyed) == 1 and keyed[0]["duplicate_count"] == 2
    assert any(o["id"] == "a" for o in out)  # unkeyed survives


def test_dedupe_is_deterministic(real_items):
    assert ot.dedupe_items(real_items) == ot.dedupe_items(real_items)


def test_build_triage_dedupe_reduces_needs_decision(real_items):
    raw = ot.build_triage(real_items, safety_class_for=lambda it: None, live_supervisors=[])
    dd = ot.build_triage(real_items, safety_class_for=lambda it: None, live_supervisors=[], dedupe=True)
    raw_nd = raw["data_quality"]["counts"].get("needs_decision", 0)
    dd_nd = dd["data_quality"]["counts"].get("needs_decision", 0)
    assert dd_nd < raw_nd, f"dedupe should shrink needs_decision ({raw_nd} -> {dd_nd})"


# --- F003 gate reconciliation --------------------------------------------

def test_is_stale_gate_predicate():
    assert ot.is_stale_gate(plan_status="completed", all_features_pass=False) is True
    assert ot.is_stale_gate(plan_status="abandoned", all_features_pass=False) is True
    assert ot.is_stale_gate(plan_status="active", all_features_pass=True) is True
    assert ot.is_stale_gate(plan_status="active", all_features_pass=False) is False


def test_stale_gate_leaves_needs_decision_live_gate_stays():
    gate = {"id": "gate:p1:pre_merge", "band": "needs_action",
            "resolution_class": "command_resolvable", "title": "Approval needed on p1",
            "clears_when": {"params": {"plan_id": "p1"}}}
    # live plan -> needs_decision
    assert ot.classify(gate, gate_live=True, plan_status="active", safety_class=None) == ot.OperatorBucket.NEEDS_DECISION
    # stale (completed) -> reconciled out of needs_decision (quiet)
    stale_live = not ot.is_stale_gate(plan_status="completed", all_features_pass=False)
    assert ot.classify(gate, gate_live=stale_live, plan_status="completed", safety_class=None) == ot.OperatorBucket.QUIET


def test_build_triage_reconciles_stale_gates_out_of_needs_decision(real_items):
    # mark every gate's plan completed -> no needs_decision should survive
    live_all = ot.build_triage(real_items, safety_class_for=lambda it: None, live_supervisors=[])
    reconciled = ot.build_triage(
        real_items, safety_class_for=lambda it: None, live_supervisors=[],
        gate_live_for=lambda it: not ot.is_stale_gate(plan_status="completed", all_features_pass=False),
    )
    assert live_all["data_quality"]["counts"].get("needs_decision", 0) > 0
    assert reconciled["data_quality"]["counts"].get("needs_decision", 0) == 0
