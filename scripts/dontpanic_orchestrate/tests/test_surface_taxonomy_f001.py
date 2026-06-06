"""Plan 2026-06-05-004 F001 — canonical surface vocabulary + alias map.

The four source vocabularies (plan-review lint tags, qa-sufficiency surface classes,
skill applies_to values, agent-conventions topics) do not naturally match. This guards
that they all resolve into ONE closed canonical surface set, with an explicit unrouteable
fallback for unknown inputs.
"""

from __future__ import annotations

import pytest

from dontpanic_orchestrate.surface_taxonomy import (
    CANONICAL_SURFACES,
    UNROUTEABLE,
    resolve_surface,
)


@pytest.mark.parametrize(
    "token,expected",
    [
        # plan-review lint tags
        ("dashboard", "frontend-ui"),
        ("cli", "command"),
        ("schema", "backend-api"),
        ("persistence", "backend-api"),
        ("orchestration", "core"),
        ("validator", "core"),
        # qa-sufficiency surface classes
        ("read-only UI", "frontend-ui"),
        ("interactive UI", "frontend-ui"),
        ("mobile app", "mobile-app"),
        ("command (CLI)", "command"),
        ("agent / MCP tool", "agent-tool"),
        ("mutation", "mutation"),
        ("external integration", "external-integration"),
        ("service / batch", "backend-api"),
        # skill applies_to values
        ("web", "frontend-ui"),
        ("ux", "frontend-ui"),
        ("ios", "mobile-app"),
        ("android", "mobile-app"),
        ("backend", "backend-api"),
        ("infra", "infra-deploy"),
        ("security", "security-review"),
        # canonical ids resolve to themselves
        ("frontend-ui", "frontend-ui"),
        ("backend-api", "backend-api"),
    ],
)
def test_alias_resolves_to_expected_canonical(token: str, expected: str) -> None:
    assert resolve_surface(token) == expected
    assert expected in CANONICAL_SURFACES


def test_web_ux_and_dashboard_converge_on_one_frontend_id() -> None:
    assert {resolve_surface(t) for t in ("web", "ux", "dashboard", "read-only UI")} == {
        "frontend-ui"
    }


def test_unknown_input_is_unrouteable_not_dropped() -> None:
    assert resolve_surface("quantum-teleporter") == UNROUTEABLE
    assert resolve_surface("") == UNROUTEABLE
    assert UNROUTEABLE not in CANONICAL_SURFACES


def test_every_alias_target_is_a_canonical_surface() -> None:
    from dontpanic_orchestrate.surface_taxonomy import SURFACE_ALIASES

    for target in SURFACE_ALIASES.values():
        assert target in CANONICAL_SURFACES, target
