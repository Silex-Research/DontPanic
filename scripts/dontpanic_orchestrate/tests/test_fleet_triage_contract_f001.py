"""Fleet build/state contract — plan 2026-06-06-005 F001.

The DEFAULT dashboard view is All-Projects (fleet). Before this, the fleet build emitted only
fleet-what-now.json — no fleet-level operator-triage.json — so the redesigned Cockpit's default
view had no operator-triage/v0 model to read. These tests pin the contract on the GENERATED
file (not a fixture): the fleet build emits a sibling operator-triage.json, it is operator-triage/v0,
its items carry the F001 fields, and it is the SAME item set as fleet-what-now.json.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from dontpanic_orchestrate import projects_dashboard as pd

NEW_FIELDS = {"resolution", "asserted_at", "freshness_basis", "provenance_source"}


def _build_fleet(tmp_path):
    out = tmp_path / "fleet-what-now.json"
    pd.build_fleet_what_now([], output_path=out)  # empty reports → still gathers install-level items
    return out, out.parent / pd.FLEET_TRIAGE_FILENAME


def test_fleet_build_emits_sibling_operator_triage_v0(tmp_path):
    _wn, triage = _build_fleet(tmp_path)
    assert triage.is_file(), "fleet build MUST emit a sibling operator-triage.json (the default Cockpit model)"
    model = json.loads(triage.read_text(encoding="utf-8"))
    assert model.get("schema") == "operator-triage/v0"
    assert isinstance(model.get("items"), list)
    assert model.get("state_revision")  # the model is a real, fingerprinted triage envelope


def test_generated_fleet_triage_items_carry_the_F001_fields(tmp_path):
    _wn, triage = _build_fleet(tmp_path)
    model = json.loads(triage.read_text(encoding="utf-8"))
    for it in model["items"]:
        assert NEW_FIELDS <= set(it), f"generated item missing F001 fields: {sorted(NEW_FIELDS - set(it))}"


def test_fleet_triage_is_the_same_item_set_as_fleet_what_now(tmp_path):
    wn, triage = _build_fleet(tmp_path)
    wn_ids = {i.get("id") for i in json.loads(wn.read_text())["items"]}
    tr_ids = {i.get("id") for i in json.loads(triage.read_text())["items"]}
    assert tr_ids == wn_ids, "the fleet triage model must be the SAME items as fleet-what-now (one model, many renderers)"


def test_mirror_copies_fleet_triage_into_served_state_dir(tmp_path, monkeypatch):
    # the served dashboard reads state/operator-triage.json — the mirror must put it there.
    home_dash = tmp_path / "home" / "dashboard"
    home_dash.mkdir(parents=True)
    (home_dash / pd.FLEET_WHAT_NOW_FILENAME).write_text('{"items":[]}', encoding="utf-8")
    (home_dash / pd.FLEET_TRIAGE_FILENAME).write_text(
        '{"schema":"operator-triage/v0","items":[],"state_revision":"x"}', encoding="utf-8")
    monkeypatch.setattr(pd, "fleet_what_now_path", lambda: home_dash / pd.FLEET_WHAT_NOW_FILENAME)

    served = tmp_path / "served-state"
    # mirror only reads .selection.kind (non-"current_repo"), .fleet_summary_path, .project_reports
    result = SimpleNamespace(
        selection=SimpleNamespace(kind="all"),
        project_reports=(),
        fleet_summary_path=None,
    )
    pd.mirror_selection_into_state_dir(result, state_out_dir=served)
    assert (served / pd.FLEET_TRIAGE_FILENAME).is_file(), "serve path must mirror state/operator-triage.json"
