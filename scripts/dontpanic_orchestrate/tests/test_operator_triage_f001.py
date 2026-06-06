"""F001 — operator triage model: pure/total operator_bucket classifier + derived
concurrency/scope metadata + canonical serialization + data_quality envelope.

Verified against the REAL 313-item fleet fixture captured in the plan evidence dir
(docs/plans/2026-06-06-001-.../evidence/fleet-fixture-real.json), plus synthetic
items for the uncertain fail-closed default and the conflicted run_state.
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


def _no_safety(_item: dict) -> str | None:
    return None  # producers don't assert safety_class yet (the real state)


def test_classify_is_total_over_real_fleet(real_items):
    valid = {b for b in ot.OperatorBucket}
    for it in real_items:
        b = ot.classify(it, gate_live=True, plan_status="active", safety_class=None)
        assert b in valid, f"{it.get('id')} -> {b!r}"


def test_classify_is_deterministic(real_items):
    a = [ot.classify(it, gate_live=True, plan_status="active", safety_class=None) for it in real_items]
    b = [ot.classify(it, gate_live=True, plan_status="active", safety_class=None) for it in real_items]
    assert a == b


def test_operator_attested_is_needs_auth(real_items):
    attested = [it for it in real_items if it.get("resolution_class") == "operator_attested"]
    assert attested, "fixture should contain operator_attested capability items"
    for it in attested:
        assert ot.classify(it, gate_live=True, plan_status="active", safety_class=None) == ot.OperatorBucket.NEEDS_AUTH


def test_info_and_advisory_are_quiet(real_items):
    for it in real_items:
        if it.get("band") in ("info", "advisory"):
            assert ot.classify(it, gate_live=True, plan_status="active", safety_class=None) == ot.OperatorBucket.QUIET


def test_malformed_item_is_uncertain_fail_closed():
    # band is an action band but resolution_class is missing/unknown -> cannot
    # classify confidently -> uncertain (surfaced, never silently dropped).
    item = {"id": "weird:1", "band": "needs_action", "resolution_class": None}
    assert ot.classify(item, gate_live=True, plan_status="active", safety_class=None) == ot.OperatorBucket.UNCERTAIN


def test_auto_safe_requires_asserted_safety_class():
    item = {"id": "arch:stale", "band": "needs_action", "resolution_class": "command_resolvable",
            "automatable": True, "audience": ["operator"]}
    # automatable but no safety assertion -> NOT auto_safe (an agent/human runs it)
    assert ot.classify(item, gate_live=True, plan_status="active", safety_class=None) == ot.OperatorBucket.AGENT_RUNNABLE
    # only with an asserted auto_safe safety_class does DontPanic claim it as auto_safe
    assert ot.classify(item, gate_live=True, plan_status="active", safety_class="auto_safe") == ot.OperatorBucket.AUTO_SAFE


def test_run_state_derived_from_live_supervisors():
    item = {"id": "gate:p1", "clears_when": {"params": {"plan_id": "P1"}}}
    assert ot.derive_run_state(item, live_supervisors=[]) == "idle"
    assert ot.derive_run_state(item, live_supervisors=[{"plan_id": "P1"}]) == "running"
    assert ot.derive_run_state(item, live_supervisors=[{"plan_id": "P1"}, {"plan_id": "P1"}]) == "conflicted"
    assert ot.derive_run_state(item, live_supervisors=[{"plan_id": "OTHER"}]) == "idle"


def test_scope_global_vs_project():
    assert ot.derive_scope({"project_name": "spindineswift"}) == ("project", "spindineswift")
    assert ot.derive_scope({"project_name": None}) == ("global", None)
    assert ot.derive_scope({}) == ("global", None)


def test_build_triage_emits_buckets_data_quality_and_stable_revision(real_items):
    model = ot.build_triage(real_items, safety_class_for=_no_safety, live_supervisors=[])
    assert model["item_count"] == len(real_items)
    # every item carries its derived fields
    for it in model["items"]:
        assert it["operator_bucket"] in {b.value for b in ot.OperatorBucket}
        assert it["scope"] in ("global", "project")
        assert it["run_state"] in ("idle", "running", "conflicted")
    dq = model["data_quality"]
    assert dq["total"] == len(real_items)
    assert sum(dq["counts"].values()) == len(real_items)
    assert dq["uncertain"] == dq["counts"].get("uncertain", 0)
    # state_revision is a stable fingerprint: same input -> same revision
    again = ot.build_triage(real_items, safety_class_for=_no_safety, live_supervisors=[])
    assert model["state_revision"] == again["state_revision"]
    # the serialization round-trips (parity anchor)
    assert json.loads(json.dumps(model))["state_revision"] == model["state_revision"]


def test_state_revision_changes_when_buckets_change(real_items):
    base = ot.build_triage(real_items, safety_class_for=_no_safety, live_supervisors=[])
    # mark every automatable item auto_safe -> buckets shift -> revision must change
    shifted = ot.build_triage(real_items, safety_class_for=lambda it: "auto_safe", live_supervisors=[])
    assert base["state_revision"] != shifted["state_revision"]
