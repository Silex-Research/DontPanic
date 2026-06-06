"""Plan 2026-06-05-004 F006 — wire + dogfood (synthetic AND real-historical)."""

from __future__ import annotations

from pathlib import Path

from dontpanic_orchestrate.conventions_gate import evaluate_plan_dispositions

_DOGFOOD = (
    Path(__file__).resolve().parents[3]
    / "docs/plans/2026-06-05-004-feat-applicable-conventions-disposition-gate-v0"
    / "evidence/dogfood"
)


def test_real_historical_dashboard_plan_would_have_warned() -> None:
    # The faithful representation of the historical dashboard work — NO conventions.json.
    findings = evaluate_plan_dispositions(
        plan_dir=_DOGFOOD / "historical-dashboard-no-disposition",
        declared=["read-only UI"],
    )
    ids = {f.item_id for f in findings}
    # The exact gap that slipped through: design-system + real-shell-journey undisposed.
    assert "design-system-consistency" in ids
    assert "real-shell-journey-proof" in ids
    assert all(f.severity == "warn" for f in findings)  # advisory, never block


def test_synthetic_incomplete_warns_only_on_undisposed_items() -> None:
    findings = evaluate_plan_dispositions(
        plan_dir=_DOGFOOD / "synthetic-incomplete", declared=["dashboard"]
    )
    ids = {f.item_id for f in findings}
    # the two disposed items are clean; the other four warn
    assert "real-shell-journey-proof" not in ids
    assert "design-system-consistency" not in ids
    assert "accessibility-contrast-focus" in ids
    assert "visible-state-coverage" in ids


def test_fully_disposed_plan_is_clean() -> None:
    findings = evaluate_plan_dispositions(
        plan_dir=_DOGFOOD / "fully-disposed", declared=["read-only UI"]
    )
    assert findings == []


def test_matched_skill_becomes_an_expected_ledger_item() -> None:
    # awareness -> accountability: a matched skill the ledger never disposes warns.
    findings = evaluate_plan_dispositions(
        plan_dir=_DOGFOOD / "fully-disposed",
        declared=["read-only UI"],
        matched_skills=["agent-browser"],
    )
    skill_findings = [f for f in findings if f.surface == "skill"]
    assert any(f.item_id == "skill:agent-browser" for f in skill_findings)
    assert all(f.severity == "warn" for f in findings)
