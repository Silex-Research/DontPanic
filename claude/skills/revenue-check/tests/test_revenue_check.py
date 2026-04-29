"""Tests for revenue-check skill (F003).

Run from Jarvis repo root:
    PYTHONPATH=. pytest claude/skills/revenue-check/tests/ -q

Fixture-driven and creds-free. Live Firestore path is documented but not exercised here.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("revenue_check", SKILL_DIR / "revenue_check.py")
revenue_check = importlib.util.module_from_spec(spec)
sys.modules["revenue_check"] = revenue_check
assert spec.loader is not None
spec.loader.exec_module(revenue_check)


FIXTURES = SKILL_DIR / "tests" / "fixtures"


def test_fixture_adapter_aggregates_finalized_and_estimated_only():
    """The fixture has finalized 320.50 + estimated 180.00 + pending 50 + refunded -30 in April.
    Only finalized + estimated count → 500.50. The March row is in a different month → ignored."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    adapter = revenue_check.FixtureAdapter(FIXTURES / "nominal")
    result = adapter.fetch("Styln", as_of)
    assert result.monthly_revenue_usd == 500.50
    assert result.source == "fixture"
    assert result.granularity == "monthly"
    # last_event_at is the max across the matching rows.
    assert result.last_event_at == "2026-04-27T22:00:00Z"


def test_fixture_adapter_zero_revenue_month():
    """No April rows — total is 0.0, not None."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    adapter = revenue_check.FixtureAdapter(FIXTURES / "zero_revenue")
    result = adapter.fetch("Styln", as_of)
    assert result.monthly_revenue_usd == 0.0
    assert result.last_event_at is None


def test_fixture_adapter_missing_fixture_returns_none():
    """No fixture file for the requested app — source flagged but no crash."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    adapter = revenue_check.FixtureAdapter(FIXTURES / "missing")
    result = adapter.fetch("Styln", as_of)
    assert result.monthly_revenue_usd is None
    assert result.source.startswith("fixture:missing")


def test_deferred_adapter_returns_unavailable_with_reason():
    """SpinDine is deferred — D001. The DeferredAdapter must report the deferral cleanly."""
    adapter = revenue_check.DeferredAdapter("StoreKit 2 / App Store Connect — no Firestore mirror")
    result = adapter.fetch("Spin & Dine", dt.datetime.now(dt.timezone.utc))
    assert result.monthly_revenue_usd is None
    assert "unavailable" in result.source
    assert "App Store Connect" in result.source


def test_resolve_adapter_picks_glam_for_styln_in_live_mode():
    a = revenue_check.resolve_adapter("Styln", stub=False, fixtures_root=None)
    assert isinstance(a, revenue_check.GlamLedgerAdapter)


def test_resolve_adapter_picks_deferred_for_spindine_in_live_mode():
    a = revenue_check.resolve_adapter("Spin & Dine", stub=False, fixtures_root=None)
    assert isinstance(a, revenue_check.DeferredAdapter)


def test_resolve_adapter_picks_fixture_when_stub_set():
    a = revenue_check.resolve_adapter("Styln", stub=True, fixtures_root=FIXTURES / "nominal")
    assert isinstance(a, revenue_check.FixtureAdapter)


def test_build_revenue_state_shape():
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    adapters = {"Styln": revenue_check.FixtureAdapter(FIXTURES / "nominal")}
    state = revenue_check.build_revenue_state(apps=["Styln"], adapter_for=adapters, as_of=as_of)
    assert state["generated"] == "2026-04-28T12:00:00Z"
    assert "Styln" in state["by_app"]
    s = state["by_app"]["Styln"]
    assert s["monthly_revenue_usd"] == 500.50
    assert s["granularity"] == "monthly"


