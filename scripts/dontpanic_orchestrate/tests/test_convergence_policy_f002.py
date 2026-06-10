"""Plan 2026-06-09-002 F002 — pure convergence policy.

Pins all four branches, purity, and the exhaustive severity x class verdict
matrix including advisory and the unclassified -> plan_contract fallback.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.sufficiency_convergence import (  # noqa: E402
    FINDING_CLASSES,
    SEVERITIES,
    VERDICT_BLOCK,
    VERDICT_DISPOSITION_REQUIRED,
    VERDICT_PLAIN_GATE,
    VERDICT_PROCEED,
    ConvergenceError,
    build_round_record,
    convergence_verdict,
    verdict_for,
)


def _finding(journey: str, desc: str, severity: str = "medium", cls: str = "matrix_pin"):
    return {
        "severity": severity,
        "journey_id": journey,
        "gap_class": "coverage_gap",
        "description": desc * 10,
        "feature_refs": ["F004"],
        "recommendation": None,
        "finding_class": cls,
    }


def _ledger(*rounds_findings: list[dict]) -> list[dict]:
    """Build an in-memory ledger from successive finding lists."""
    ledger: list[dict] = []
    prior = None
    for i, findings in enumerate(rounds_findings, start=1):
        record = build_round_record(
            findings, prior=prior, input_fingerprint=f"sha256:{i}", round_number=i
        )
        ledger.append(record)
        prior = record
    return ledger


def _dispose(ledger: list[dict], kind: str = "deferred_to_impl") -> dict[str, dict]:
    current = ledger[-1]
    return {
        f["finding_id"]: {"kind": kind, "fingerprint": f["fingerprint"]}
        for f in current["findings"]
    }


# ──────────────────────────────  branches  ──────────────────────────────


def test_branch_d_first_round_plain_gate():
    ledger = _ledger([_finding("a", "x", "medium", "matrix_pin")])
    v = convergence_verdict(ledger, {})
    assert v.verdict == VERDICT_PLAIN_GATE
    assert v.branch == "d_first_round"


def test_branch_b_high_blocks_even_with_full_clearance():
    ledger = _ledger(
        [_finding("a", "x")],
        [_finding("b", "y", severity="high", cls="matrix_pin")],
    )
    v = convergence_verdict(ledger, {})
    assert v.verdict == VERDICT_BLOCK
    assert v.branch == "b_high_severity"


def test_branch_b_high_not_suppressible_by_disposition():
    ledger = _ledger(
        [_finding("a", "x")],
        [_finding("b", "y", severity="high", cls="matrix_pin")],
    )
    v = convergence_verdict(ledger, _dispose(ledger, "deferred_to_impl"))
    assert v.verdict == VERDICT_BLOCK, "high severity keeps the plain hard block"


def test_branch_c_plan_contract_blocks_unless_waived():
    ledger = _ledger(
        [_finding("a", "x")],
        [_finding("b", "y", severity="medium", cls="plan_contract")],
    )
    blocked = convergence_verdict(ledger, _dispose(ledger, "deferred_to_impl"))
    assert blocked.verdict == VERDICT_BLOCK
    assert blocked.branch == "c_plan_contract"
    waived = convergence_verdict(ledger, _dispose(ledger, "waived_with_reason"))
    assert waived.verdict == VERDICT_PROCEED


def test_branch_a_full_clearance_pins_demand_disposition():
    ledger = _ledger(
        [_finding("a", "x")],
        [
            _finding("b", "y", "medium", "matrix_pin"),
            _finding("c", "z", "low", "editorial"),
            _finding("d", "w", "advisory", "scope_guard"),
            _finding("e", "v", "medium", "implementation_detail"),
        ],
    )
    v = convergence_verdict(ledger, {})
    assert v.verdict == VERDICT_DISPOSITION_REQUIRED
    assert v.branch == "a_full_clearance_pins"
    assert v.undisposed_ids, "the verdict names the findings awaiting disposition"


def test_branch_a_requires_full_clearance():
    persisted = _finding("a", "x", "medium", "matrix_pin")
    ledger = _ledger([persisted], [persisted, _finding("b", "y", "medium", "editorial")])
    v = convergence_verdict(ledger, {})
    assert v.verdict == VERDICT_BLOCK, "no full clearance -> plain block, not disposition"


def test_proceed_when_all_blocking_disposed_no_audit_kinds():
    ledger = _ledger(
        [_finding("a", "x")],
        [_finding("b", "y", "medium", "matrix_pin")],
    )
    v = convergence_verdict(ledger, _dispose(ledger, "split_to_followup_plan"))
    assert v.verdict == VERDICT_PROCEED
    assert v.branch == "resolved_by_disposition"


def test_accepted_into_plan_never_suppresses():
    ledger = _ledger(
        [_finding("a", "x")],
        [_finding("b", "y", "medium", "matrix_pin")],
    )
    v = convergence_verdict(ledger, _dispose(ledger, "accepted_into_plan"))
    assert v.verdict != VERDICT_PROCEED, "accepted_into_plan demands a plan edit + fresh audit"


def test_policy_is_pure():
    ledger = _ledger([_finding("a", "x")], [_finding("b", "y", "medium", "matrix_pin")])
    d = _dispose(ledger)
    assert convergence_verdict(ledger, d) == convergence_verdict(ledger, d)


# ──────────────────────────────  exhaustive matrix  ──────────────────────────────


def test_matrix_exhaustive_over_severity_x_class():
    cases = [(s, c) for s in SEVERITIES for c in (*FINDING_CLASSES, None, "bogus")]
    for severity, cls in cases:
        verdict = verdict_for(severity, cls)
        assert verdict in {"pass", "block", "block_unless_waived", "disposition_eligible"}, (
            severity,
            cls,
        )


def test_matrix_pins():
    # advisory/low never hard-block on their own (matches the existing gate).
    assert verdict_for("advisory", "plan_contract") == "pass"
    assert verdict_for("low", "matrix_pin") == "pass"
    # high/critical always block.
    assert verdict_for("high", "editorial") == "block"
    assert verdict_for("critical", "matrix_pin") == "block"
    # medium splits on class; unclassified falls back to plan_contract.
    assert verdict_for("medium", "matrix_pin") == "disposition_eligible"
    assert verdict_for("medium", "scope_guard") == "disposition_eligible"
    assert verdict_for("medium", "plan_contract") == "block_unless_waived"
    assert verdict_for("medium", None) == "block_unless_waived"
    assert verdict_for("medium", "garbage") == "block_unless_waived"


def test_matrix_rejects_unknown_severity():
    with pytest.raises(ConvergenceError):
        verdict_for("catastrophic", "matrix_pin")
