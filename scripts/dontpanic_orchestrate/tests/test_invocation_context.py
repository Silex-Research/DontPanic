"""Plan 2026-06-14-001 F001 — operator_surface axis + four-axis InvocationContext
+ canonical-id/alias contract (D013/D015).

Covers the F001 acceptance: the OperatorSurface + ExecutionLocality enums with
EXACT membership, the InvocationContext dataclass with exactly four fields,
agent_runtime validated against the same source as agent_surface (unknown ->
unknown_runtime), the role axis reusing worker ROLES + unknown_role, the pure
normalize_identifier alias contract (user inputs -> canonical, unknown ->
unknown_* per axis), byte-stable round-trip serialization, and the secret-free
field-name invariant.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import agent_surface  # noqa: E402
from dontpanic_orchestrate.invocation_context import (  # noqa: E402
    AGENT_RUNTIMES,
    UNKNOWN_LOCALITY,
    UNKNOWN_ROLE,
    UNKNOWN_RUNTIME,
    UNKNOWN_SURFACE,
    ExecutionLocality,
    InvocationContext,
    OperatorSurface,
    normalize_identifier,
)


# ──────────────────────────────  enum membership (exact)  ──────────────────────────────


def test_operator_surface_membership_is_exact() -> None:
    assert {s.value for s in OperatorSurface} == {
        "terminal",
        "codex_app",
        "claude_desktop",
        "claude_dispatch",
        "antigravity",
        "cursor",
        "github_agent_hq",
        "remote_vm",
        "github_vm",
        "unknown_surface",
    }
    assert OperatorSurface.UNKNOWN.value == UNKNOWN_SURFACE == "unknown_surface"


def test_execution_locality_membership_is_exact() -> None:
    assert {loc.value for loc in ExecutionLocality} == {
        "local_mac",
        "plan_worktree",
        "dashboard_terminal",
        "code_task",
        "remote_vm",
        "github_vm",
        "unknown_locality",
    }
    assert ExecutionLocality.UNKNOWN.value == UNKNOWN_LOCALITY == "unknown_locality"


def test_agent_runtime_canonical_ids_and_role_axis_reuse_worker_roles() -> None:
    # agent_runtime canonical ids at least the spec set
    for rid in ("claude", "codex", "gemini", "grok", "cursor", "antigravity", "opencode", "aider"):
        assert rid in AGENT_RUNTIMES
    # validated against the SAME source as agent_surface: every dispatchable
    # executor + every known operator agent is a canonical runtime id
    for known in agent_surface.KNOWN_OPERATOR_AGENTS:
        assert known in AGENT_RUNTIMES
    # role axis reuses the worker ROLES + an explicit unknown_role
    assert UNKNOWN_ROLE == "unknown_role"
    for role in agent_surface.ROLES:  # implementer, auditor, goal_auditor
        assert normalize_identifier(role, "role") == role


# ──────────────────────────────  InvocationContext shape  ──────────────────────────────


def test_invocation_context_has_exactly_four_fields() -> None:
    import dataclasses

    fields = {f.name for f in dataclasses.fields(InvocationContext)}
    assert fields == {"operator_surface", "agent_runtime", "role", "execution_locality"}


def test_no_field_name_contains_secret_shapes() -> None:
    import dataclasses

    for f in dataclasses.fields(InvocationContext):
        lowered = f.name.lower()
        assert "_token" not in lowered
        assert "_key" not in lowered
        assert "_secret" not in lowered


# ──────────────────────────────  normalize_identifier (alias contract)  ──────────────────────────────


def test_normalize_aliases_to_canonical_ids() -> None:
    # agent_runtime aliases -> claude
    for alias in ("Claude Code", "claude-cli", "Anthropic Claude", "CLAUDE", "claude"):
        assert normalize_identifier(alias, "agent_runtime") == "claude"
    # operator_surface aliases
    assert normalize_identifier("Cursor", "operator_surface") == "cursor"
    assert normalize_identifier("codex app", "operator_surface") == "codex_app"
    # locality
    assert normalize_identifier("Local Mac", "execution_locality") == "local_mac"


def test_normalize_unrecognized_maps_to_axis_unknown_member() -> None:
    assert normalize_identifier("totally-made-up", "operator_surface") == UNKNOWN_SURFACE
    assert normalize_identifier("nope", "agent_runtime") == UNKNOWN_RUNTIME
    assert normalize_identifier("nope", "role") == UNKNOWN_ROLE
    assert normalize_identifier("nope", "execution_locality") == UNKNOWN_LOCALITY


def test_normalize_is_pure_and_handles_empty() -> None:
    # empty / None -> unknown for that axis, no exception
    assert normalize_identifier("", "operator_surface") == UNKNOWN_SURFACE
    assert normalize_identifier(None, "agent_runtime") == UNKNOWN_RUNTIME


def test_normalize_rejects_unknown_axis() -> None:
    with pytest.raises(ValueError):
        normalize_identifier("x", "not_an_axis")


# ──────────────────────────────  byte-stable serialization  ──────────────────────────────


def test_serialization_round_trips_byte_stable() -> None:
    ctx = InvocationContext(
        operator_surface=OperatorSurface.CURSOR,
        agent_runtime="claude",
        role="auditor",
        execution_locality=ExecutionLocality.PLAN_WORKTREE,
    )
    d = ctx.to_dict()
    # every enum member round-trips through to_dict/from_dict
    assert InvocationContext.from_dict(d) == ctx
    # byte-stable: serializing twice yields identical bytes (no timestamps / set ordering)
    assert json.dumps(d, sort_keys=True) == json.dumps(InvocationContext.from_dict(d).to_dict(), sort_keys=True)
    # no timestamp-ish keys leaked into the serialized form
    assert set(d.keys()) == {"operator_surface", "agent_runtime", "role", "execution_locality"}


def test_every_enum_member_round_trips() -> None:
    for surface in OperatorSurface:
        for loc in ExecutionLocality:
            ctx = InvocationContext(
                operator_surface=surface,
                agent_runtime="codex",
                role="implementer",
                execution_locality=loc,
            )
            assert InvocationContext.from_dict(ctx.to_dict()) == ctx
