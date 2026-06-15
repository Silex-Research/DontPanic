"""Plan 2026-06-14-001 F006 — dispatch-safety guard for the D009 SAFETY INVARIANT.

operator_roles.* are PREFERENCE/INTENT ONLY and NEVER dispatch authority.
Assigning a surface/agent an operator role must never make DontPanic able to
spawn it as a worker — dispatch authority derives SOLELY from
executors.AGENT_REGISTRY via the worker roles.* namespace. This pins that
boundary in the dispatch path and proves it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import agent_surface, dispatch_safety_guard as guard, operator_roles  # noqa: E402


def _a_real_executor() -> str | None:
    workers = agent_surface.worker_executors()
    return workers[0] if workers else None


# ──────────────────────────────  the SAFETY INVARIANT  ──────────────────────────────


def test_operator_role_on_non_executor_does_not_grant_dispatch() -> None:
    # cursor is a non-executor operator surface
    assert not agent_surface.is_worker_capable("cursor")
    operator_roles.set_operator_role("primary_operator", "cursor", scope="global")

    # ...assigning it an operator-role PREFERENCE changes nothing about dispatch
    assert guard.is_dispatchable("cursor") is False
    assert "cursor" not in guard.dispatchable_agents()
    with pytest.raises(guard.DispatchRefused):
        guard.assert_dispatch_allowed("cursor")


def test_refusal_is_identical_whether_or_not_a_preference_is_set() -> None:
    # no operator role set -> refused
    with pytest.raises(guard.DispatchRefused):
        guard.assert_dispatch_allowed("cursor")
    before = guard.is_dispatchable("cursor")
    # set a preference -> still refused, byte-identical outcome
    operator_roles.set_operator_role("auditor", "cursor", scope="global")
    assert guard.is_dispatchable("cursor") == before is False


def test_dispatchable_set_is_exactly_agent_registry_regardless_of_preferences() -> None:
    operator_roles.set_operator_role("primary_operator", "cursor", scope="global")
    operator_roles.set_operator_role("researcher", "antigravity", scope="global")
    operator_roles.set_operator_role("reviewer", "human", scope="global")
    # the dispatchable set never widens past the worker executor registry
    assert guard.dispatchable_agents() == agent_surface.worker_executors()


def test_a_real_executor_stays_dispatchable_with_or_without_a_preference() -> None:
    worker = _a_real_executor()
    if worker is None:
        pytest.skip("no worker executors registered in this environment")
    assert guard.is_dispatchable(worker) is True
    guard.assert_dispatch_allowed(worker)  # does not raise
    # assigning the worker an operator-role preference must not change dispatch
    operator_roles.set_operator_role("primary_operator", worker, scope="global")
    assert guard.is_dispatchable(worker) is True
    guard.assert_dispatch_allowed(worker)


# ──────────────────────────────  register-worker path is unchanged  ──────────────────────────────


def test_register_worker_path_unchanged_by_operator_role_presence() -> None:
    # assert_registrable refuses a non-executor whether or not it holds a preference
    with pytest.raises(agent_surface.RegisterWorkerError):
        agent_surface.assert_registrable("cursor")
    operator_roles.set_operator_role("primary_operator", "cursor", scope="global")
    with pytest.raises(agent_surface.RegisterWorkerError):
        agent_surface.assert_registrable("cursor")


# ──────────────────────────────  no read path widens dispatch (executable proof)  ──────────────────────────────


def test_preference_only_surfaces_are_proven_non_dispatchable() -> None:
    operator_roles.set_operator_role("primary_operator", "cursor", scope="global")
    operator_roles.set_operator_role("designer", "antigravity", scope="global")
    pref_only = guard.preference_only_surfaces()
    assert "cursor" in pref_only and "antigravity" in pref_only
    for surface in pref_only:
        assert guard.is_dispatchable(surface) is False
    # the executable D009 proof: no operator-role read path grants/widens dispatch
    guard.assert_operator_roles_do_not_widen_dispatch()  # must not raise


def test_dispatchability_never_reads_operator_roles(monkeypatch) -> None:
    # If is_dispatchable consulted operator_roles, poisoning that read would change
    # the answer. Poison it and assert the answer is invariant.
    def _boom(*_a, **_k):
        raise AssertionError("dispatch authority must NOT read operator_roles")

    monkeypatch.setattr(operator_roles, "list_operator_roles", _boom)
    assert guard.is_dispatchable("cursor") is False
    assert guard.dispatchable_agents() == agent_surface.worker_executors()
