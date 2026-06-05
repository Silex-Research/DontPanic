"""Plan 2026-06-04-005 F003 — per-source freshness.

Freshness moves from 004's snapshot-wide envelope to a per-source stamp, so one
stale or failed producer demotes only ITS OWN cards. Each source resolves
{source, evaluated_at, age, is_stale, eval_ok}; eval_ok=False (recompute
failed/skipped) is distinct from is_stale (old-but-evaluated); an unknown source
fails closed (is_stale=True, eval_ok=False).
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from dontpanic_orchestrate import state_projection as sp

_NOW = dt.datetime(2026, 6, 5, 12, 0, 0, tzinfo=dt.timezone.utc)


def _iso(delta_seconds: float) -> str:
    return (_NOW - dt.timedelta(seconds=delta_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_fresh_source_not_stale():
    em = {"reconcile": {"evaluated_at": _iso(10), "eval_ok": True}}
    f = sp.source_freshness("reconcile", em, now=_NOW)
    assert f["is_stale"] is False
    assert f["eval_ok"] is True
    assert f["age"] is not None and f["age"] >= 0
    assert set(f) >= {"source", "evaluated_at", "age", "is_stale", "eval_ok"}


def test_stale_source_is_stale():
    em = {"reconcile": {"evaluated_at": _iso(1000), "eval_ok": True}}  # > 900 threshold
    f = sp.source_freshness("reconcile", em, now=_NOW)
    assert f["is_stale"] is True
    assert f["eval_ok"] is True  # old, but it DID evaluate


def test_eval_failure_is_distinct_from_staleness():
    # Recompute failed/skipped but the stamp is recent: NOT stale, but not eval_ok.
    em = {"capabilities": {"evaluated_at": _iso(5), "eval_ok": False}}
    f = sp.source_freshness("capabilities", em, now=_NOW)
    assert f["is_stale"] is False
    assert f["eval_ok"] is False


def test_unknown_source_fails_closed():
    f = sp.source_freshness("never-ran", {}, now=_NOW)
    assert f["is_stale"] is True
    assert f["eval_ok"] is False
    assert f["evaluated_at"] is None


def test_mixed_freshness_in_one_snapshot():
    em = {
        "reconcile": {"evaluated_at": _iso(1000), "eval_ok": True},   # stale
        "capabilities": {"evaluated_at": _iso(10), "eval_ok": True},  # fresh
    }
    stale = sp.source_freshness("reconcile", em, now=_NOW)
    fresh = sp.source_freshness("capabilities", em, now=_NOW)
    assert stale["is_stale"] is True
    assert fresh["is_stale"] is False  # sibling not poisoned by the stale source


def test_card_source_freshness_reads_card_source():
    em = {"gate": {"evaluated_at": _iso(5), "eval_ok": True}}
    card = SimpleNamespace(id="g1", source="gate")
    f = sp.card_source_freshness(card, em, now=_NOW)
    assert f["source"] == "gate"
    assert f["is_stale"] is False and f["eval_ok"] is True


def test_negative_age_clamped_on_clock_skew():
    em = {"reconcile": {"evaluated_at": _iso(-30), "eval_ok": True}}  # "future" stamp
    f = sp.source_freshness("reconcile", em, now=_NOW)
    assert f["age"] >= 0
