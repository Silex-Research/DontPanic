"""F006 — operator_triage.write_triage_state writes the model JSON the operator
console reads (one model, many renderers). Verified on the real fleet fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import operator_triage as ot

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "docs/plans/2026-06-06-001-feat-operator-triage-surface-v0"
    / "evidence/fleet-fixture-real.json"
)


def test_write_triage_state_writes_a_readable_model(tmp_path):
    items = json.loads(_FIXTURE.read_text())["items"]
    out = tmp_path / "state" / "operator-triage.json"
    ot.write_triage_state(items, out)
    model = json.loads(out.read_text())
    assert model["schema"] == "operator-triage/v0"
    assert model["data_quality"]["input_count"] == 313  # raw fleet preserved
    assert model["data_quality"]["total"] < 313          # deduped
    assert model["state_revision"]
    assert all("operator_bucket" in i for i in model["items"])


def test_write_triage_state_creates_parent_dirs(tmp_path):
    out = tmp_path / "deep" / "nested" / "operator-triage.json"
    ot.write_triage_state([], out)
    assert out.exists()
    assert json.loads(out.read_text())["item_count"] == 0
