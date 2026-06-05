"""Plan 2026-06-04-006 F005 — round-trip verification.

After an action runs, the runner recomputes live_state and re-evaluates the
targeted card's ``clears_when`` (001's predicate primitive, at apply time) to
classify the outcome as cleared / chained / human_required / unchanged. An
``unchanged`` card — its predicate did not move and nothing chained/escalated —
is a DEFECT signal: the card or its action is incomplete.
"""

from __future__ import annotations

from types import SimpleNamespace

from dontpanic_orchestrate import action_resolvability as ar
from dontpanic_orchestrate import repair_verify as rv


def _card(predicate, params, resolution_class):
    return SimpleNamespace(
        id="card-1",
        clears_when=ar.ClearsWhen(predicate=predicate, params=params),
        resolution_class=resolution_class,
    )


# live_state shapes for the seed predicates -------------------------------------
def _gate_card(rc=ar.RESOLUTION_COMMAND_RESOLVABLE):
    # gate_no_longer_actionable resolves (True) when the plan is terminal/pre-lock.
    return _card("gate_no_longer_actionable", {"plan_id": "P", "gate": "g"}, rc)


_GATE_STILL_OPEN = {"plan_status": {"P": "active"}, "cleared_gates": {"P": []}}
_GATE_RESOLVED = {"plan_status": {"P": "completed"}}


def _cap_card():
    return _card(
        "capability_ready", {"capability_id": "C"}, ar.RESOLUTION_OPERATOR_ATTESTED
    )


_CAP_NOT_READY = {"capabilities": {"C": "needs_setup"}}


# ── cleared ────────────────────────────────────────────────────────────────────
def test_derived_refresh_clears_a_stale_card():
    # the action regenerated state; the predicate now resolves -> cleared
    assert rv.verify_round_trip(_gate_card(), _GATE_RESOLVED) == rv.CLEARED


# ── chained ────────────────────────────────────────────────────────────────────
def test_chained_action_that_surfaces_next_step_is_chained():
    card = _gate_card(ar.RESOLUTION_CHAINED)
    out = rv.verify_round_trip(
        card, _GATE_STILL_OPEN, chained_followups=(SimpleNamespace(id="next"),)
    )
    assert out == rv.CHAINED


def test_chained_step_that_clears_with_no_followup_is_cleared():
    card = _gate_card(ar.RESOLUTION_CHAINED)
    assert rv.verify_round_trip(card, _GATE_RESOLVED) == rv.CLEARED


def test_chained_step_that_neither_clears_nor_surfaces_is_unchanged():
    card = _gate_card(ar.RESOLUTION_CHAINED)
    assert rv.verify_round_trip(card, _GATE_STILL_OPEN) == rv.UNCHANGED


# ── human_required ─────────────────────────────────────────────────────────────
def test_operator_attested_card_that_did_not_clear_is_human_required():
    # no command clears it; the predicate is still unresolved -> escalate to human
    assert rv.verify_round_trip(_cap_card(), _CAP_NOT_READY) == rv.HUMAN_REQUIRED


# ── unchanged / defective ──────────────────────────────────────────────────────
def test_command_action_that_does_not_move_its_predicate_is_defective():
    out = rv.verify_round_trip(_gate_card(), _GATE_STILL_OPEN)
    assert out == rv.UNCHANGED
    assert rv.is_defective(out) is True


def test_only_unchanged_is_defective():
    assert rv.is_defective(rv.CLEARED) is False
    assert rv.is_defective(rv.CHAINED) is False
    assert rv.is_defective(rv.HUMAN_REQUIRED) is False
    assert rv.is_defective(rv.UNCHANGED) is True


def test_outcomes_are_a_closed_set():
    assert rv.OUTCOMES == frozenset(
        {rv.CLEARED, rv.CHAINED, rv.HUMAN_REQUIRED, rv.UNCHANGED}
    )
