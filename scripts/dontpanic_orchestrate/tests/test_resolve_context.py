"""Plan 2026-06-14-001 F002 — explicit-first / heuristic / unknown-last context resolver.

Covers the F002 acceptance: resolve_context(env, *, repo, plan) is PURE and
(1) honors the four DONT_PANIC_* explicit vars verbatim (run through
normalize_identifier so an unrecognized explicit value -> that axis's unknown_*,
never rejected); (2) with no explicit vars, a DOCUMENTED DETERMINISTIC RULE
TABLE maps named markers to fields — a named rule cell for EACH ExecutionLocality
member AND a named per-surface detection cell for EACH seeded operator_surface,
plus a known agent env marker -> agent_runtime; (3) any unresolved field is the
axis's unknown_* member (never a most-likely guess); (4) no I/O, no mutation of
the passed env.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.invocation_context import (  # noqa: E402
    UNKNOWN_LOCALITY,
    UNKNOWN_ROLE,
    UNKNOWN_RUNTIME,
    UNKNOWN_SURFACE,
    ExecutionLocality,
    OperatorSurface,
)
from dontpanic_orchestrate.resolve_context import (  # noqa: E402
    LOCALITY_RULES,
    SEEDED_SURFACES,
    SURFACE_RULES,
    resolve_context,
)

SEEDED = ("cursor", "codex_app", "claude_desktop", "antigravity")


# ──────────────────────────────  explicit-first  ──────────────────────────────


def test_explicit_vars_win_over_all_heuristics() -> None:
    env = {
        # explicit
        "DONT_PANIC_OPERATOR": "Cursor",
        "DONT_PANIC_AGENT": "Claude Code",
        "DONT_PANIC_ROLE": "auditor",
        "DONT_PANIC_LOCALITY": "plan_worktree",
        # conflicting heuristic markers that must be ignored
        "GITHUB_ACTIONS": "true",
        "CLAUDECODE": "1",
        "ANTIGRAVITY": "1",
    }
    ctx = resolve_context(env, repo=None, plan=None)
    assert ctx.operator_surface is OperatorSurface.CURSOR
    assert ctx.agent_runtime == "claude"  # alias normalized
    assert ctx.role == "auditor"
    assert ctx.execution_locality is ExecutionLocality.PLAN_WORKTREE


def test_unrecognized_explicit_values_map_to_axis_unknown() -> None:
    env = {
        "DONT_PANIC_OPERATOR": "made-up-surface",
        "DONT_PANIC_AGENT": "not-an-agent",
        "DONT_PANIC_ROLE": "wizard",
        "DONT_PANIC_LOCALITY": "the-moon",
    }
    ctx = resolve_context(env, repo=None, plan=None)
    assert ctx.operator_surface.value == UNKNOWN_SURFACE
    assert ctx.agent_runtime == UNKNOWN_RUNTIME
    assert ctx.role == UNKNOWN_ROLE
    assert ctx.execution_locality.value == UNKNOWN_LOCALITY


# ──────────────────────────────  named rule cells (heuristic)  ──────────────────────────────


@pytest.mark.parametrize("member", [m for m in ExecutionLocality if m is not ExecutionLocality.UNKNOWN])
def test_every_execution_locality_member_reachable_by_named_cell(member: ExecutionLocality) -> None:
    # the rule table must declare at least one named cell whose target is this member
    targets = {rule.target for rule in LOCALITY_RULES}
    assert member.value in targets, f"no named locality cell yields {member.value}"


@pytest.mark.parametrize("surface", SEEDED)
def test_every_seeded_surface_reachable_by_named_cell(surface: str) -> None:
    targets = {rule.target for rule in SURFACE_RULES}
    assert surface in targets, f"no named surface cell yields {surface}"
    assert surface in SEEDED_SURFACES


def test_locality_local_mac_via_named_marker() -> None:
    ctx = resolve_context({"DONTPANIC_PLATFORM": "darwin"}, repo=None, plan=None)
    assert ctx.execution_locality is ExecutionLocality.LOCAL_MAC


def test_locality_plan_worktree_via_repo_path() -> None:
    repo = Path("/Users/x/.dontpanic/worktrees/Proj-abc/2026-06-14-001-feat-foo")
    ctx = resolve_context({}, repo=repo, plan=None)
    assert ctx.execution_locality is ExecutionLocality.PLAN_WORKTREE


def test_locality_dashboard_remote_codetask_github_each_reachable() -> None:
    assert resolve_context({"DONTPANIC_DASHBOARD_TERMINAL": "1"}, repo=None, plan=None).execution_locality is ExecutionLocality.DASHBOARD_TERMINAL
    assert resolve_context({"SSH_CONNECTION": "10.0.0.1 22"}, repo=None, plan=None).execution_locality is ExecutionLocality.REMOTE_VM
    assert resolve_context({"DONTPANIC_CODE_TASK": "1"}, repo=None, plan=None).execution_locality is ExecutionLocality.CODE_TASK
    assert resolve_context({"GITHUB_ACTIONS": "true"}, repo=None, plan=None).execution_locality is ExecutionLocality.GITHUB_VM


def test_each_seeded_surface_detected_by_its_marker() -> None:
    assert resolve_context({"CURSOR_TRACE_ID": "abc"}, repo=None, plan=None).operator_surface is OperatorSurface.CURSOR
    assert resolve_context({"CODEX_APP": "1"}, repo=None, plan=None).operator_surface is OperatorSurface.CODEX_APP
    assert resolve_context({"CLAUDE_DESKTOP": "1"}, repo=None, plan=None).operator_surface is OperatorSurface.CLAUDE_DESKTOP
    assert resolve_context({"ANTIGRAVITY": "1"}, repo=None, plan=None).operator_surface is OperatorSurface.ANTIGRAVITY


def test_known_agent_env_marker_resolves_agent_runtime() -> None:
    assert resolve_context({"CLAUDECODE": "1"}, repo=None, plan=None).agent_runtime == "claude"
    # the existing DONTPANIC_AGENT (no underscores) marker is honored as a heuristic too
    assert resolve_context({"DONTPANIC_AGENT": "gemini"}, repo=None, plan=None).agent_runtime == "gemini"


# ──────────────────────────────  unknown-last + purity  ──────────────────────────────


def test_empty_env_resolves_all_unknown_no_guessing() -> None:
    ctx = resolve_context({}, repo=None, plan=None)
    assert ctx.operator_surface.value == UNKNOWN_SURFACE
    assert ctx.agent_runtime == UNKNOWN_RUNTIME
    assert ctx.role == UNKNOWN_ROLE
    assert ctx.execution_locality.value == UNKNOWN_LOCALITY


def test_resolver_is_pure_no_mutation_and_deterministic() -> None:
    env = {"CLAUDECODE": "1", "GITHUB_ACTIONS": "true"}
    snapshot = dict(env)
    a = resolve_context(env, repo=None, plan=None)
    b = resolve_context(env, repo=None, plan=None)
    assert env == snapshot  # not mutated
    assert a == b  # deterministic


def test_plan_supplies_repo_when_repo_omitted() -> None:
    class _Plan:
        dir = Path("/Users/x/.dontpanic/worktrees/Proj-abc/2026-06-14-001-feat-foo")

    ctx = resolve_context({}, repo=None, plan=_Plan())
    assert ctx.execution_locality is ExecutionLocality.PLAN_WORKTREE
