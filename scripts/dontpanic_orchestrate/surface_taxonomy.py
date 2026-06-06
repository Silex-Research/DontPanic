"""Plan 2026-06-05-004 F001 — canonical surface vocabulary + alias map.

DontPanic has FOUR surface vocabularies that do not naturally match:

1. plan-review lint surface tags  (cli, dashboard, schema, persistence, orchestration,
   core, doctor, validator)
2. qa-sufficiency-contract surface classes  (read-only UI, interactive UI, mobile app,
   command (CLI), agent / MCP tool, mutation, external integration, service / batch)
3. skill ``applies_to`` values  (web, ios, android, backend, infra, security, data,
   ux, ml, docs)
4. agent-conventions topics  (overlap with the skill surfaces)

Without a canonical bridge, surface AWARENESS can route to the wrong standard — e.g. a
skill declaring ``[web, ux]`` and a dashboard plan deriving ``dashboard`` never meet.
This module folds all four into ONE closed canonical vocabulary, with an explicit
``unrouteable`` fallback so unknown inputs are surfaced, never silently dropped.

Pure + dependency-free so plan-review, derivation (F002), and the registry (F003) can
all share one resolver.
"""

from __future__ import annotations

import re

# ── Canonical, closed surface vocabulary ────────────────────────────────────
# Seeded from the 2026-06-05-004 plan table + the qa-sufficiency surface classes.
# ``core`` is the internal/governance catch-all (DontPanic's own plan-review / doctor /
# orchestration internals) — it has no required sufficiency pack.
CANONICAL_SURFACES: frozenset[str] = frozenset(
    {
        "frontend-ui",
        "command",
        "backend-api",
        "mobile-app",
        "agent-tool",
        "external-integration",
        "infra-deploy",
        "security-review",
        "mutation",
        "core",
    }
)

# Sentinel for an input we cannot route to a canonical surface. NOT a canonical id —
# it must be reported (see F003's unrouteable inventory), never treated as "no surface".
UNROUTEABLE = "unrouteable"


def _norm(token: str) -> str:
    """Lowercase + collapse any non-alphanumeric run to a single space.

    ``"read-only UI"`` -> ``"read only ui"``; ``"command (CLI)"`` -> ``"command cli"``;
    ``"agent / MCP tool"`` -> ``"agent mcp tool"``.
    """
    return re.sub(r"[^a-z0-9]+", " ", token.lower()).strip()


# Alias map keyed by the NORMALISED token. Every value is a canonical surface id.
SURFACE_ALIASES: dict[str, str] = {
    # canonical ids (normalised) resolve to themselves
    "frontend ui": "frontend-ui",
    "command": "command",
    "backend api": "backend-api",
    "mobile app": "mobile-app",
    "agent tool": "agent-tool",
    "external integration": "external-integration",
    "infra deploy": "infra-deploy",
    "security review": "security-review",
    "mutation": "mutation",
    "core": "core",
    # 1) plan-review lint surface tags
    "cli": "command",
    "dashboard": "frontend-ui",
    "schema": "backend-api",
    "persistence": "backend-api",
    "orchestration": "core",
    "doctor": "core",
    "validator": "core",
    # 2) qa-sufficiency surface classes
    "read only ui": "frontend-ui",
    "interactive ui": "frontend-ui",
    "command cli": "command",
    "agent mcp tool": "agent-tool",
    "agent mcp": "agent-tool",
    "service batch": "backend-api",
    # 3) skill applies_to values
    "web": "frontend-ui",
    "ux": "frontend-ui",
    "ios": "mobile-app",
    "android": "mobile-app",
    "backend": "backend-api",
    "api": "backend-api",
    "data": "backend-api",
    "ml": "backend-api",
    "infra": "infra-deploy",
    "deploy": "infra-deploy",
    "security": "security-review",
    "docs": "core",
}


def resolve_surface(token: str) -> str:
    """Resolve any source-vocabulary token to a canonical surface id, or UNROUTEABLE.

    Pure: no IO. Unknown / empty inputs return :data:`UNROUTEABLE` (never dropped).
    """
    if not token or not token.strip():
        return UNROUTEABLE
    return SURFACE_ALIASES.get(_norm(token), UNROUTEABLE)
