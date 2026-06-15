"""Plan 2026-06-14-001 F002 — explicit-first / heuristic / unknown-last resolver.

Resolves an :class:`InvocationContext` (F001) from an env mapping plus the active
repo/plan, with a strict precedence:

  1. EXPLICIT — the four ``DONT_PANIC_*`` vars win over every heuristic. Each is
     run through :func:`normalize_identifier`, so an *unrecognized* explicit value
     maps to that axis's ``unknown_*`` member (never rejected, never a wrong guess).
  2. HEURISTIC — with no explicit var for an axis, a DOCUMENTED DETERMINISTIC RULE
     TABLE (``SURFACE_RULES`` / ``LOCALITY_RULES`` / ``RUNTIME_RULES``) maps named
     env markers to canonical ids. There is a named cell for EACH
     ``ExecutionLocality`` member and a named per-surface detection cell for EACH
     seeded ``operator_surface`` (cursor, codex_app, claude_desktop, antigravity) —
     not just a generic ``TERM_PROGRAM`` fallback.
  3. UNKNOWN — any field still unresolved becomes the axis's ``unknown_*`` member.

Pure: no I/O, no ``os.environ`` reads, no mutation of the passed env. The env
mapping is read via ``.get`` only; ``repo``/``plan`` are inputs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.invocation_context import (
    ExecutionLocality,
    InvocationContext,
    OperatorSurface,
    UNKNOWN_LOCALITY,
    UNKNOWN_SURFACE,
    normalize_identifier,
)

# Explicit override env var per axis (these WIN, then normalize).
ENV_OPERATOR = "DONT_PANIC_OPERATOR"
ENV_AGENT = "DONT_PANIC_AGENT"
ENV_ROLE = "DONT_PANIC_ROLE"
ENV_LOCALITY = "DONT_PANIC_LOCALITY"

# The four surfaces F008 seeds now; each MUST have a named detection cell below.
SEEDED_SURFACES: tuple[str, ...] = ("cursor", "codex_app", "claude_desktop", "antigravity")


@dataclass(frozen=True)
class MarkerRule:
    """One deterministic detection cell: when ``env[key]`` is present (and, if
    ``value`` is given, normalizes-equal to it), resolve the axis to ``target``.
    Rules are evaluated in declaration order; first match wins."""

    key: str
    target: str
    value: str | None = None  # None => presence is enough


def _matches(env: Mapping[str, str], rule: MarkerRule) -> bool:
    raw = env.get(rule.key)
    if raw is None or not str(raw).strip():
        return False
    if rule.value is None:
        return True
    return str(raw).strip().lower() == rule.value.lower()


# ──────────────────────────────  operator_surface rule table  ──────────────────────────────
# Named per-surface cells for each seeded surface, plus the remaining members.
# Order: most-specific app/VM markers before the generic terminal fallback.
SURFACE_RULES: tuple[MarkerRule, ...] = (
    MarkerRule("CURSOR_TRACE_ID", "cursor"),
    MarkerRule("TERM_PROGRAM", "cursor", value="cursor"),
    MarkerRule("CODEX_APP", "codex_app"),
    MarkerRule("TERM_PROGRAM", "codex_app", value="codex_app"),
    MarkerRule("CLAUDE_DESKTOP", "claude_desktop"),
    MarkerRule("ANTIGRAVITY", "antigravity"),
    MarkerRule("CLAUDE_DISPATCH", "claude_dispatch"),
    MarkerRule("GITHUB_AGENT_HQ", "github_agent_hq"),
    MarkerRule("GITHUB_ACTIONS", "github_vm", value="true"),
    MarkerRule("SSH_CONNECTION", "remote_vm"),
    MarkerRule("REMOTE_CONTAINERS", "remote_vm", value="true"),
    # generic terminal LAST — any other TERM_PROGRAM / TERM means a plain terminal
    MarkerRule("TERM_PROGRAM", "terminal"),
    MarkerRule("TERM", "terminal"),
)

# ──────────────────────────────  execution_locality rule table  ──────────────────────────────
# One named cell per member; remote/vm/task markers precede the local_mac marker.
LOCALITY_RULES: tuple[MarkerRule, ...] = (
    MarkerRule("GITHUB_ACTIONS", "github_vm", value="true"),
    MarkerRule("DONTPANIC_REMOTE_VM", "remote_vm"),
    MarkerRule("SSH_CONNECTION", "remote_vm"),
    MarkerRule("REMOTE_CONTAINERS", "remote_vm", value="true"),
    MarkerRule("DONTPANIC_CODE_TASK", "code_task"),
    MarkerRule("CLAUDE_CODE_TASK", "code_task"),
    MarkerRule("DONTPANIC_DASHBOARD_TERMINAL", "dashboard_terminal"),
    MarkerRule("DONTPANIC_WORKTREE", "plan_worktree"),
    MarkerRule("DONTPANIC_PLATFORM", "local_mac", value="darwin"),
)

# ──────────────────────────────  agent_runtime rule table  ──────────────────────────────
# Known agent-CLI env markers -> agent_runtime. DONTPANIC_AGENT (no underscores)
# is the existing agent_surface marker, honored here as a heuristic; its value is
# normalized so an unknown agent name still lands on unknown_runtime.
RUNTIME_RULES: tuple[MarkerRule, ...] = (
    MarkerRule("CLAUDECODE", "claude"),
    MarkerRule("CURSOR_TRACE_ID", "cursor"),
    MarkerRule("CODEX_APP", "codex"),
)

# repo path segment that marks a DontPanic plan worktree.
_WORKTREE_SEGMENT = ".dontpanic/worktrees"


def _repo_str(repo: Any, plan: Any) -> str | None:
    """Derive a repo path string from ``repo`` (or, when omitted, from ``plan``)."""
    candidate = repo
    if candidate is None and plan is not None:
        candidate = getattr(plan, "dir", None)
        if candidate is None and isinstance(plan, (str, Path)):
            candidate = plan
    if candidate is None:
        return None
    return str(candidate).replace("\\", "/")


def _resolve_surface(env: Mapping[str, str]) -> OperatorSurface:
    explicit = env.get(ENV_OPERATOR)
    if explicit is not None and str(explicit).strip():
        return OperatorSurface(normalize_identifier(explicit, "operator_surface"))
    for rule in SURFACE_RULES:
        if _matches(env, rule):
            return OperatorSurface(rule.target)
    return OperatorSurface(UNKNOWN_SURFACE)


def _resolve_locality(env: Mapping[str, str], repo_str: str | None) -> ExecutionLocality:
    explicit = env.get(ENV_LOCALITY)
    if explicit is not None and str(explicit).strip():
        return ExecutionLocality(normalize_identifier(explicit, "execution_locality"))
    for rule in LOCALITY_RULES:
        if _matches(env, rule):
            return ExecutionLocality(rule.target)
    if repo_str is not None and _WORKTREE_SEGMENT in repo_str:
        return ExecutionLocality.PLAN_WORKTREE
    return ExecutionLocality(UNKNOWN_LOCALITY)


def _resolve_runtime(env: Mapping[str, str]) -> str:
    explicit = env.get(ENV_AGENT)
    if explicit is not None and str(explicit).strip():
        return normalize_identifier(explicit, "agent_runtime")
    heuristic = env.get("DONTPANIC_AGENT")
    if heuristic is not None and str(heuristic).strip():
        return normalize_identifier(heuristic, "agent_runtime")
    for rule in RUNTIME_RULES:
        if _matches(env, rule):
            return normalize_identifier(rule.target, "agent_runtime")
    return normalize_identifier(None, "agent_runtime")


def _resolve_role(env: Mapping[str, str]) -> str:
    explicit = env.get(ENV_ROLE)
    if explicit is not None and str(explicit).strip():
        return normalize_identifier(explicit, "role")
    return normalize_identifier(None, "role")


def resolve_context(env: Mapping[str, str], *, repo: Any, plan: Any) -> InvocationContext:
    """Resolve the four-axis :class:`InvocationContext` from ``env`` + active
    ``repo``/``plan`` using explicit-first / heuristic / unknown-last precedence.
    Pure: reads ``env`` via ``.get`` only and never mutates it."""
    repo_str = _repo_str(repo, plan)
    return InvocationContext(
        operator_surface=_resolve_surface(env),
        agent_runtime=_resolve_runtime(env),
        role=_resolve_role(env),
        execution_locality=_resolve_locality(env, repo_str),
    )


__all__ = [
    "ENV_AGENT",
    "ENV_LOCALITY",
    "ENV_OPERATOR",
    "ENV_ROLE",
    "LOCALITY_RULES",
    "MarkerRule",
    "RUNTIME_RULES",
    "SEEDED_SURFACES",
    "SURFACE_RULES",
    "resolve_context",
]
