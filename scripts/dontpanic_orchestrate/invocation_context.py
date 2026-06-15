"""Plan 2026-06-14-001 F001 — operator_surface axis + four-axis InvocationContext
+ canonical-id/alias contract (D013/D015).

Pure model module: no I/O, no env reads (F002 owns resolution). Defines the
fourth axis the platform did not model — ``operator_surface`` (where the
caller engages from) — alongside the existing ``agent_runtime`` (reused from
:mod:`agent_surface` / ``executors.AGENT_REGISTRY``), worker ``role`` (reused
``agent_surface.ROLES``), and a SHARP ``execution_locality`` enum.

CANONICAL-ID + ALIAS CONTRACT (D013): every axis id is a lowercase
snake/kebab-stable canonical id; display labels are aliases ONLY. The pure
:func:`normalize_identifier` maps known aliases / user inputs to the canonical
id and maps every unrecognized value to that axis's ``unknown_*`` member — never
an invented id. The SAME canonical id set is the single source consumed by
resolution (F002), ``operator_roles`` values (F004), capability-manifest ids
(F008), and dashboard labels (F010). No parallel runtime/capability registry.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from enum import Enum

from dontpanic_orchestrate import agent_surface

# ──────────────────────────────  axis unknown members  ──────────────────────────────

UNKNOWN_SURFACE = "unknown_surface"
UNKNOWN_RUNTIME = "unknown_runtime"
UNKNOWN_ROLE = "unknown_role"
UNKNOWN_LOCALITY = "unknown_locality"


# ──────────────────────────────  enums (exact membership)  ──────────────────────────────


class OperatorSurface(str, Enum):
    """Where the user/caller is engaging from. ``str`` mixin so ``.value`` and
    the member compare/serialize as the canonical id."""

    TERMINAL = "terminal"
    CODEX_APP = "codex_app"
    CLAUDE_DESKTOP = "claude_desktop"
    CLAUDE_DISPATCH = "claude_dispatch"
    ANTIGRAVITY = "antigravity"
    CURSOR = "cursor"
    GITHUB_AGENT_HQ = "github_agent_hq"
    REMOTE_VM = "remote_vm"
    GITHUB_VM = "github_vm"
    UNKNOWN = UNKNOWN_SURFACE


class ExecutionLocality(str, Enum):
    """Where commands actually run — sharp enough to tell a plan-worktree run
    from a remote-VM or code-task run (the reason this axis is not local|remote)."""

    LOCAL_MAC = "local_mac"
    PLAN_WORKTREE = "plan_worktree"
    DASHBOARD_TERMINAL = "dashboard_terminal"
    CODE_TASK = "code_task"
    REMOTE_VM = "remote_vm"
    GITHUB_VM = "github_vm"
    UNKNOWN = UNKNOWN_LOCALITY


# ──────────────────────────────  string-valued axes (reused sources)  ──────────────────────────────

# agent_runtime canonical universe — validated against the SAME source as
# agent_surface: the dispatchable executors (AGENT_REGISTRY) + known operator
# agents, extended with the operator-surface-capable runtimes named in the spec
# (D013). Unknown agents map to unknown_runtime, never an invented entry.
_SPEC_RUNTIMES: tuple[str, ...] = (
    "claude",
    "codex",
    "gemini",
    "grok",
    "cursor",
    "antigravity",
    "opencode",
    "aider",
)


def _dispatchable_executors() -> tuple[str, ...]:
    try:
        from dontpanic_orchestrate import executors

        return tuple(sorted(executors.AGENT_REGISTRY))
    except Exception:  # noqa: BLE001 — model module never hard-fails on registry import
        return ("claude", "codex")


AGENT_RUNTIMES: tuple[str, ...] = tuple(
    sorted(set(_dispatchable_executors()) | set(agent_surface.KNOWN_OPERATOR_AGENTS) | set(_SPEC_RUNTIMES))
)

# role axis = the worker ROLES (implementer / auditor / goal_auditor) + unknown_role.
ROLES: tuple[str, ...] = agent_surface.ROLES


# ──────────────────────────────  alias contract  ──────────────────────────────

_Axis = str  # one of: operator_surface | agent_runtime | role | execution_locality

_AXIS_UNKNOWN: dict[_Axis, str] = {
    "operator_surface": UNKNOWN_SURFACE,
    "agent_runtime": UNKNOWN_RUNTIME,
    "role": UNKNOWN_ROLE,
    "execution_locality": UNKNOWN_LOCALITY,
}

# Per-axis canonical -> extra display aliases (the canonical id itself is always
# accepted; underscores in a canonical id normalize to spaces, so 'codex_app'
# also matches the input 'codex app').
_AXIS_ALIASES: dict[_Axis, dict[str, tuple[str, ...]]] = {
    "agent_runtime": {
        "claude": ("claude code", "claude cli", "anthropic claude", "claudecode"),
        "codex": ("codex cli", "openai codex"),
        "gemini": ("google gemini",),
        "grok": ("xai grok",),
        "opencode": ("open code",),
    },
    "operator_surface": {
        "terminal": ("term", "shell", "tty"),
        "claude_desktop": ("claude app",),
        "claude_dispatch": ("claude code dispatch", "claude headless"),
        "github_agent_hq": ("agent hq", "gh agent hq"),
        "github_vm": ("github actions", "github runner", "gh actions"),
    },
    "execution_locality": {
        "local_mac": ("mac", "macos", "darwin", "local"),
        "plan_worktree": ("worktree",),
        "dashboard_terminal": ("dashboard",),
        "github_vm": ("github actions", "github runner"),
    },
    "role": {
        "goal_auditor": ("goal auditor",),
    },
}


def _canonical_ids(axis: _Axis) -> tuple[str, ...]:
    if axis == "operator_surface":
        return tuple(s.value for s in OperatorSurface)
    if axis == "execution_locality":
        return tuple(loc.value for loc in ExecutionLocality)
    if axis == "agent_runtime":
        return AGENT_RUNTIMES
    if axis == "role":
        return ROLES
    raise ValueError(f"unknown axis: {axis!r}")


def _normalize_key(value: str) -> str:
    """Fold an input to a comparison key: lowercase, collapse any run of
    whitespace / hyphen / underscore / dot to a single space, strip."""
    return re.sub(r"[\s\-_.]+", " ", value).strip().lower()


def _build_alias_index() -> dict[_Axis, dict[str, str]]:
    index: dict[_Axis, dict[str, str]] = {}
    for axis in _AXIS_UNKNOWN:
        amap: dict[str, str] = {}
        for canonical in _canonical_ids(axis):
            amap[_normalize_key(canonical)] = canonical
        for canonical, aliases in _AXIS_ALIASES.get(axis, {}).items():
            for alias in aliases:
                amap[_normalize_key(alias)] = canonical
        index[axis] = amap
    return index


_ALIAS_INDEX: dict[_Axis, dict[str, str]] = _build_alias_index()


def normalize_identifier(value: str | None, axis: _Axis) -> str:
    """Map ``value`` to its canonical id for ``axis``; an unrecognized or empty
    value maps to that axis's ``unknown_*`` member (never an invented id). Pure:
    no I/O, no mutation. Raises ``ValueError`` for an unknown axis name."""
    if axis not in _AXIS_UNKNOWN:
        raise ValueError(f"unknown axis: {axis!r}")
    unknown = _AXIS_UNKNOWN[axis]
    if not value or not str(value).strip():
        return unknown
    return _ALIAS_INDEX[axis].get(_normalize_key(str(value)), unknown)


# ──────────────────────────────  InvocationContext  ──────────────────────────────


@dataclass(frozen=True)
class InvocationContext:
    """The four-axis context of a single DontPanic invocation. Exactly four
    fields; serializes byte-stable (no timestamps). operator_surface /
    execution_locality are typed enums; agent_runtime / role are canonical
    string ids (reused vocabularies)."""

    operator_surface: OperatorSurface
    agent_runtime: str
    role: str
    execution_locality: ExecutionLocality

    def to_dict(self) -> dict[str, str]:
        return {
            "operator_surface": self.operator_surface.value,
            "agent_runtime": self.agent_runtime,
            "role": self.role,
            "execution_locality": self.execution_locality.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> InvocationContext:
        return cls(
            operator_surface=OperatorSurface(data["operator_surface"]),
            agent_runtime=data["agent_runtime"],
            role=data["role"],
            execution_locality=ExecutionLocality(data["execution_locality"]),
        )


__all__ = [
    "AGENT_RUNTIMES",
    "ExecutionLocality",
    "InvocationContext",
    "OperatorSurface",
    "ROLES",
    "UNKNOWN_LOCALITY",
    "UNKNOWN_ROLE",
    "UNKNOWN_RUNTIME",
    "UNKNOWN_SURFACE",
    "normalize_identifier",
]

# Defensive: guard the secret-free field-name invariant at import time so a
# future field rename that leaks a secret-shaped name fails fast (F001 acceptance).
for _f in dataclasses.fields(InvocationContext):
    _low = _f.name.lower()
    assert not any(s in _low for s in ("_token", "_key", "_secret")), (
        f"InvocationContext field {_f.name!r} has a secret-shaped name"
    )
