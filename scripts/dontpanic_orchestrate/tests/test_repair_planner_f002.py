"""Plan 2026-06-04-006 F002 — dependency-ordered fixpoint repair planner.

The planner consumes the 005 render-gate output (render -> repair candidate,
demote -> source-refresh candidate, suppress -> skip), orders candidates by
declared dependency, then runs a fixpoint loop: apply the eligible auto_safe
batch -> recompute state -> re-plan, until only human_required / blocked_external
/ info remain or no progress is made. A state-changing step re-plans rather than
trusting a static list; cyclic / dependency-stuck input is detected and deferred,
not looped. Every applied action is round-trip verified (F005).
"""

from __future__ import annotations

import copy

from dontpanic_orchestrate import action_resolvability as ar
from dontpanic_orchestrate import render_gate as rg
from dontpanic_orchestrate import repair_planner as rp
from dontpanic_orchestrate import repair_safety as rs
from dontpanic_orchestrate import repair_verify as rv


def _action(
    aid,
    *,
    kind="recompute_what_now",
    safety_class=rs.AUTO_SAFE,
    apply_tier=rs.TIER_DERIVED_STATE,
    resolution_class=ar.RESOLUTION_COMMAND_RESOLVABLE,
    depends_on=(),
    plan_id=None,
):
    plan_id = plan_id or aid
    return rp.RepairAction(
        id=aid,
        kind=kind,
        safety_class=safety_class,
        apply_tier=apply_tier,
        resolution_class=resolution_class,
        clears_when=ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": plan_id, "gate": "g"}),
        depends_on=tuple(depends_on),
    )


# initial state: every plan is "active" so every candidate's predicate is UNRESOLVED.
def _state(plan_ids):
    return {"plan_status": {p: "active" for p in plan_ids}, "cleared_gates": {}}


def _resolving_apply(action, state):
    """Stub side effect: completing the plan resolves that card's predicate."""
    new = copy.deepcopy(state)
    new["plan_status"][action.clears_when.params["plan_id"]] = "completed"
    return new


def _noop_apply(action, state):
    """Stub side effect that does NOT move the predicate (defective action)."""
    return copy.deepcopy(state)


# ── ordering ───────────────────────────────────────────────────────────────────
def test_actions_ordered_prerequisite_before_dependent():
    a, b = _action("A"), _action("B", depends_on=["A"])
    ordered, cyclic = rp.order_actions([b, a])
    assert [x.id for x in ordered] == ["A", "B"]
    assert cyclic == set()


def test_cycle_is_detected():
    a = _action("A", depends_on=["B"])
    b = _action("B", depends_on=["A"])
    ordered, cyclic = rp.order_actions([a, b])
    assert cyclic == {"A", "B"}
    assert ordered == []


# ── fixpoint ───────────────────────────────────────────────────────────────────
def test_independent_safe_batch_applied_and_terminates():
    a, b = _action("A"), _action("B")
    run = rp.run_fixpoint([a, b], _state(["A", "B"]), apply_fn=_resolving_apply, run_tier=rs.RUN_TIER_DERIVED)
    assert {s.action_id for s in run.applied} == {"A", "B"}
    assert all(s.outcome == rv.CLEARED for s in run.applied)
    assert run.deferred == ()
    assert run.iterations <= 2


def test_replan_lets_dependent_run_after_prerequisite():
    a = _action("A")
    b = _action("B", depends_on=["A"])
    run = rp.run_fixpoint([b, a], _state(["A", "B"]), apply_fn=_resolving_apply, run_tier=rs.RUN_TIER_DERIVED)
    # B was not eligible until A ran (re-plan on state change); applied A before B.
    assert [s.action_id for s in run.applied] == ["A", "B"]
    assert run.deferred == ()


# ── deferral reasons ────────────────────────────────────────────────────────────
def test_human_required_action_deferred_with_safety_reason():
    h = _action("H", safety_class=rs.HUMAN_REQUIRED, apply_tier=None,
                resolution_class=ar.RESOLUTION_OPERATOR_ATTESTED)
    run = rp.run_fixpoint([h], _state(["H"]), apply_fn=_resolving_apply, run_tier=rs.RUN_TIER_DERIVED)
    assert run.applied == ()
    assert {(d.action_id, d.reason) for d in run.deferred} == {("H", rp.DEFER_SAFETY)}


def test_dependent_of_unrunnable_prereq_deferred_dependency():
    h = _action("H", safety_class=rs.HUMAN_REQUIRED, apply_tier=None,
                resolution_class=ar.RESOLUTION_BLOCKED_EXTERNAL)
    b = _action("B", depends_on=["H"])
    run = rp.run_fixpoint([b, h], _state(["H", "B"]), apply_fn=_resolving_apply, run_tier=rs.RUN_TIER_DERIVED)
    reasons = {d.action_id: d.reason for d in run.deferred}
    assert reasons == {"H": rp.DEFER_SAFETY, "B": rp.DEFER_DEPENDENCY}
    assert run.applied == ()


def test_cyclic_actions_deferred_not_looped():
    a = _action("A", depends_on=["B"])
    b = _action("B", depends_on=["A"])
    run = rp.run_fixpoint([a, b], _state(["A", "B"]), apply_fn=_resolving_apply, run_tier=rs.RUN_TIER_DERIVED)
    assert {(d.action_id, d.reason) for d in run.deferred} == {("A", rp.DEFER_CYCLE), ("B", rp.DEFER_CYCLE)}
    assert run.applied == ()


def test_confirmed_local_not_runnable_under_derived_tier():
    c = _action("C", kind=next(iter(rs.CONFIRMED_LOCAL_KINDS)), apply_tier=rs.TIER_CONFIRMED_LOCAL)
    run = rp.run_fixpoint([c], _state(["C"]), apply_fn=_resolving_apply, run_tier=rs.RUN_TIER_DERIVED)
    assert {(d.action_id, d.reason) for d in run.deferred} == {("C", rp.DEFER_SAFETY)}
    # ...but it runs under the stronger confirm tier
    run2 = rp.run_fixpoint([c], _state(["C"]), apply_fn=_resolving_apply, run_tier=rs.RUN_TIER_CONFIRM)
    assert [s.action_id for s in run2.applied] == ["C"]


# ── verification integration (F005) ─────────────────────────────────────────────
def test_action_that_does_not_move_predicate_flagged_defective():
    a = _action("A")
    run = rp.run_fixpoint([a], _state(["A"]), apply_fn=_noop_apply, run_tier=rs.RUN_TIER_DERIVED)
    assert [(s.action_id, s.outcome) for s in run.applied] == [("A", rv.UNCHANGED)]
    # an action applied once is never retried -> loop still terminates
    assert run.iterations <= 2


# ── consuming the 005 render gate ───────────────────────────────────────────────
def test_select_candidates_keeps_render_and_demote_skips_suppress():
    a, b, c = _action("A"), _action("B"), _action("C")
    decisions = [(a, rg.RENDER), (b, rg.DEMOTE), (c, rg.SUPPRESS)]
    kept = rp.select_candidates(decisions)
    assert [x.id for x in kept] == ["A", "B"]
