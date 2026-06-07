"""operator-triage/v0 schema gaps — F001 (plan 2026-06-06-004 redesign).

Adds, additively, the four parity/render-truth fields the console redesign needs:
resolution[], asserted_at, freshness_basis, provenance_source. These tests pin the
derivation rules + the honest freshness basis (plan-level liveness is NOT item-level
freshness; the filled dot is reserved for item_probe, which no v0 producer emits) +
backward compatibility (no field renamed/removed).
"""

from __future__ import annotations

from dontpanic_orchestrate import operator_triage as ot


def _build(items, *, live=()):
    return ot.build_triage(
        items,
        safety_class_for=lambda _it: None,
        live_supervisors=list(live),
    )


# ── resolution_for: enumerated, bucket-correct, derived (claims no new truth) ──

def test_resolution_for_each_bucket():
    R = ot.resolution_for
    assert R("needs_decision", None) == ["approve", "request_changes", "reject"]
    assert R("needs_auth", None) == ["guided_setup"]
    assert R("auto_safe", None) == ["apply_fix"]
    assert R("uncertain", None) == ["inspect"]
    assert R("quiet", None) == []
    # agent_runnable depends on a command existing
    assert R("agent_runnable", "dontpanic x") == ["run"]
    assert R("agent_runnable", None) == []  # nothing to run yet
    assert R("agent_runnable", "") == []


def test_build_emits_resolution_matching_bucket():
    # an info item → quiet → [] ; an automatable item with a command → agent_runnable → ["run"]
    model = _build([
        {"id": "a", "band": "info"},
        {"id": "b", "resolution_class": "command_resolvable", "exact_command": "dontpanic do"},
    ])
    by_id = {i["id"]: i for i in model["items"]}
    assert by_id["a"]["operator_bucket"] == "quiet"
    assert by_id["a"]["resolution"] == []
    # concrete (not tautological): an agent_runnable item with a command → exactly ["run"]
    assert by_id["b"]["operator_bucket"] == "agent_runnable"
    assert by_id["b"]["resolution"] == ["run"]
    for it in model["items"]:
        # resolution is always a list, always a subset of the closed vocabulary
        assert isinstance(it["resolution"], list)
        assert set(it["resolution"]) <= {
            "approve", "request_changes", "reject", "guided_setup",
            "apply_fix", "inspect", "run",
        }


# ── freshness_basis: render-truth — plan-level liveness is NOT item-level freshness ──

def test_freshness_basis_null_when_no_basis():
    model = _build([{"id": "x", "band": "info"}])
    # no live supervisor → no basis → null → the renderer must show hollow / unverified
    assert model["items"][0]["freshness_basis"] is None


def test_freshness_basis_plan_match_only_with_a_live_supervisor():
    plan = "2026-06-06-001-feat-thing"
    item = {"id": f"gate:{plan}", "title": "Gate approval"}
    # no supervisors → idle → no basis
    assert _build([item])["items"][0]["freshness_basis"] is None
    # one live supervisor on the plan → running → PLAN-level basis (not item-level)
    rep = _build([item], live=[{"plan_id": plan}])["items"][0]
    assert rep["run_state"] == "running"
    assert rep["freshness_basis"] == "live_supervisor_plan_match"
    # two supervisors → conflicted → still only a plan-level basis
    conflicted = _build([item], live=[{"plan_id": plan}, {"plan_id": plan}])["items"][0]
    assert conflicted["run_state"] == "conflicted"
    assert conflicted["freshness_basis"] == "live_supervisor_plan_match"


def test_no_v0_item_claims_item_level_freshness():
    # RENDER-TRUTH: the filled freshness dot is reserved for "item_probe", and NO v0
    # producer can emit it — so plan liveness can never be mislabeled as item freshness.
    plan = "2026-06-06-001-feat-thing"
    model = _build(
        [{"id": f"gate:{plan}", "title": "Gate approval"}, {"id": "y", "band": "info"}],
        live=[{"plan_id": plan}],
    )
    assert all(i["freshness_basis"] != "item_probe" for i in model["items"])
    assert {i["freshness_basis"] for i in model["items"]} <= {"live_supervisor_plan_match", None}


# ── asserted_at + provenance_source ──

def test_asserted_at_from_updated_at_else_null():
    model = _build([
        {"id": "a", "updated_at": "2026-06-06T12:00:00Z"},
        {"id": "b"},
    ])
    by_id = {i["id"]: i for i in model["items"]}
    assert by_id["a"]["asserted_at"] == "2026-06-06T12:00:00Z"
    assert by_id["b"]["asserted_at"] is None


def test_provenance_source_reads_source_else_null_and_keeps_actor_label_separate():
    model = _build([
        {"id": "a", "source": "claude-auditor"},
        {"id": "b", "producer": "capabilities-probe"},
        {"id": "c"},
    ])
    by_id = {i["id"]: i for i in model["items"]}
    assert by_id["a"]["provenance_source"] == "claude-auditor"
    assert by_id["b"]["provenance_source"] == "capabilities-probe"
    assert by_id["c"]["provenance_source"] is None
    # provenance_source is a machine id; actor_label remains the (None here) display name
    assert all("actor_label" in i for i in model["items"])


# ── additive parity: nothing removed; new fields present on every item ──

def test_additive_no_existing_field_removed_and_new_fields_present():
    model = _build([{"id": "a", "band": "info"}])
    it = model["items"][0]
    existing = {
        "id", "operator_bucket", "scope", "project_name", "run_state",
        "actor_label", "dedupe_key", "duplicate_count", "exact_command",
        "title", "why_now", "evidence_uri",
    }
    assert existing <= set(it)  # backward-compatible
    assert {"resolution", "asserted_at", "freshness_basis", "provenance_source"} <= set(it)
    assert "proven_live" not in it  # the overclaiming boolean was removed before any renderer
    assert model["schema"] == "operator-triage/v0"  # additive extend, not a new version
