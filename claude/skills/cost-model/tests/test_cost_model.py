"""Tests for cost-model skill (F001).

Run from Jarvis repo root with:
    PYTHONPATH=. pytest claude/skills/cost-model/tests/ -q

All tests are fixture-driven and require zero credentials — that is the public-boundary
anchor for F001 acceptance.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

# Import via path injection so we don't have to publish the skill as a package.
import importlib.util
import sys

SKILL_DIR = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("cost_model", SKILL_DIR / "cost_model.py")
cost_model = importlib.util.module_from_spec(spec)
sys.modules["cost_model"] = cost_model
assert spec.loader is not None
spec.loader.exec_module(cost_model)


FIXTURES = SKILL_DIR / "tests" / "fixtures"


def _load(p: Path) -> dict | None:
    if not p.is_file():
        return None
    return json.loads(p.read_text())


def test_nominal_with_revenue_produces_with_revenue_mode():
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs = _load(FIXTURES / "nominal" / "costs.json")
    quota = _load(FIXTURES / "nominal" / "quota_state.json")
    revenue = _load(FIXTURES / "nominal" / "revenue.json")
    report = cost_model.build_report(costs=costs, quota=quota, revenue=revenue, as_of=as_of)
    assert report["mode"] == "with-revenue"
    assert "Styln" in report["by_app"]
    styln = report["by_app"]["Styln"]
    # April: 30 days, day 28; daily rate = 233.44 / 28 = 8.337142857142857
    assert styln["mtd_usd"] == 233.44
    assert styln["days_into_month"] == 28
    assert styln["days_in_month"] == 30
    assert styln["projected_month_end_usd"] == round(233.44 / 28 * 30, 2)
    # Next month is May (31 days)
    assert styln["projected_next_month_usd"] == round(233.44 / 28 * 31, 2)
    assert styln["monthly_revenue_usd"] == 850.00
    assert styln["projected_net_month_end_usd"] == round(850.00 - styln["projected_month_end_usd"], 2)


def test_no_revenue_falls_back_to_cost_only():
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs = _load(FIXTURES / "nominal" / "costs.json")
    quota = _load(FIXTURES / "nominal" / "quota_state.json")
    report = cost_model.build_report(costs=costs, quota=quota, revenue=None, as_of=as_of)
    assert report["mode"] == "cost-only"
    assert "monthly_revenue_usd" not in report["by_app"]["Styln"]


def test_empty_inputs_yields_data_unavailable_and_exit_zero():
    """The empty-fixture set has no JSON files. cost-model must not raise — it must
    emit a structured `data_unavailable` report and exit 0. This is the fresh-clone
    contract: the skill is safe to run before refresh-costs.sh / quota_check.py have
    ever been executed."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    report = cost_model.build_report(costs=None, quota=None, revenue=None, as_of=as_of)
    assert report["mode"] == "data_unavailable"
    assert report["by_app"] == {}
    assert report["by_llm"] == {}


def test_stale_inputs_emit_note_but_still_render():
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs = _load(FIXTURES / "stale" / "costs.json")
    quota = _load(FIXTURES / "stale" / "quota_state.json")
    report = cost_model.build_report(costs=costs, quota=quota, revenue=None, as_of=as_of)
    assert any("stale" in n for n in report["notes"])
    # Even with stale data, projections still render (operator decides).
    assert "Styln" in report["by_app"]


def test_zero_spend_app_has_zero_projection():
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs = _load(FIXTURES / "nominal" / "costs.json")
    report = cost_model.build_report(costs=costs, quota=None, revenue=None, as_of=as_of)
    qra = report["by_app"]["QuantRE/Axiom"]
    assert qra["mtd_usd"] == 0.0
    assert qra["projected_month_end_usd"] == 0.0
    assert qra["projected_next_month_usd"] == 0.0


