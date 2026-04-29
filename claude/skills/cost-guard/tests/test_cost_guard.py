"""Tests for cost-guard skill (F002).

Run from Jarvis repo root:
    PYTHONPATH=. pytest claude/skills/cost-guard/tests/ -q

Fixture-driven; require zero credentials. Public-boundary anchor for F002 acceptance.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("cost_guard", SKILL_DIR / "cost_guard.py")
cost_guard = importlib.util.module_from_spec(spec)
sys.modules["cost_guard"] = cost_guard
assert spec.loader is not None
spec.loader.exec_module(cost_guard)


FIXTURES = SKILL_DIR / "tests" / "fixtures"


def _load(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.is_file() else None


def _load_fixtures(name: str) -> tuple[dict | None, dict | None, dict | None]:
    base = FIXTURES / name
    return _load(base / "costs.json"), _load(base / "quota_state.json"), _load(base / "cost_budgets.json")


def test_nominal_under_threshold_emits_no_findings():
    """Under-threshold burn against configured budgets: zero findings."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs, quota, budgets = _load_fixtures("nominal")
    findings = cost_guard.evaluate(costs=costs, quota=quota, budgets=budgets, as_of=as_of)
    # All ratios are well under 0.80, so no findings should be emitted.
    assert findings == []


def test_warn_emits_cost_warn():
    """Styln MTD 800/28 days × 30 = 857.14 vs 1000 budget = 0.857, in [0.80, 1.00)."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs, quota, budgets = _load_fixtures("warn")
    findings = cost_guard.evaluate(costs=costs, quota=quota, budgets=budgets, as_of=as_of)
    assert len(findings) == 1
    f = findings[0]
    assert f["scope"] == "app:Styln"
    assert f["kind"] == "cost_warn"
    assert 0.80 <= f["ratio"] < 1.00


def test_breach_emits_cost_breach():
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs, quota, budgets = _load_fixtures("breach")
    findings = cost_guard.evaluate(costs=costs, quota=quota, budgets=budgets, as_of=as_of)
    kinds = sorted(f["kind"] for f in findings)
    scopes = sorted(f["scope"] for f in findings)
    assert "cost_breach" in kinds
    assert "app:Styln" in scopes
    # The LLM scope should also fire — 800M tokens used roughly 35h into the week projects
    # well above 1B/week budget. Validate the scope appears.
    assert "llm:claude" in scopes


def test_zero_budget_emits_no_budgets_configured_only():
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs, quota, budgets = _load_fixtures("zero_budget")
    findings = cost_guard.evaluate(costs=costs, quota=quota, budgets=budgets, as_of=as_of)
    assert len(findings) == 1
    assert findings[0]["kind"] == "no_budgets_configured"


def test_stale_short_circuits_to_data_stale():
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs, quota, budgets = _load_fixtures("stale")
    findings = cost_guard.evaluate(costs=costs, quota=quota, budgets=budgets, as_of=as_of)
    assert len(findings) == 1
    assert findings[0]["kind"] == "data_stale"
    # No false-positive breach when both inputs are stale, even though the numbers are 'over budget'.


def test_idempotent_within_week(tmp_path: Path):
    """Re-running with identical inputs in the same calendar week appends zero new entries."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs, quota, budgets = _load_fixtures("breach")
    inbox_dir = tmp_path / "inbox"
    seen = tmp_path / "seen.json"

    findings = cost_guard.evaluate(costs=costs, quota=quota, budgets=budgets, as_of=as_of)
    counts1 = cost_guard.emit_findings(findings, inbox_dir=inbox_dir, seen_state_path=seen, as_of=as_of)
    counts2 = cost_guard.emit_findings(findings, inbox_dir=inbox_dir, seen_state_path=seen, as_of=as_of)

    assert counts1["appended"] >= 1
    assert counts2["appended"] == 0
    assert counts2["skipped_idempotent"] == counts1["appended"]


def test_dedupe_resets_for_new_week(tmp_path: Path):
    """A finding seen in week N must NOT block the same finding in week N+1."""
    as_of_w1 = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)  # Tue of week starting Apr 27
    as_of_w2 = dt.datetime(2026, 5, 5, 12, 0, 0, tzinfo=dt.timezone.utc)   # Tue of week starting May 4
    costs, quota, budgets = _load_fixtures("breach")
    inbox_dir = tmp_path / "inbox"
    seen = tmp_path / "seen.json"

    findings_w1 = cost_guard.evaluate(costs=costs, quota=quota, budgets=budgets, as_of=as_of_w1)
    cost_guard.emit_findings(findings_w1, inbox_dir=inbox_dir, seen_state_path=seen, as_of=as_of_w1)

    findings_w2 = cost_guard.evaluate(costs=costs, quota=quota, budgets=budgets, as_of=as_of_w2)
    counts_w2 = cost_guard.emit_findings(findings_w2, inbox_dir=inbox_dir, seen_state_path=seen, as_of=as_of_w2)
    assert counts_w2["appended"] >= 1


def test_main_writes_inbox_and_exits_zero(tmp_path: Path):
    fixtures = FIXTURES / "breach"
    inbox_dir = tmp_path / "inbox"
    seen = tmp_path / "seen.json"
    rc = cost_guard.main([
        "--fixtures", str(fixtures),
        "--as-of", "2026-04-28T12:00:00Z",
        "--inbox-dir", str(inbox_dir),
        "--seen-state", str(seen),
    ])
    assert rc == 0
    inbox_md = inbox_dir / "INBOX.md"
    assert inbox_md.is_file()
    body = inbox_md.read_text()
    assert "cost_breach" in body
    # Synthetic plan_id is the cost-guard sentinel.
    assert "plan_id: cost-guard" in body


def test_main_zero_budget_exits_zero_with_single_finding(tmp_path: Path):
    fixtures = FIXTURES / "zero_budget"
    inbox_dir = tmp_path / "inbox"
    seen = tmp_path / "seen.json"
    rc = cost_guard.main([
        "--fixtures", str(fixtures),
        "--as-of", "2026-04-28T12:00:00Z",
        "--inbox-dir", str(inbox_dir),
        "--seen-state", str(seen),
    ])
    assert rc == 0
    body = (inbox_dir / "INBOX.md").read_text()
    assert "no_budgets_configured" in body
    assert "cost_breach" not in body


def test_main_stale_inputs_no_breach(tmp_path: Path):
    fixtures = FIXTURES / "stale"
    inbox_dir = tmp_path / "inbox"
    seen = tmp_path / "seen.json"
    rc = cost_guard.main([
        "--fixtures", str(fixtures),
        "--as-of", "2026-04-28T12:00:00Z",
        "--inbox-dir", str(inbox_dir),
        "--seen-state", str(seen),
    ])
    assert rc == 0
    body = (inbox_dir / "INBOX.md").read_text()
    assert "data_stale" in body
    assert "cost_breach" not in body
    assert "cost_warn" not in body


def test_main_invalid_as_of_returns_2():
    rc = cost_guard.main(["--as-of", "not-a-date"])
    assert rc == 2


def test_thresholds_can_be_overridden_via_budget_config():
    """The thresholds field on the budget config takes precedence over defaults."""
    as_of = dt.datetime(2026, 4, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
    costs, quota, budgets = _load_fixtures("warn")
    # Override warn threshold to 0.95 — the same Styln warn at 0.857 should now be quiet.
    budgets["thresholds"] = {"warn": 0.95, "breach": 1.10}
    findings = cost_guard.evaluate(costs=costs, quota=quota, budgets=budgets, as_of=as_of)
    assert findings == []
