"""Plan 2026-06-04-005 F001 — unified render gate (render/suppress/demote).

The gate is the single deterministic decision point every card passes through
before it can render as Needs Action. Normative 6-step order (operator-confirmed,
D004):
  1. scope applies?            else SUPPRESS
  2. source fresh + evaluable? else DEMOTE
  3. clears_when present?      else DEMOTE
  4. resolution_class set?     else DEMOTE
  5. predicate resolved?       -> SUPPRESS
  6. unresolved                -> RENDER
"""

from __future__ import annotations

from types import SimpleNamespace

from dontpanic_orchestrate import action_resolvability as _ar
from dontpanic_orchestrate import render_gate as rg
from dontpanic_orchestrate.operator_console import Band

# reconcile_clean: resolved iff a reconcile dict is present with no drift_kinds.
_CW = _ar.ClearsWhen("reconcile_clean", {})
_UNRESOLVED = {"reconcile": {"drift_kinds": ["new_capabilities"]}}  # drift present
_RESOLVED = {"reconcile": {"drift_kinds": []}}  # clean


def _card(
    *,
    band=Band.NEEDS_ACTION,
    clears_when=_CW,
    resolution_class=_ar.RESOLUTION_COMMAND_RESOLVABLE,
):
    return SimpleNamespace(
        id="x", band=band, clears_when=clears_when, resolution_class=resolution_class
    )


def _decide(card, *, scope_applies=True, source_fresh=True, source_evaluable=True, live_state=None):
    return rg.render_decision(
        card,
        scope_applies=scope_applies,
        source_fresh=source_fresh,
        source_evaluable=source_evaluable,
        live_state=_UNRESOLVED if live_state is None else live_state,
    )


# ── step 1: scope ─────────────────────────────────────────────────────────────
def test_scope_not_applies_suppresses():
    assert _decide(_card(), scope_applies=False) == rg.SUPPRESS


def test_precedence_scope_beats_staleness():
    # scope is checked FIRST: a not-applicable card suppresses before staleness demotes.
    assert _decide(_card(), scope_applies=False, source_fresh=False) == rg.SUPPRESS


# ── step 2: source freshness / evaluability ──────────────────────────────────
def test_needs_action_stale_source_demotes():
    assert _decide(_card(), source_fresh=False) == rg.DEMOTE


def test_needs_action_uneval_source_demotes():
    assert _decide(_card(), source_evaluable=False) == rg.DEMOTE


# ── step 3: verification path (recompute | evidence | reconstruction) ────────
def test_needs_action_command_resolvable_no_predicate_renders_via_reconstruction():
    # No clears_when, but the source is fresh (step 2 passed) -> the card is
    # reconstruction-fresh (re-emitted this build) -> render, NOT demote. A
    # missing predicate is not uncertainty; only a stale source is.
    assert _decide(_card(clears_when=None, resolution_class=_ar.RESOLUTION_COMMAND_RESOLVABLE)) == rg.RENDER


def test_needs_action_operator_attested_no_predicate_renders():
    # operator_attested resolves via EVIDENCE, not recompute: legit live card
    assert _decide(_card(clears_when=None, resolution_class=_ar.RESOLUTION_OPERATOR_ATTESTED)) == rg.RENDER


def test_needs_action_blocked_external_no_predicate_renders():
    assert _decide(_card(clears_when=None, resolution_class=_ar.RESOLUTION_BLOCKED_EXTERNAL)) == rg.RENDER


def test_needs_action_missing_resolution_class_still_demotes():
    # A NEEDS_ACTION card with NO resolution_class at all is malformed -> demote.
    assert _decide(_card(clears_when=None, resolution_class="")) == rg.DEMOTE
    # ...and a stale source still demotes regardless of predicate.
    assert _decide(_card(clears_when=None), source_fresh=False) == rg.DEMOTE


# ── step 4: resolution_class set ─────────────────────────────────────────────
def test_needs_action_missing_resolution_class_demotes():
    assert _decide(_card(resolution_class="")) == rg.DEMOTE


# ── step 5: resolved -> suppress ─────────────────────────────────────────────
def test_needs_action_resolved_suppresses():
    assert _decide(_card(), live_state=_RESOLVED) == rg.SUPPRESS


# ── step 6: unresolved -> render ─────────────────────────────────────────────
def test_needs_action_unresolved_renders():
    assert _decide(_card(), live_state=_UNRESOLVED) == rg.RENDER


# ── lower-band cards: not Needs Action, so not fail-closed-gated ──────────────
def test_advisory_unresolved_renders_in_own_band():
    # An advisory card with no predicate is NOT demoted (it makes no Needs Action claim).
    assert _decide(_card(band=Band.ADVISORY, clears_when=None)) == rg.RENDER


def test_advisory_resolved_suppresses():
    assert _decide(_card(band=Band.ADVISORY), live_state=_RESOLVED) == rg.SUPPRESS


def test_info_card_not_demoted_for_missing_predicate():
    assert _decide(_card(band=Band.INFO, clears_when=None)) == rg.RENDER


# ── outcomes are total + mutually exclusive ──────────────────────────────────
def test_every_decision_is_one_of_three_outcomes():
    cases = [
        _decide(_card(), scope_applies=False),
        _decide(_card(), source_fresh=False),
        _decide(_card(clears_when=None)),
        _decide(_card(resolution_class="")),
        _decide(_card(), live_state=_RESOLVED),
        _decide(_card(), live_state=_UNRESOLVED),
    ]
    assert all(c in rg.OUTCOMES for c in cases)
    assert rg.OUTCOMES == {rg.RENDER, rg.SUPPRESS, rg.DEMOTE}
    # all three outcomes are reachable
    assert set(cases) >= {rg.SUPPRESS, rg.DEMOTE, rg.RENDER}
