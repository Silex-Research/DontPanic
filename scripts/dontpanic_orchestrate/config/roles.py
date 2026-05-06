"""Plan G F006 — ``RolesConfig``: agent role names by capability.

Three roles in v1: ``implementer``, ``auditor``, ``goal_auditor``. All
optional; the resolver layers them with legacy fields and a hardcoded
fallback (``claude`` / ``codex``) per D013.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RolesConfig(BaseModel):
    """Per-tier agent role names. Layered global → project → per-call by
    :func:`config.resolvers.resolve_role`."""

    model_config = ConfigDict(extra="forbid")

    implementer: str | None = None
    auditor: str | None = None
    goal_auditor: str | None = None


__all__ = ["RolesConfig"]
