"""Plan 2026-06-04-005 F002 — explicit producer-asserted scope + applicability lattice.

scope_state() returns a TRI-STATE so the gate can fail closed:
  - APPLIES        -> card is relevant to the selected view
  - NOT_APPLICABLE -> card definitively belongs elsewhere -> suppress
  - UNRESOLVED     -> cannot prove which project a plan/feature card belongs to -> demote
Lattice: global ⊇ every view; fleet only in the aggregate view; project only its own;
plan/feature resolve their plan_id -> project (failed resolution -> UNRESOLVED).
No silent project_name inference: an unset scope routes through a logged legacy adapter.
"""

from __future__ import annotations

from types import SimpleNamespace

from dontpanic_orchestrate import action_resolvability as _ar
from dontpanic_orchestrate import render_gate as rg
from dontpanic_orchestrate import scope_lattice as sl
from dontpanic_orchestrate.operator_console import Band

# ── lattice truth table ───────────────────────────────────────────────────────
def test_global_applies_to_every_view():
    for sel in (sl.Scope.GLOBAL, sl.Scope.FLEET, sl.Scope.PROJECT):
        assert sl.scope_state(sl.Scope.GLOBAL, selected_scope=sel, selected_project="quantre") == sl.APPLIES


def test_aggregate_view_shows_everything():
    # fleet/global aggregate views show project + global + fleet cards
    assert sl.scope_state(sl.Scope.PROJECT, selected_scope=sl.Scope.FLEET, card_project="a") == sl.APPLIES
    assert sl.scope_state(sl.Scope.FLEET, selected_scope=sl.Scope.GLOBAL) == sl.APPLIES


def test_project_card_applies_only_to_its_own_project_view():
    assert sl.scope_state(sl.Scope.PROJECT, selected_scope=sl.Scope.PROJECT,
                          card_project="quantre", selected_project="quantre") == sl.APPLIES
    assert sl.scope_state(sl.Scope.PROJECT, selected_scope=sl.Scope.PROJECT,
                          card_project="other", selected_project="quantre") == sl.NOT_APPLICABLE


def test_fleet_card_not_shown_in_single_project_view():
    assert sl.scope_state(sl.Scope.FLEET, selected_scope=sl.Scope.PROJECT,
                          selected_project="quantre") == sl.NOT_APPLICABLE


def test_plan_card_resolves_to_project():
    resolve = {"2026-06-04-005": "dontpanic"}.get
    # resolves to selected project -> applies
    assert sl.scope_state(sl.Scope.PLAN, selected_scope=sl.Scope.PROJECT, selected_project="dontpanic",
                          card_plan_id="2026-06-04-005", resolve_plan_to_project=resolve) == sl.APPLIES
    # resolves to a DIFFERENT project -> not applicable
    assert sl.scope_state(sl.Scope.PLAN, selected_scope=sl.Scope.PROJECT, selected_project="quantre",
                          card_plan_id="2026-06-04-005", resolve_plan_to_project=resolve) == sl.NOT_APPLICABLE


def test_plan_card_failed_resolution_is_unresolved():
    resolve = {}.get  # nothing resolves
    assert sl.scope_state(sl.Scope.PLAN, selected_scope=sl.Scope.PROJECT, selected_project="quantre",
                          card_plan_id="unknown", resolve_plan_to_project=resolve) == sl.UNRESOLVED
    # no resolver at all -> unresolved (cannot prove)
    assert sl.scope_state(sl.Scope.FEATURE, selected_scope=sl.Scope.PROJECT, selected_project="q",
                          card_plan_id="p") == sl.UNRESOLVED


def test_unknown_scope_fails_closed_unresolved():
    assert sl.scope_state("nonsense", selected_scope=sl.Scope.PROJECT, selected_project="q") == sl.UNRESOLVED


# ── gate integration: scope_state drives the gate's step 1 (3-way) ────────────
def _card(band=Band.NEEDS_ACTION, clears_when=_ar.ClearsWhen("reconcile_clean", {}),
          resolution_class=_ar.RESOLUTION_COMMAND_RESOLVABLE):
    return SimpleNamespace(id="x", band=band, clears_when=clears_when, resolution_class=resolution_class)

_UNRESOLVED_LS = {"reconcile": {"drift_kinds": ["new_capabilities"]}}


def test_gate_unresolved_scope_demotes():
    # A plan card whose project can't be resolved must DEMOTE, not suppress or render.
    assert rg.render_decision(_card(), scope_state=sl.UNRESOLVED,
                              source_fresh=True, live_state=_UNRESOLVED_LS) == rg.DEMOTE


def test_gate_not_applicable_scope_suppresses():
    assert rg.render_decision(_card(), scope_state=sl.NOT_APPLICABLE,
                              source_fresh=True, live_state=_UNRESOLVED_LS) == rg.SUPPRESS


def test_gate_applies_scope_continues_to_render():
    assert rg.render_decision(_card(), scope_state=sl.APPLIES,
                              source_fresh=True, live_state=_UNRESOLVED_LS) == rg.RENDER


def test_gate_bool_scope_compat_still_works():
    # F001's bool path is preserved: True->applies, False->not_applicable.
    assert rg.render_decision(_card(), scope_applies=True, source_fresh=True, live_state=_UNRESOLVED_LS) == rg.RENDER
    assert rg.render_decision(_card(), scope_applies=False, source_fresh=True, live_state=_UNRESOLVED_LS) == rg.SUPPRESS


# ── no silent inference: unset scope -> logged legacy adapter, demotion-eligible ─
def test_unset_scope_uses_logged_legacy_adapter(caplog):
    card = SimpleNamespace(id="legacy", band=Band.NEEDS_ACTION, scope=None, project_name="quantre")
    import logging
    with caplog.at_level(logging.WARNING):
        st = sl.resolve_card_scope_state(card, selected_scope=sl.Scope.PROJECT, selected_project="quantre")
    # legacy adapter must LOG that it fired (deprecation), and must NOT silently treat
    # the card as trustworthy project work — it is demotion-eligible / advisory.
    assert any("legacy" in r.message.lower() or "unscoped" in r.message.lower() for r in caplog.records)
    assert st in (sl.APPLIES, sl.NOT_APPLICABLE, sl.UNRESOLVED)
    assert sl.is_legacy_unscoped(card) is True


def test_explicit_scope_skips_legacy_adapter(caplog):
    card = SimpleNamespace(id="m", band=Band.NEEDS_ACTION, scope=sl.Scope.GLOBAL.value, project_name=None)
    import logging
    with caplog.at_level(logging.WARNING):
        st = sl.resolve_card_scope_state(card, selected_scope=sl.Scope.PROJECT, selected_project="quantre")
    assert st == sl.APPLIES
    assert sl.is_legacy_unscoped(card) is False
