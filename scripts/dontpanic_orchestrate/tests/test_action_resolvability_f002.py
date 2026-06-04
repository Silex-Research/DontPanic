"""Plan 2026-06-04-001 F002 — suppress-at-source recompute tests."""

from __future__ import annotations

from dontpanic_orchestrate import action_resolvability as ar
from dontpanic_orchestrate.operator_console import ActionItem, Band


def _item(item_id, clears_when=None):
    return ActionItem(
        id=item_id, source="gate", band=Band.NEEDS_ACTION, title="t", detail="d",
        exact_command=None, automatable=False, human_required_reason="needs human",
        evidence_uri=None, updated_at="2026-06-04T00:00:00Z", dedupe_key=item_id,
        clears_when=clears_when,
    )


def test_suppress_drops_satisfied_keeps_unsatisfied_and_none():
    resolved = _item(
        "gate:p_done:pre_impl",
        ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": "p_done", "gate": "pre_impl"}),
    )
    live = _item(
        "gate:p_live:pre_impl",
        ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": "p_live", "gate": "pre_impl"}),
    )
    plain = _item("misc:1")  # clears_when=None → always kept
    state = {
        "plan_status": {"p_done": "completed", "p_live": "active"},
        "cleared_gates": {"p_live": []},
    }
    kept, audit = ar.suppress_resolved([resolved, live, plain], state)
    kept_ids = {it.id for it in kept}
    assert kept_ids == {"gate:p_live:pre_impl", "misc:1"}
    # audit names the suppressed item + its predicate
    assert len(audit) == 1
    assert audit[0]["id"] == "gate:p_done:pre_impl"
    assert audit[0]["dedupe_key"] == "gate:p_done:pre_impl"
    assert audit[0]["predicate"] == "gate_no_longer_actionable"


def test_suppress_returns_tuple_and_is_noop_when_all_none():
    items = [_item("a"), _item("b"), _item("c")]
    kept, audit = ar.suppress_resolved(items, {})
    assert isinstance(kept, tuple)
    assert [it.id for it in kept] == ["a", "b", "c"]
    assert audit == ()


def test_abandoned_plan_gate_is_suppressed():
    it = _item(
        "gate:p_dead:pre_merge",
        ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": "p_dead", "gate": "pre_merge"}),
    )
    kept, audit = ar.suppress_resolved([it], {"plan_status": {"p_dead": "abandoned"}})
    assert kept == ()
    assert audit[0]["id"] == "gate:p_dead:pre_merge"


def test_global_predicate_evaluates_without_any_project_dir():
    # install_snapshot_fresh is a GLOBAL predicate — it reads live_state only,
    # never a per-project capabilities/ dir. Proven by evaluating with a bare
    # reconcile mapping and no filesystem context.
    it = _item("reconcile:missing_snapshot", ar.ClearsWhen("install_snapshot_fresh"))
    # snapshot present + cache fresh → resolved → suppressed
    kept, audit = ar.suppress_resolved(
        [it], {"reconcile": {"snapshot_present": True, "cache_fresh": True}}
    )
    assert kept == ()
    # still missing → kept
    kept2, _ = ar.suppress_resolved(
        [it], {"reconcile": {"snapshot_present": False, "cache_fresh": False}}
    )
    assert [x.id for x in kept2] == ["reconcile:missing_snapshot"]
