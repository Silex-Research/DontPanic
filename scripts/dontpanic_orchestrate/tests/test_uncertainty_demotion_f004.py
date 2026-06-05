"""Plan 2026-06-04-005 F004 — stale/failed → uncertainty demotion for ALL producers.

A source the gate demotes (stale or eval_ok=False) has its cards REPLACED by
exactly one uncertainty card: band=INFO, resolution_class=blocked_external,
section=status_uncertain, stating source + last-checked + reason. N cards from one
stale source collapse to one card; zero render as Needs Action. Reconcile,
capabilities, gates, and architecture all demote through the same builder.
"""

from __future__ import annotations

from types import SimpleNamespace

from dontpanic_orchestrate import action_resolvability as _ar
from dontpanic_orchestrate import operator_console as oc
from dontpanic_orchestrate.operator_console import Band


def test_build_uncertainty_card_shape():
    c = oc.build_uncertainty_card(
        source=oc.SOURCE_RECONCILE, last_checked="2026-06-05T11:40:00Z", reason="source stale"
    )
    assert c.band == Band.INFO
    assert c.band != Band.NEEDS_ACTION
    assert c.resolution_class == _ar.RESOLUTION_BLOCKED_EXTERNAL
    assert c.section == oc.SECTION_STATUS_UNCERTAIN
    assert "could not be refreshed" in c.title.lower()
    assert oc.SOURCE_RECONCILE in c.title
    assert "2026-06-05T11:40:00Z" in (c.detail or "")
    assert "source stale" in (c.detail or "")


def test_collapse_n_cards_from_one_source_to_one_uncertainty_card():
    demoted = [
        SimpleNamespace(id="reconcile:new", source=oc.SOURCE_RECONCILE, band=Band.NEEDS_ACTION),
        SimpleNamespace(id="reconcile:removed", source=oc.SOURCE_RECONCILE, band=Band.NEEDS_ACTION),
        SimpleNamespace(id="reconcile:changed", source=oc.SOURCE_RECONCILE, band=Band.NEEDS_ACTION),
    ]
    fresh = {oc.SOURCE_RECONCILE: {"evaluated_at": "2026-06-05T11:40:00Z", "reason": "source stale"}}
    cards = oc.collapse_demoted_to_uncertainty(demoted, freshness_by_source=fresh)
    assert len(cards) == 1  # three reconcile cards -> one uncertainty card
    assert cards[0].section == oc.SECTION_STATUS_UNCERTAIN
    assert all(c.band == Band.INFO for c in cards)
    # zero of the demoted cards survive as Needs Action
    assert all(c.band != Band.NEEDS_ACTION for c in cards)


def test_collapse_groups_by_source():
    demoted = [
        SimpleNamespace(id="reconcile:new", source=oc.SOURCE_RECONCILE, band=Band.NEEDS_ACTION),
        SimpleNamespace(id="cap:x", source=oc.SOURCE_CAPABILITY, band=Band.NEEDS_ACTION),
    ]
    fresh = {
        oc.SOURCE_RECONCILE: {"evaluated_at": "t1", "reason": "stale"},
        oc.SOURCE_CAPABILITY: {"evaluated_at": "t2", "reason": "eval failed"},
    }
    cards = oc.collapse_demoted_to_uncertainty(demoted, freshness_by_source=fresh)
    assert len(cards) == 2  # one per distinct source
    sources = {c.source for c in cards}
    assert sources == {oc.SOURCE_RECONCILE, oc.SOURCE_CAPABILITY}


def test_architecture_demotes_through_same_builder():
    demoted = [SimpleNamespace(id="architecture:stale", source=oc.SOURCE_ARCHITECTURE, band=Band.NEEDS_ACTION)]
    cards = oc.collapse_demoted_to_uncertainty(
        demoted, freshness_by_source={oc.SOURCE_ARCHITECTURE: {"evaluated_at": "t", "reason": "regen failed"}}
    )
    assert len(cards) == 1
    assert cards[0].source == oc.SOURCE_ARCHITECTURE
    assert cards[0].band == Band.INFO
    assert "regen failed" in (cards[0].detail or "")
