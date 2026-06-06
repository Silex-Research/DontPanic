"""Plan 2026-06-05-004 F005 — advisory plan-review disposition check."""

from __future__ import annotations

from dontpanic_orchestrate.conventions_ledger import LedgerEntry
from dontpanic_orchestrate.plan_review.disposition_check import check_plan_dispositions
from dontpanic_orchestrate.sufficiency_packs import get_pack


def _full_frontend_ledger() -> dict[str, LedgerEntry]:
    return {
        it.id: LedgerEntry(it.id, "applied", evidence="tests/dashboard-journey.test.js")
        for it in get_pack("frontend-ui")
    }


def test_frontend_surface_with_no_dispositions_warns() -> None:
    findings = check_plan_dispositions(declared=["read-only UI"], ledger={})
    assert findings, "a frontend-surface plan with an empty ledger must warn"
    assert all(f.severity == "warn" for f in findings)  # never blocks in v0
    ids = {f.item_id for f in findings}
    assert "design-system-consistency" in ids
    assert "real-shell-journey-proof" in ids


def test_fully_disposed_frontend_plan_is_clean() -> None:
    findings = check_plan_dispositions(
        declared=["read-only UI"], ledger=_full_frontend_ledger()
    )
    assert findings == []


def test_non_surface_plan_is_unaffected() -> None:
    # backend-api is a demand-gated stub (empty pack) -> no warnings even undisposed.
    assert check_plan_dispositions(declared=["backend"], ledger={}) == []
    # no surfaces at all -> nothing.
    assert check_plan_dispositions(declared=[], paths=[], ledger={}) == []


def test_applied_without_evidence_warns() -> None:
    items = get_pack("frontend-ui")
    ledger = {it.id: LedgerEntry(it.id, "applied", evidence="") for it in items}
    findings = check_plan_dispositions(declared=["dashboard"], ledger=ledger)
    assert findings
    assert all(f.status == "applied-without-evidence" for f in findings)
