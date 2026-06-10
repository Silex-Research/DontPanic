"""Plan 2026-06-09-002 F001 — append-only sufficiency rounds ledger.

Pins: rounds appended only via the auditor path, clearance accounting by
finding_id against the prior round, conservative class fallback, append-only
reconstruction, and the override_used event shape.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.sufficiency_convergence import (  # noqa: E402
    ROUNDS_LEDGER_ARTIFACT,
    append_audit_round,
    append_override_event,
    audit_rounds,
    build_round_record,
    full_clearance,
    latest_round,
    read_ledger,
)


def _finding(journey: str, desc: str, severity: str = "medium", cls: str | None = "matrix_pin"):
    return {
        "severity": severity,
        "journey_id": journey,
        "gap_class": "coverage_gap",
        "description": desc * 10,
        "feature_refs": ["F004"],
        "recommendation": None,
        "finding_class": cls,
    }


@pytest.fixture()
def plan_dir(tmp_path: Path) -> Path:
    d = tmp_path / "plan"
    d.mkdir()
    return d


def _ledger_file(plan_dir: Path) -> Path:
    return plan_dir / "evidence" / "goal-governance" / "pre_impl" / ROUNDS_LEDGER_ARTIFACT


def test_append_creates_jsonl_and_numbers_rounds(plan_dir: Path):
    r1 = append_audit_round(plan_dir, [_finding("a", "one")], input_fingerprint="sha256:1")
    r2 = append_audit_round(plan_dir, [_finding("b", "two")], input_fingerprint="sha256:2")
    assert r1["round"] == 1 and r2["round"] == 2
    lines = _ledger_file(plan_dir).read_text().strip().splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["type"] == "audit_round" for line in lines)


def test_clearance_accounting_by_finding_id(plan_dir: Path):
    append_audit_round(
        plan_dir,
        [_finding("a", "one"), _finding("b", "two")],
        input_fingerprint="sha256:1",
    )
    # Round 2 keeps journey-a's finding VERBATIM (persists) and replaces b's.
    r2 = append_audit_round(
        plan_dir,
        [_finding("a", "one"), _finding("c", "three")],
        input_fingerprint="sha256:2",
    )
    assert len(r2["persisted_ids"]) == 1
    assert len(r2["cleared_ids"]) == 1
    assert r2["prior_finding_count"] == 2
    assert not full_clearance(r2)


def test_full_clearance_detection(plan_dir: Path):
    append_audit_round(plan_dir, [_finding("a", "one")], input_fingerprint="sha256:1")
    r2 = append_audit_round(plan_dir, [_finding("b", "two")], input_fingerprint="sha256:2")
    assert full_clearance(r2)
    # A first round can never be a full clearance — there is no prior.
    first = build_round_record(
        [_finding("a", "x")], prior=None, input_fingerprint="sha256:0", round_number=1
    )
    assert not full_clearance(first)


def test_conservative_class_fallback_in_ledger(plan_dir: Path):
    record = append_audit_round(
        plan_dir,
        [_finding("a", "one", cls=None), _finding("b", "two", cls="nonsense")],
        input_fingerprint="sha256:1",
    )
    classes = {f["finding_class"] for f in record["findings"]}
    assert classes == {"plan_contract"}, "missing/invalid class must fall back to plan_contract"


def test_ledger_reconstructable_and_append_only(plan_dir: Path):
    append_audit_round(plan_dir, [_finding("a", "one")], input_fingerprint="sha256:1")
    append_override_event(plan_dir, reason="operator says so", approved_by="op")
    append_audit_round(plan_dir, [_finding("b", "two")], input_fingerprint="sha256:2")
    ledger = read_ledger(plan_dir)
    assert [r["type"] for r in ledger] == ["audit_round", "override_used", "audit_round"]
    assert len(audit_rounds(ledger)) == 2
    assert latest_round(ledger)["round"] == 2
    override = ledger[1]
    assert override["reason"] == "operator says so"
    assert override["approved_by"] == "op"


def test_disposition_resolution_pass_appends_nothing(plan_dir: Path):
    """The gate's disposition-resolution path reads the ledger but never
    appends an audit round — only run_sufficiency_audit appends. Here we
    assert read paths leave the file untouched."""
    append_audit_round(plan_dir, [_finding("a", "one")], input_fingerprint="sha256:1")
    before = _ledger_file(plan_dir).read_text()
    from dontpanic_orchestrate.sufficiency_convergence import gate_decision

    gate_decision(plan_dir)
    assert _ledger_file(plan_dir).read_text() == before
