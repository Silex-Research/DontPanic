"""Plan 2026-06-09-002 F006 — two-level finding identity.

Pins: semantic id stability under rewording (same cell -> same id, new
fingerprint), deterministic same-cell ordinals under auditor output
reordering, severity/class escalation registering as material change, and
the fail-closed cell-invalidation primitive. All pure — no I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.sufficiency_convergence import (  # noqa: E402
    CONSERVATIVE_FALLBACK_CLASS,
    assign_identities,
    cell_fingerprint_sets,
    finding_fingerprint,
    normalize_class,
)


def _finding(**over) -> dict:
    base = {
        "severity": "medium",
        "journey_id": "honest-coverage",
        "gap_class": "coverage_gap",
        "description": "x" * 50,
        "feature_refs": ["F004"],
        "recommendation": "pin the rule",
        "finding_class": "matrix_pin",
    }
    base.update(over)
    return base


# ──────────────────────────────  class fallback  ──────────────────────────────


def test_normalize_class_passes_valid_values():
    assert normalize_class("matrix_pin") == "matrix_pin"
    assert normalize_class("  Editorial ") == "editorial"


def test_normalize_class_conservative_fallback():
    # Operator invariant (D003): missing/invalid classifier data becomes
    # plan_contract — never a disposition-eligible class.
    assert normalize_class(None) == CONSERVATIVE_FALLBACK_CLASS
    assert normalize_class("") == CONSERVATIVE_FALLBACK_CLASS
    assert normalize_class("totally_bogus") == CONSERVATIVE_FALLBACK_CLASS
    assert normalize_class(42) == CONSERVATIVE_FALLBACK_CLASS


# ──────────────────────────────  fingerprint  ──────────────────────────────


def test_fingerprint_covers_severity_and_class():
    base = _finding()
    escalated_sev = _finding(severity="high")
    escalated_cls = _finding(finding_class="plan_contract")
    fp = finding_fingerprint(base)
    assert fp != finding_fingerprint(escalated_sev), "severity escalation must be material"
    assert fp != finding_fingerprint(escalated_cls), "class escalation must be material"


def test_fingerprint_covers_description_and_recommendation():
    fp = finding_fingerprint(_finding())
    assert fp != finding_fingerprint(_finding(description="y" * 50))
    assert fp != finding_fingerprint(_finding(recommendation="different hint"))


# ──────────────────────────────  semantic id  ──────────────────────────────


def test_reworded_single_finding_keeps_id_changes_fingerprint():
    before = assign_identities([_finding()])[0]
    after = assign_identities([_finding(description="z" * 60)])[0]
    assert before["finding_id"] == after["finding_id"], "same cell, single finding -> same id"
    assert before["fingerprint"] != after["fingerprint"], "content change -> new fingerprint"


def test_ordinals_deterministic_under_auditor_reordering():
    a = _finding(description="a" * 50)
    b = _finding(description="b" * 50)
    forward = {f["fingerprint"]: f["finding_id"] for f in assign_identities([a, b])}
    backward = {f["fingerprint"]: f["finding_id"] for f in assign_identities([b, a])}
    assert forward == backward, "output order must not affect identity"


def test_same_cell_collisions_get_distinct_ids():
    a = _finding(description="a" * 50)
    b = _finding(description="b" * 50)
    ids = {f["finding_id"] for f in assign_identities([a, b])}
    assert len(ids) == 2


def test_different_cells_get_different_ids():
    a = _finding()
    b = _finding(journey_id="weak-graph-any-repo")
    c = _finding(feature_refs=["F001"])
    ids = {f["finding_id"] for f in assign_identities([a, b, c])}
    assert len(ids) == 3


# ──────────────────────────────  cell sets  ──────────────────────────────


def test_cell_fingerprint_sets_change_on_any_cell_mutation():
    a = _finding(description="a" * 50)
    b = _finding(description="b" * 50)
    one = cell_fingerprint_sets(assign_identities([a]))
    two = cell_fingerprint_sets(assign_identities([a, b]))
    reworded = cell_fingerprint_sets(assign_identities([_finding(description="c" * 50)]))
    cell = next(iter(one))
    assert one[cell] != two[cell], "insertion changes the cell set"
    assert one[cell] != reworded[cell], "content change changes the cell set"