def test_render_cash_flow_computes_net():
    """net = revenue (500.50) − GCP MTD (233.44) = 267.06."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    revenue = {
        "generated": "2026-04-28T12:00:00Z",
        "by_app": {"Styln": {"monthly_revenue_usd": 500.50, "source": "fixture", "granularity": "monthly", "last_event_at": None}},
    }
    costs = {"totals": {"Styln": 233.44, "Total": 233.44}}
    report = revenue_check.render_cash_flow(revenue=revenue, costs=costs, as_of=as_of)
    assert report["by_app"]["Styln"]["mtd_net_usd"] == 267.06


def test_render_cash_flow_handles_missing_cost_gracefully():
    """If costs.json is absent, mtd_net_usd is None rather than a crash."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    revenue = {
        "generated": "2026-04-28T12:00:00Z",
        "by_app": {"Styln": {"monthly_revenue_usd": 500.50, "source": "fixture", "granularity": "monthly", "last_event_at": None}},
    }
    report = revenue_check.render_cash_flow(revenue=revenue, costs=None, as_of=as_of)
    assert report["by_app"]["Styln"]["mtd_net_usd"] is None


def test_main_stub_writes_revenue_json_and_evidence(tmp_path: Path):
    out = tmp_path / "rev.json"
    evidence = tmp_path / "evidence"
    rc = revenue_check.main([
        "--stub",
        "--fixtures", str(FIXTURES / "nominal"),
        "--apps", "Styln",
        "--out", str(out),
        "--evidence-dir", str(evidence),
        "--costs", str(FIXTURES / "_no_such_costs_file.json"),
        "--as-of", "2026-04-28T12:00:00Z",
    ])
    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["by_app"]["Styln"]["monthly_revenue_usd"] == 500.50
    cash_flow_files = list(evidence.rglob("cash-flow-*.json"))
    assert len(cash_flow_files) == 1


def test_main_refuses_live_without_explicit_flag():
    """Fresh-clone safety: running with no flags must not silently issue a Firestore call.
    Operator opts in via --stub for tests or by supplying a fixture path."""
    rc = revenue_check.main(["--apps", "Styln", "--as-of", "2026-04-28T12:00:00Z"])
    assert rc == 2


def test_main_live_flag_reaches_deferred_adapter_without_credentials(tmp_path: Path):
    """The CLI must expose live mode explicitly, while this test stays no-network by using
    the deferred SpinDine adapter rather than Glam's Firestore adapter."""
    out = tmp_path / "rev.json"
    evidence = tmp_path / "evidence"
    rc = revenue_check.main([
        "--live",
        "--apps", "Spin & Dine",
        "--out", str(out),
        "--evidence-dir", str(evidence),
        "--as-of", "2026-04-28T12:00:00Z",
    ])
    assert rc == 0
    payload = json.loads(out.read_text())
    sd = payload["by_app"]["Spin & Dine"]
    assert sd["monthly_revenue_usd"] is None
    assert "App Store Connect" in sd["source"]


def test_main_rejects_stub_and_live_together():
    rc = revenue_check.main([
        "--stub",
        "--live",
        "--fixtures", str(FIXTURES / "nominal"),
        "--as-of", "2026-04-28T12:00:00Z",
    ])
    assert rc == 2


def test_main_invalid_as_of_returns_2():
    rc = revenue_check.main(["--stub", "--fixtures", str(FIXTURES / "nominal"), "--as-of", "not-a-date"])
    assert rc == 2


def test_main_handles_spindine_deferral_in_stub_mode_gracefully(tmp_path: Path):
    """In stub mode, SpinDine routes through FixtureAdapter — if no fixture exists, it reports
    fixture:missing rather than going through the live Deferred path. Either way: no crash."""
    out = tmp_path / "rev.json"
    evidence = tmp_path / "evidence"
    rc = revenue_check.main([
        "--stub",
        "--fixtures", str(FIXTURES / "nominal"),
        "--apps", "Styln,Spin & Dine",
        "--out", str(out),
        "--evidence-dir", str(evidence),
        "--as-of", "2026-04-28T12:00:00Z",
    ])
    assert rc == 0
    payload = json.loads(out.read_text())
    assert "Styln" in payload["by_app"]
    assert "Spin & Dine" in payload["by_app"]
    sd = payload["by_app"]["Spin & Dine"]
    # No fixture for Spin & Dine in the nominal set, so fixture:missing.
    assert sd["monthly_revenue_usd"] is None
    assert sd["source"].startswith("fixture:missing") or "unavailable" in sd["source"]
