"""Test isolation for dontpanic_orchestrate.

Five operator-state surfaces cross-pollute tests when not isolated:

  1. ~/.jarvis/breaker_history.jsonl (F006 global circuit breaker) —
     every iteration_cap hit writes a row; once any 24h window holds 3
     rows the global breaker trips and unrelated tests start returning
     stopped_global_breaker.

  2. ~/.jarvis/active_supervisors.jsonl (F023 EC13 registry) — register/
     unregister roundtrips on every dispatch_volley(). Tests running
     under sandboxes or read-only $HOME also fail outright trying to
     write the operator path.

  3. ~/.jarvis/interactive_state.json (F007 interactive backoff) —
     `claude-touch` and the supervisor's admission reconcile both
     read/write this; without isolation the operator's real touch state
     bleeds into tests (and vice versa).

  4. ~/.jarvis/quota_state.json (F020 quota gate, also read by F006
     budget_ceiling and F007 quota_threshold admission) — operator's
     real percent_weekly will trip defer:quota_threshold and
     breaker:budget_ceiling in unrelated tests if not isolated.

  5. Plan 2026-05-09-001 F001 — ~/.dontpanic/global_config.json (modern)
     and ~/.jarvis/config.json (legacy) carry operator role assignments
     read by sufficiency_auditor / completion_dispatch / completion_gate
     resolvers. Without redirecting DONTPANIC_HOME / JARVIS_HOME, these
     leak operator-specific roles.goal_auditor into ~50 tests that
     declare different agent pairings, producing SameVendorRefused-style
     failures that have nothing to do with the test's own assertions.

Solution: autouse fixture redirects all five surfaces to per-test
tmp_path entries via JARVIS_BREAKER_HISTORY_PATH /
JARVIS_ACTIVE_SUPERVISORS_PATH / JARVIS_INTERACTIVE_STATE_PATH /
JARVIS_QUOTA_STATE_PATH / JARVIS_QUOTA_CAPS_PATH plus the home-dir env
vars DONTPANIC_HOME and JARVIS_HOME. Honored by the corresponding
*_effective_*_path() helpers in each module and by
:func:`dontpanic_orchestrate.global_config.dontpanic_home`.

Tests that want a specific quota state can write to
$JARVIS_QUOTA_STATE_PATH explicitly (it's a known per-test path).
Tests that want a specific operator config can write to
$DONTPANIC_HOME/global_config.json or $JARVIS_HOME/config.json on the
redirected paths.
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
    monkeypatch.setenv(
        "JARVIS_INTERACTIVE_STATE_PATH",
        str(tmp_path / "interactive_state.json"),
    )
    monkeypatch.setenv(
        "JARVIS_QUOTA_STATE_PATH",
        str(tmp_path / "quota_state.json"),
    )
    # F006a: caps file path isolation matches the four above. Plus reset the
    # circuit_breakers _warned_once dedup cache so warning assertions don't
    # become order-dependent across tests.
    monkeypatch.setenv(
        "JARVIS_QUOTA_CAPS_PATH",
        str(tmp_path / "quota_caps.json"),
    )
    # Plan 2026-05-09-001 F001 — redirect both home-dir env vars
    # consulted by global_config.dontpanic_home() so operator
    # ~/.dontpanic/global_config.json and ~/.jarvis/config.json cannot
    # leak roles.goal_auditor into resolver-driven tests. Each path
    # points at an empty per-test directory; tests that need a specific
    # operator config shape can write into the redirected dirs on
    # demand.
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path / "dontpanic_home"))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jarvis_home"))
    from dontpanic_orchestrate import circuit_breakers

    circuit_breakers.reset_warning_cache()
    yield
    circuit_breakers.reset_warning_cache()
