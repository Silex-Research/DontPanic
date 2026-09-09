"""Global breaker threshold must be fleet-configurable via env.

Operators running multiple concurrent plans (multi-project fleets) need to
size the global iteration_cap threshold; the hardcoded 3 assumes a single
active project. JARVIS_GLOBAL_BREAKER_THRESHOLD overrides the default;
invalid values fall back to the default; an explicit kwarg always wins.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from dontpanic_orchestrate import circuit_breakers as cb


def _write_hits(path, count: int) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    lines = [
        json.dumps(
            {
                "plan_id": f"plan-{i}",
                "kind": "iteration_cap",
                "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        for i in range(count)
    ]
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def history(tmp_path, monkeypatch):
    path = tmp_path / "breaker_history.jsonl"
    monkeypatch.setenv("JARVIS_BREAKER_HISTORY_PATH", str(path))
    monkeypatch.delenv("JARVIS_GLOBAL_BREAKER_THRESHOLD", raising=False)
    return path


def test_default_threshold_unchanged_without_env(history):
    _write_hits(history, 2)
    assert cb.evaluate_global().tripped is False
    _write_hits(history, 3)
    state = cb.evaluate_global()
    assert state.tripped is True
    assert state.threshold == cb.GLOBAL_THRESHOLD_HITS


def test_env_raises_threshold_for_fleet(history, monkeypatch):
    monkeypatch.setenv("JARVIS_GLOBAL_BREAKER_THRESHOLD", "9")
    _write_hits(history, 3)
    state = cb.evaluate_global()
    assert state.tripped is False
    assert state.threshold == 9
    _write_hits(history, 9)
    assert cb.evaluate_global().tripped is True


@pytest.mark.parametrize("bad", ["abc", "", "0", "-2", "3.5"])
def test_invalid_env_falls_back_to_default(history, monkeypatch, bad):
    monkeypatch.setenv("JARVIS_GLOBAL_BREAKER_THRESHOLD", bad)
    _write_hits(history, 3)
    state = cb.evaluate_global()
    assert state.threshold == cb.GLOBAL_THRESHOLD_HITS
    assert state.tripped is True


def test_explicit_kwarg_wins_over_env(history, monkeypatch):
    monkeypatch.setenv("JARVIS_GLOBAL_BREAKER_THRESHOLD", "9")
    _write_hits(history, 2)
    state = cb.evaluate_global(threshold=2)
    assert state.threshold == 2
    assert state.tripped is True


def _write_hits_at_times(path, timestamps: list[dt.datetime]) -> None:
    """Write hits at specific timestamps for release_at testing."""
    lines = [
        json.dumps(
            {
                "plan_id": f"plan-{i}",
                "kind": "iteration_cap",
                "at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        for i, ts in enumerate(timestamps)
    ]
    path.write_text("\n".join(lines) + "\n")


def test_release_at_is_threshold_crossing_expiry_not_oldest(history):
    """Plan 2026-09-09-001 F001: release_at must be the threshold-crossing
    hit's expiry, not the oldest hit's expiry.

    Scenario from operator-review.md: 4 hits at 08:00, 09:00, 10:00, 11:00
    with threshold 3 and a 24-hour window.

    At 08:00+24h, 3 hits remain (09:00, 10:00, 11:00) → still tripped.
    At 09:00+24h, 2 hits remain (10:00, 11:00) → no longer tripped.

    So release_at = 09:00 + 24h, NOT 08:00 + 24h.
    """
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    window_seconds = 24 * 3600
    h08 = now - dt.timedelta(hours=3)
    h09 = now - dt.timedelta(hours=2)
    h10 = now - dt.timedelta(hours=1)
    h11 = now
    _write_hits_at_times(history, [h08, h09, h10, h11])
    state = cb.evaluate_global(threshold=3, window_seconds=window_seconds)
    assert state.tripped is True
    assert state.hits_in_window == 4
    assert state.release_at is not None
    expected_release = h09 + dt.timedelta(seconds=window_seconds)
    assert state.release_at == expected_release, (
        f"release_at should be {expected_release} (threshold-crossing hit at {h09}), "
        f"not {h08 + dt.timedelta(seconds=window_seconds)} (oldest hit)"
    )


def test_release_at_exact_threshold(history):
    """When hits == threshold, the oldest hit is the threshold-crossing hit."""
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    window_seconds = 24 * 3600
    h08 = now - dt.timedelta(hours=2)
    h09 = now - dt.timedelta(hours=1)
    h10 = now
    _write_hits_at_times(history, [h08, h09, h10])
    state = cb.evaluate_global(threshold=3, window_seconds=window_seconds)
    assert state.tripped is True
    assert state.hits_in_window == 3
    assert state.release_at is not None
    expected_release = h08 + dt.timedelta(seconds=window_seconds)
    assert state.release_at == expected_release


def test_release_at_none_when_not_tripped(history):
    """release_at is None when breaker is not tripped."""
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    window_seconds = 24 * 3600
    h09 = now - dt.timedelta(hours=1)
    h10 = now
    _write_hits_at_times(history, [h09, h10])
    state = cb.evaluate_global(threshold=3, window_seconds=window_seconds)
    assert state.tripped is False
    assert state.hits_in_window == 2
    assert state.release_at is None


def test_release_at_none_when_empty_history(history):
    """release_at is None when no hits recorded."""
    state = cb.evaluate_global(threshold=3)
    assert state.tripped is False
    assert state.hits_in_window == 0
    assert state.release_at is None
