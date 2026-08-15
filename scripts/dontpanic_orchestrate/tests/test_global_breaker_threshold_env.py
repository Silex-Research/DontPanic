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
