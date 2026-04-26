"""Test isolation for jarvis_orchestrate.

The supervisor's circuit-breaker subsystem (F006) writes to
~/.jarvis/breaker_history.jsonl on every iteration_cap hit so the global
breaker can fire after 3 hits in 24h. Real-volley tests that exercise
dispatch_volley() will repollute the operator's actual home directory unless
isolated; once the count reaches 3 the global breaker trips and unrelated
tests start returning stopped_global_breaker.

Solution: autouse fixture redirecting JARVIS_BREAKER_HISTORY_PATH to a tmp
file for every test. Honored by circuit_breakers._effective_history_path().
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_breaker_history(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "JARVIS_BREAKER_HISTORY_PATH",
        str(tmp_path / "breaker_history.jsonl"),
    )
    yield
