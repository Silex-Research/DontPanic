"""Plan G F006 — ``RolesConfig``: agent role names by capability.

Three roles in v1: ``implementer``, ``auditor``, ``goal_auditor``. All
optional; the resolver layers them with legacy fields and a hardcoded
fallback (``claude`` / ``codex``) per D013.

F012 (D1/D011) adds model overrides. The canonical shape is the
plan-locked ``roles.<role>.model``: a roles entry may be either a plain
agent-name string (back-compat, pre-F012 shape) or a :class:`RoleSpec`
object (``{"name": "codex", "model": "gpt-5.2-codex"}``).
:class:`RoleModelsConfig` (top-level ``models.<role>`` block, shipped in
F012 i0) remains supported as a compatibility alias; the canonical
``roles.<role>.model`` wins within the same config layer. Models are
data, never registry keys (D010) — the harness stays whatever the role
name resolves to; the model string is forwarded to that harness's CLI.
Unset means the harness CLI default.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RoleSpec(BaseModel):
    """F012 i1 — object form of a roles entry, the plan-locked
    ``roles.*.model`` shape. ``name`` is the agent/harness registry key
    (same value the plain-string form carries); ``model`` is the vendor
    model-id override. Either may be omitted: a model-only entry pins
    the model while the name falls through to deeper layers."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    model: str | None = None


class RolesConfig(BaseModel):
    """Per-tier agent role names. Layered global → project → per-call by
    :func:`config.resolvers.resolve_role`. Each entry is a plain agent
    name (legacy) or a :class:`RoleSpec` (F012 ``roles.*.model``)."""

    model_config = ConfigDict(extra="forbid")

    implementer: str | RoleSpec | None = None
    auditor: str | RoleSpec | None = None
    goal_auditor: str | RoleSpec | None = None


class RoleModelsConfig(BaseModel):
    """F012 — per-role vendor model-id overrides (e.g.
    ``{"implementer": "claude-opus-5"}``). Compatibility alias for the
    canonical ``roles.<role>.model`` shape (which wins within the same
    layer); layered global → project → per-call by
    :func:`config.resolvers.resolve_model`. No fallback tier: an unset
    role means the harness CLI default (pre-F012 behavior). Worker
    profiles (F013) will layer above this when they land."""

    model_config = ConfigDict(extra="forbid")

    implementer: str | None = None
    auditor: str | None = None
    goal_auditor: str | None = None


def role_name(entry: str | RoleSpec | None) -> str | None:
    """Normalize a roles entry to its agent name (both shapes)."""
    if entry is None:
        return None
    if isinstance(entry, RoleSpec):
        return entry.name
    return entry


def role_model(entry: str | RoleSpec | None) -> str | None:
    """Normalize a roles entry to its model override (string form has none)."""
    if isinstance(entry, RoleSpec):
        return entry.model
    return None


__all__ = ["RoleModelsConfig", "RoleSpec", "RolesConfig", "role_model", "role_name"]
