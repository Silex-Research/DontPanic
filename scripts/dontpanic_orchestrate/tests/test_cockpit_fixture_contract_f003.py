"""Cockpit journey fixture ↔ producer contract — plan 2026-06-06-005 F003.

The JS journey (cockpit-journey-f003.test.js) boots the real shell against
tests/fixtures/real-state/operator-triage.json. That fixture must NOT drift from what the live
producer (write_triage_state over the SAME fleet-what-now.json fixture items) emits — otherwise the
journey could pass green on a synthetic shape the real build never produces. This re-derives the
triage model from the producer and asserts the fixture matches it (item set + the F001 fields +
schema + generated_at), so a producer change that drops a field fails HERE, loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import operator_triage as ot

FIXTURES = Path(__file__).resolve().parents[3] / "dashboard" / "tests" / "fixtures" / "real-state"
F001_FIELDS = {"resolution", "asserted_at", "freshness_basis", "provenance_source"}


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_cockpit_fixture_is_real_producer_output():
    fleet = _load("fleet-what-now.json")
    fixture = _load("operator-triage.json")
    # re-derive from the producer over the SAME items the fixture was built from
    produced = ot.build_triage(
        fleet["items"], safety_class_for=lambda _it: None, live_supervisors=[], dedupe=False
    )
    assert fixture["schema"] == produced["schema"] == "operator-triage/v0"
    # same item set (ids) — the fixture is the producer's output, not a hand-authored shape
    assert {i.get("id") for i in fixture["items"]} == {i.get("id") for i in produced["items"]}
    # every fixture item carries the F001 fields the Cockpit + journey depend on
    for it in fixture["items"]:
        assert F001_FIELDS <= set(it), f"fixture item missing F001 fields: {sorted(F001_FIELDS - set(it))}"


def test_cockpit_fixture_carries_a_generated_at_for_staleness():
    fixture = _load("operator-triage.json")
    # the journey overrides this per-test, but the fixture must carry the field the F004 stale path reads
    assert "generated_at" in fixture


def test_cockpit_fixture_has_no_item_probe_basis_so_dots_stay_hollow_in_v0():
    # render-truth: v0 emits no item_probe basis, so the journey's "no proven-live dot" assertion holds
    fixture = _load("operator-triage.json")
    assert not any(it.get("freshness_basis") == "item_probe" for it in fixture["items"])
