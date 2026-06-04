"""Plan 2026-06-04-001 F001 — ActionItem resolvability contract unit tests."""

from __future__ import annotations

import pytest

from dontpanic_orchestrate import action_resolvability as ar
from dontpanic_orchestrate.operator_console import ActionItem, Band


# ── resolution_class contract ────────────────────────────────────────────────
def test_resolution_classes_are_exactly_four():
    assert ar.RESOLUTION_CLASSES == {
        "command_resolvable",
        "chained",
        "operator_attested",
        "blocked_external",
    }


def test_validate_resolution_class_rejects_unknown():
    ar.validate_resolution_class("command_resolvable")  # no raise
    with pytest.raises(ValueError):
        ar.validate_resolution_class("totally_made_up")


def test_non_command_classes_are_attested_and_blocked():
    assert ar.NON_COMMAND_RESOLUTION_CLASSES == {
        "operator_attested",
        "blocked_external",
    }


# ── ClearsWhen references the closed registry ────────────────────────────────
def test_clears_when_rejects_unregistered_predicate():
    with pytest.raises(ValueError):
        ar.ClearsWhen(predicate="no_such_predicate")


def test_clears_when_roundtrips_dict():
    cw = ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": "p", "gate": "pre_impl"})
    again = ar.ClearsWhen.from_dict(cw.to_dict())
    assert again.predicate == cw.predicate
    assert dict(again.params) == {"plan_id": "p", "gate": "pre_impl"}


def test_registered_predicates_is_closed_and_nonempty():
    preds = ar.registered_predicates()
    assert "gate_no_longer_actionable" in preds
    assert "install_snapshot_fresh" in preds


# ── evaluate_clears_when is pure + correct per predicate ──────────────────────
def test_evaluate_none_never_clears():
    assert ar.evaluate_clears_when(None, {}) is False


def test_gate_predicate_true_when_plan_terminal():
    cw = ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": "p", "gate": "pre_impl"})
    # completed plan → gate card resolved (drop)
    assert ar.evaluate_clears_when(cw, {"plan_status": {"p": "completed"}}) is True
    # abandoned likewise
    assert ar.evaluate_clears_when(cw, {"plan_status": {"p": "abandoned"}}) is True


def test_gate_predicate_false_when_live_and_uncleared():
    cw = ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": "p", "gate": "pre_impl"})
    st = {"plan_status": {"p": "active"}, "cleared_gates": {"p": []}}
    assert ar.evaluate_clears_when(cw, st) is False  # still actionable → keep card


def test_gate_predicate_true_when_gate_already_cleared():
    cw = ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": "p", "gate": "pre_impl"})
    st = {"plan_status": {"p": "active"}, "cleared_gates": {"p": ["pre_impl"]}}
    assert ar.evaluate_clears_when(cw, st) is True


@pytest.mark.parametrize("status", sorted(ar.LIVE_BUT_UNFINISHED_STATUSES))
def test_gate_predicate_keeps_card_for_each_live_status(status):
    cw = ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": "p", "gate": "pre_merge"})
    st = {"plan_status": {"p": status}, "cleared_gates": {"p": []}}
    assert ar.evaluate_clears_when(cw, st) is False


def test_install_snapshot_fresh_predicate():
    cw = ar.ClearsWhen("install_snapshot_fresh")
    assert ar.evaluate_clears_when(cw, {"reconcile": {"snapshot_present": True, "cache_fresh": True}}) is True
    assert ar.evaluate_clears_when(cw, {"reconcile": {"snapshot_present": True, "cache_fresh": False}}) is False
    assert ar.evaluate_clears_when(cw, {"reconcile": {}}) is False
    assert ar.evaluate_clears_when(cw, {}) is False


def test_duplicate_predicate_registration_raises():
    with pytest.raises(ValueError):
        @ar.register_predicate("gate_no_longer_actionable")
        def _dupe(params, live_state):  # pragma: no cover
            return True


# ── ActionItem carries + serializes the contract ─────────────────────────────
def _item(**kw):
    base = dict(
        id="x:1", source="reconcile", band=Band.NEEDS_ACTION, title="t", detail="d",
        exact_command=None, automatable=False, human_required_reason="needs human",
        evidence_uri=None, updated_at="2026-06-04T00:00:00Z", dedupe_key="x:1",
    )
    base.update(kw)
    return ActionItem(**base)


def test_actionitem_defaults_resolution_class_command_resolvable():
    it = _item()
    assert it.resolution_class == "command_resolvable"
    assert it.clears_when is None
    d = it.to_dict()
    assert d["resolution_class"] == "command_resolvable"
    assert d["clears_when"] is None


def test_actionitem_rejects_bad_resolution_class():
    with pytest.raises(ValueError):
        _item(resolution_class="nope")


def test_actionitem_serializes_clears_when():
    cw = ar.ClearsWhen("install_snapshot_fresh")
    it = _item(clears_when=cw, resolution_class="operator_attested")
    d = it.to_dict()
    assert d["clears_when"] == {"predicate": "install_snapshot_fresh", "params": {}}
    assert d["resolution_class"] == "operator_attested"