def test_end_of_month_projection_equals_mtd():
    """On the last day of the month, projected_month_end should equal MTD (no extrapolation
    beyond observed days). This is a sanity check on the daily-rate × days-in-month formula."""
    as_of = dt.datetime(2026, 4, 30, 23, 0, 0, tzinfo=dt.timezone.utc)
    costs = _load(FIXTURES / "nominal" / "costs.json")
    report = cost_model.build_report(costs=costs, quota=None, revenue=None, as_of=as_of)
    styln = report["by_app"]["Styln"]
    # MTD treated as 30-day total at this point.
    assert styln["projected_month_end_usd"] == 233.44


def test_llm_projection_handles_unmetered_models():
    """Ollama is unmetered (limit=null). The projection must not crash on null limits and
    must report None for percent-of-cap."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    quota = _load(FIXTURES / "nominal" / "quota_state.json")
    report = cost_model.build_report(costs=None, quota=quota, revenue=None, as_of=as_of)
    ollama = report["by_llm"]["ollama"]
    assert ollama["limit"] is None
    assert ollama["percent_of_cap_week_end"] is None
    assert ollama["percent_of_cap_monthly"] is None


def test_render_markdown_is_deterministic_for_fixed_as_of():
    """Same inputs + same as_of must produce byte-identical markdown. This is what makes
    golden-output diffing possible in fresh-clone CI."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs = _load(FIXTURES / "nominal" / "costs.json")
    quota = _load(FIXTURES / "nominal" / "quota_state.json")
    revenue = _load(FIXTURES / "nominal" / "revenue.json")
    r1 = cost_model.build_report(costs=costs, quota=quota, revenue=revenue, as_of=as_of)
    r2 = cost_model.build_report(costs=costs, quota=quota, revenue=revenue, as_of=as_of)
    assert cost_model.render_markdown(r1) == cost_model.render_markdown(r2)


def test_main_writes_outputs_and_exits_zero(tmp_path: Path):
    fixtures = FIXTURES / "nominal"
    rc = cost_model.main([
        "--fixtures", str(fixtures),
        "--as-of", "2026-04-28T12:00:00Z",
        "--out", str(tmp_path),
    ])
    assert rc == 0
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1
    files = sorted(p.name for p in runs[0].iterdir())
    assert any(f.endswith(".md") for f in files)
    assert any(f.endswith(".json") for f in files)


def test_main_with_no_inputs_exits_zero_and_writes_data_unavailable(tmp_path: Path):
    """Fresh-clone smoke: invoke with --fixtures pointing to an empty dir."""
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = cost_model.main([
        "--fixtures", str(empty),
        "--as-of", "2026-04-28T12:00:00Z",
        "--out", str(tmp_path / "out"),
    ])
    assert rc == 0
    out_files = list((tmp_path / "out").rglob("*.json"))
    assert out_files
    payload = json.loads(out_files[0].read_text())
    assert payload["mode"] == "data_unavailable"


def test_invalid_as_of_returns_2():
    rc = cost_model.main(["--as-of", "not-a-date", "--fixtures", str(FIXTURES / "nominal")])
    assert rc == 2


@pytest.mark.parametrize(
    "month,day,expected_dim,expected_next_dim",
    [
        (1, 15, 31, 28),   # Jan 15, 2026 → Jan has 31, Feb 2026 has 28
        (2, 1, 28, 31),    # Feb 1 → Feb 28, Mar 31
        (12, 31, 31, 31),  # Dec 31 → Dec 31, Jan 31
    ],
)
def test_calendar_month_lengths(month, day, expected_dim, expected_next_dim):
    as_of = dt.datetime(2026, month, day, 12, 0, 0, tzinfo=dt.timezone.utc)
    entry = cost_model.project_app_gcp(mtd_usd=100.0, as_of=as_of)
    assert entry["days_in_month"] == expected_dim
    expected_next_proj = round(100.0 / day * expected_next_dim, 2)
    assert entry["projected_next_month_usd"] == expected_next_proj
