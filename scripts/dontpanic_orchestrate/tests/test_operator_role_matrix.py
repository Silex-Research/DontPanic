"""Plan 2026-06-14-001 F005 — read-only operator-role matrix projection.

Asserts: (1) the projection is pure (derived from operator_roles, no I/O, no
mutation of inputs); (2) it returns the resolved operator-role map with scope
provenance; (3) operator-role PREFERENCES render distinctly from worker roles.*
(no conflation of the two namespaces); and that it carries no dispatchability
claim (intent only).
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.operator_role_matrix import (  # noqa: E402
    OPERATOR_NAMESPACE,
    WORKER_NAMESPACE,
    project_role_matrix,
)

_RESOLVED = {
    "primary_operator": {"value": "cursor", "scope": "project"},
    "auditor": {"value": "codex", "scope": "global"},
    "researcher": {"value": "human", "scope": "global"},
}


def test_projection_is_pure_no_mutation_and_deterministic() -> None:
    snapshot = copy.deepcopy(_RESOLVED)
    a = project_role_matrix(_RESOLVED)
    b = project_role_matrix(_RESOLVED)
    assert _RESOLVED == snapshot  # inputs not mutated
    assert a == b  # deterministic, pure


def test_returns_resolved_map_with_scope_provenance() -> None:
    matrix = project_role_matrix(_RESOLVED)
    entries = {e["role"]: e for e in matrix[OPERATOR_NAMESPACE]["entries"]}
    assert entries["primary_operator"]["value"] == "cursor"
    assert entries["primary_operator"]["scope"] == "project"  # provenance preserved
    assert entries["auditor"]["scope"] == "global"


def test_operator_preferences_render_distinctly_from_worker_roles() -> None:
    matrix = project_role_matrix(
        _RESOLVED,
        worker_role_assignments={"implementer": "claude", "auditor": "codex", "goal_auditor": "codex"},
    )
    # two DISTINCT namespaces — no conflation
    assert OPERATOR_NAMESPACE in matrix and WORKER_NAMESPACE in matrix
    assert OPERATOR_NAMESPACE != WORKER_NAMESPACE
    # an operator-role value (cursor) is NOT rendered into the worker section
    worker_agents = {e["agent"] for e in matrix[WORKER_NAMESPACE]["entries"]}
    assert "cursor" not in worker_agents
    # worker section carries dispatch authority; operator section does not
    assert matrix[WORKER_NAMESPACE]["dispatch_authority"] is True


def test_operator_section_is_intent_only_no_dispatchability_claim() -> None:
    matrix = project_role_matrix(_RESOLVED)
    section = matrix[OPERATOR_NAMESPACE]
    assert section["intent_only"] is True
    assert section["dispatch_authority"] is False
    # no per-entry field claims dispatchability
    for entry in section["entries"]:
        assert "dispatchable" not in entry
        assert "can_dispatch" not in entry
