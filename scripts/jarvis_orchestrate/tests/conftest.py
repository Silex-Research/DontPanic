"""Test isolation for jarvis_orchestrate.

Two operator-state files cross-pollute tests when not isolated:

  1. ~/.jarvis/breaker_history.jsonl (F006 global circuit breaker) —
     every iteration_cap hit writes a row; once any 24h window holds 3
     rows the global breaker trips and unrelated tests start returning
     stopped_global_breaker.

  2. ~/.jarvis/active_supervisors.jsonl (F023 EC13 registry) — register/
     unregister roundtrips on every dispatch_volley(). Tests running
     under sandboxes or read-only $HOME also fail outright trying to
     write the operator path.

Solution: autouse fixture sets JARVIS_BREAKER_HISTORY_PATH and
JARVIS_ACTIVE_SUPERVISORS_PATH to per-test tmp_path entries. Honored by
circuit_breakers._effective_history_path() and
active_supervisors._effective_registry_path().
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_jarvis_state(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "JARVIS_BREAKER_HISTORY_PATH",
        str(tmp_path / "breaker_history.jsonl"),
    )
    monkeypatch.setenv(
        "JARVIS_ACTIVE_SUPERVISORS_PATH",
        str(tmp_path / "active_supervisors.jsonl"),
    )
    yield
