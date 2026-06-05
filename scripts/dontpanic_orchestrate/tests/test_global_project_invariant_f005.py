"""Plan 2026-06-04-005 F005 — global/project separation + four-part render-truth
invariant + the pinned QuantRE regression.

A global producer emits one scope=global card; a project view shows it with a
GLOBAL badge iff its predicate is unresolved AND source fresh, hides it when the
live global predicate is clean, and never resurrects a now-clean global card from
a per-project cache (the gate re-evaluates the live predicate, never trusts a
cached card). The invariant: every visible Needs Action card satisfies
scope ∧ fresh ∧ unresolved ∧ resolution_class.
"""

from __future__ import annotations

from types import SimpleNamespace

from dontpanic_orchestrate import action_resolvability as _ar
from dontpanic_orchestrate import render_gate as rg
from dontpanic_orchestrate import scope_lattice as sl
from dontpanic_orchestrate.operator_console import Band

_QUANTRE = "quantre-migration"
# A global reconcile/install-drift card (the "setup-drift" / missing_snapshot card).
_INSTALL_CW = _ar.ClearsWhen("install_snapshot_fresh", {})


def _global_card(clears_when=_INSTALL_CW):
    return SimpleNamespace(
        id="reconcile:missing_snapshot",
        source="reconcile",
        band=Band.NEEDS_ACTION,
        scope=sl.Scope.GLOBAL.value,
        clears_when=clears_when,
        resolution_class=_ar.RESOLUTION_CHAINED,
    )


# ── GLOBAL badge ──────────────────────────────────────────────────────────────
def test_global_card_badged_in_project_view():
    assert rg.global_badge_for(_global_card(), selected_scope=sl.Scope.PROJECT.value) is True


def test_global_card_not_badged_in_fleet_view():
    # aggregate views show everything ungrouped; no per-card GLOBAL badge needed
    assert rg.global_badge_for(_global_card(), selected_scope=sl.Scope.FLEET.value) is False


def test_project_card_never_badged_global():
    proj = SimpleNamespace(id="g", source="gate", band=Band.NEEDS_ACTION,
                           scope=sl.Scope.PROJECT.value, project_name=_QUANTRE,
                           clears_when=None, resolution_class=_ar.RESOLUTION_OPERATOR_ATTESTED)
    assert rg.global_badge_for(proj, selected_scope=sl.Scope.PROJECT.value) is False


# ── global card renders (badged) while unresolved + fresh, in a project view ──
def test_global_unresolved_renders_in_project_view():
    # missing snapshot -> install_snapshot_fresh NOT resolved -> renders
    live = {"reconcile": {"snapshot_present": False, "cache_fresh": False}}
    d = rg.render_decision(_global_card(), scope_state=sl.APPLIES, source_fresh=True, live_state=live)
    assert d == rg.RENDER


# ── hidden when the global predicate is clean (suppressed, not resurrected) ───
def test_global_clean_predicate_suppressed():
    live = {"reconcile": {"snapshot_present": True, "cache_fresh": True}}  # clean
    d = rg.render_decision(_global_card(), scope_state=sl.APPLIES, source_fresh=True, live_state=live)
    assert d == rg.SUPPRESS


# ── THE QuantRE regression (pinned acceptance) ────────────────────────────────
def test_quantre_stale_cache_clean_global_renders_zero_setup_drift():
    """Selected project = quantre-migration; a stale per-project cache 'says'
    missing_snapshot (the card is present in the input, as if rehydrated from
    what-now-cache.json); BUT the LIVE global reconcile check is clean. The gate
    re-evaluates the live predicate (never trusts the cached card) -> the
    setup-drift card is SUPPRESSED. Zero setup-drift Needs Action cards render."""
    stale_cached_card = _global_card()  # as if resurrected from a per-project cache
    live_clean_global = {"reconcile": {"snapshot_present": True, "cache_fresh": True}}

    # scope: a global card APPLIES in the quantre project view (would be badged)
    st = sl.resolve_card_scope_state(
        stale_cached_card, selected_scope=sl.Scope.PROJECT.value, selected_project=_QUANTRE
    )
    assert st == sl.APPLIES

    decision = rg.render_decision(
        stale_cached_card, scope_state=st, source_fresh=True, live_state=live_clean_global
    )
    assert decision == rg.SUPPRESS  # NOT rendered, NOT resurrected from cache

    rendered = [stale_cached_card] if decision == rg.RENDER else []
    setup_drift = [c for c in rendered if "snapshot" in c.id or "setup" in c.id]
    assert setup_drift == []  # zero setup-drift cards in the quantre project view


# ── four-part invariant over a mixed fixture ──────────────────────────────────
def test_render_truth_invariant_holds_for_clean_render_set():
    live = {"reconcile": {"snapshot_present": False, "cache_fresh": False}}  # global unresolved
    rendered = [
        _global_card(),  # global, unresolved, fresh, resolution_class set -> valid
        SimpleNamespace(id="gate:p:pre_merge", source="gate", band=Band.NEEDS_ACTION,
                        scope=sl.Scope.PROJECT.value, project_name=_QUANTRE, clears_when=None,
                        resolution_class=_ar.RESOLUTION_OPERATOR_ATTESTED),  # evidence-class, valid
    ]
    violations = rg.render_truth_invariant(
        rendered,
        scope_state_of=lambda c: sl.resolve_card_scope_state(
            c, selected_scope=sl.Scope.PROJECT.value, selected_project=_QUANTRE
        ),
        source_fresh_of=lambda c: (True, True),
        live_state=live,
    )
    assert violations == []


def test_render_truth_invariant_flags_violations():
    live = {"reconcile": {"snapshot_present": True, "cache_fresh": True}}  # makes install card RESOLVED
    rendered = [
        _global_card(),  # predicate now resolved -> should NOT be in a render set -> violation
        SimpleNamespace(id="stale:x", source="reconcile", band=Band.NEEDS_ACTION,
                        scope=sl.Scope.GLOBAL.value, clears_when=None,
                        resolution_class=_ar.RESOLUTION_CHAINED),  # stale source -> violation
        SimpleNamespace(id="noclass:y", source="reconcile", band=Band.NEEDS_ACTION,
                        scope=sl.Scope.GLOBAL.value, clears_when=None, resolution_class=""),  # malformed
    ]

    def fresh_of(c):
        return (False, True) if c.id == "stale:x" else (True, True)

    violations = rg.render_truth_invariant(
        rendered,
        scope_state_of=lambda c: sl.APPLIES,
        source_fresh_of=fresh_of,
        live_state=live,
    )
    ids = {v[0] for v in violations}
    assert ids == {"reconcile:missing_snapshot", "stale:x", "noclass:y"}
