"""Plan 2026-07-27-001 F013 — worker-profile config schema (Track D2).

A worker profile is the operator-config "agent card" from the Track D
vocabulary (docs/AGENT_CAPABILITY_MATRIX.md): a named binding of

    display_name + harness + model + allowed_roles (+ capability overrides)

Profiles live under ``worker_profiles.<id>`` in the global config
(``~/.dontpanic/config.json``) and/or the per-project config
(``<project>/.dontpanic/dontpanic.json``); the project layer wins per id.
A roles entry (``roles.implementer`` / ``auditor`` / ``goal_auditor``) may
name a profile id instead of a legacy harness name — resolution lives in
:mod:`dontpanic_orchestrate.worker_profiles`.

Capability vocabulary (F011): a harness earns roles through capability
flags — ``implementer`` requires ``file_edit`` + ``tool_use`` +
``non_interactive``; audit-style roles require ``non_interactive`` only.
Profile ``capabilities`` overrides can only RESTRICT the harness's flags
(e.g. an audit-only profile on a full-capability harness); a profile that
claims a capability its harness lacks is refused, never widened — models
are data and profiles are config, so neither can grant dispatch authority
beyond what the registered harness adapter provides (D009/D010).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, field_validator

PROFILE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
"""Profile ids are lowercase slugs so they are unambiguous in configs and
CLI output. Enforced by the ``workers`` CLI writer (a hand-edited config
with a strange key degrades to the usual load-time WARN, not a crash)."""

HARNESS_ALIASES: dict[str, str] = {
    "claude_cli": "claude",
    "codex_cli": "codex",
    "gemini_cli": "gemini",
}
"""D015 harness aliases: the Track D docs name harnesses by their adapter
module (``codex_cli``), while AGENT_REGISTRY keys the bare vendor name.
Both spellings are accepted anywhere a harness is named (profile
``harness`` fields, legacy role values) and normalize to the registry key
BEFORE registry membership and capability checks. ``gemini_cli`` maps to
``gemini`` even though no gemini executor is registered yet — the alias is
a naming rule, not a registration."""


def normalize_harness(name: str) -> str:
    """Canonical AGENT_REGISTRY spelling for a harness name: alias-table
    lookup, identity otherwise. Never validates registration."""
    return HARNESS_ALIASES.get(name, name)

CAPABILITY_FLAGS: tuple[str, ...] = ("file_edit", "tool_use", "non_interactive")
"""The harness capability axes that gate role holding (F011 vocabulary)."""

# Capability flags per registered harness. Both current harnesses run a
# sandboxed non-interactive CLI with tool use + file edit. A registered
# harness NOT listed here defaults conservatively to audit-style capability
# only (DEFAULT_HARNESS_CAPABILITIES) — a future read-only or
# goal-audit-only harness (gemini_cli per D001 B2) must be listed
# explicitly to hold the implementer role.
HARNESS_CAPABILITIES: dict[str, frozenset[str]] = {
    "claude": frozenset(CAPABILITY_FLAGS),
    "codex": frozenset(CAPABILITY_FLAGS),
}

DEFAULT_HARNESS_CAPABILITIES: frozenset[str] = frozenset({"non_interactive"})
"""Conservative default for a registered-but-unlisted harness: it may hold
audit-style roles, never implementer."""

ROLE_REQUIRED_CAPABILITIES: dict[str, frozenset[str]] = {
    "implementer": frozenset({"file_edit", "tool_use", "non_interactive"}),
    "auditor": frozenset({"non_interactive"}),
    "goal_auditor": frozenset({"non_interactive"}),
}
"""Capability gate per canonical role (F011): implementer needs the full
set; audit-style roles only need non-interactive dispatch."""


class WorkerProfileCapabilities(BaseModel):
    """Per-profile capability OVERRIDES. ``None`` means "inherit from the
    harness"; ``False`` restricts (removes the flag); ``True`` asserts the
    flag and is refused when the harness does not actually provide it —
    overrides can narrow a profile, never widen dispatch authority."""

    model_config = ConfigDict(extra="forbid")

    file_edit: bool | None = None
    tool_use: bool | None = None
    non_interactive: bool | None = None


class WorkerProfile(BaseModel):
    """One named worker profile (Track D2 agent card)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    """Human-facing label (e.g. "Honey"). Purely cosmetic."""

    harness: str
    """AGENT_REGISTRY key the profile dispatches through (``claude`` /
    ``codex`` today). Required — a profile without a harness cannot be
    dispatched. Model ids are never valid here (D010)."""

    model: str | None = None
    """Vendor model-id override forwarded to the harness CLI (F012 pass-
    through). ``None`` falls through to the role-level model override,
    then the harness CLI default."""

    allowed_roles: list[str] | None = None
    """Roles this profile may hold. ``None`` means all roles (still
    subject to capability gates); an explicit list refuses everything
    else — e.g. ``["auditor"]`` for an auditor-only profile."""

    capabilities: WorkerProfileCapabilities | None = None
    """Optional capability overrides — see
    :class:`WorkerProfileCapabilities`."""

    @field_validator("harness")
    @classmethod
    def _normalize_harness(cls, v: str) -> str:
        # D015 aliases (claude_cli/codex_cli/gemini_cli) normalize at parse
        # time so every downstream registry + capability check sees the
        # canonical AGENT_REGISTRY spelling.
        return normalize_harness(v)

    @field_validator("allowed_roles")
    @classmethod
    def _validate_allowed_roles(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        known = set(ROLE_REQUIRED_CAPABILITIES)
        unknown = [r for r in v if r not in known]
        if unknown:
            raise ValueError(
                f"unknown allowed_roles {unknown!r}; valid roles: {sorted(known)}"
            )
        return v


def harness_capabilities(harness: str) -> frozenset[str]:
    """Capability flags for ``harness``; conservative default for a
    registered harness not listed in :data:`HARNESS_CAPABILITIES`."""
    return HARNESS_CAPABILITIES.get(normalize_harness(harness), DEFAULT_HARNESS_CAPABILITIES)


def effective_capabilities(profile: WorkerProfile) -> frozenset[str]:
    """Harness capabilities minus any flags the profile's overrides set to
    ``False``. Overrides never add flags — see :func:`widened_capabilities`
    for the refusal path when a profile claims more than its harness."""
    caps = set(harness_capabilities(profile.harness))
    if profile.capabilities is not None:
        for flag in CAPABILITY_FLAGS:
            if getattr(profile.capabilities, flag) is False:
                caps.discard(flag)
    return frozenset(caps)


def widened_capabilities(profile: WorkerProfile) -> list[str]:
    """Flags the profile asserts ``True`` that its harness does not
    provide. Non-empty means the profile is invalid (capability overrides
    restrict, never widen) and must be refused."""
    base = harness_capabilities(profile.harness)
    if profile.capabilities is None:
        return []
    return sorted(
        flag
        for flag in CAPABILITY_FLAGS
        if getattr(profile.capabilities, flag) is True and flag not in base
    )


def missing_capabilities_for_role(profile: WorkerProfile, role: str) -> list[str]:
    """Capability flags ``role`` requires that the profile's effective set
    lacks. Empty means the capability gate passes for that role. Unknown
    (non-canonical) roles require nothing — model override / profile
    metadata is optional for them, mirroring ``resolve_model``."""
    required = ROLE_REQUIRED_CAPABILITIES.get(role, frozenset())
    return sorted(required - effective_capabilities(profile))


__all__ = [
    "CAPABILITY_FLAGS",
    "DEFAULT_HARNESS_CAPABILITIES",
    "HARNESS_ALIASES",
    "HARNESS_CAPABILITIES",
    "PROFILE_ID_PATTERN",
    "ROLE_REQUIRED_CAPABILITIES",
    "WorkerProfile",
    "WorkerProfileCapabilities",
    "effective_capabilities",
    "harness_capabilities",
    "missing_capabilities_for_role",
    "normalize_harness",
    "widened_capabilities",
]
