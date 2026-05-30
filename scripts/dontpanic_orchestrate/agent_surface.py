"""Plan 2026-05-30-001 F002 — machine agent surface helpers.

Pure classification + deterministic rendering for the ``dontpanic agent``
command family (``brief`` / ``status`` / ``setup`` / ``register-worker``).
The CLI layer in :mod:`cli` parses argv and performs config writes; the
operator-facing text and the operator-vs-worker classification live here so
they are unit-testable without spawning a process or invoking a real agent
CLI (F002 acceptance #9).

Load-bearing distinction (shared with :mod:`agent_brief`): **any** named
agent can *operate* DontPanic by running its CLI commands; only agents with a
real executor in :data:`executors.AGENT_REGISTRY` can be *dispatched* as
workers. An agent absent from the registry is operator-only — it should
operate DontPanic, not configure itself as a worker.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dontpanic_orchestrate import agent_brief
from dontpanic_orchestrate import executors
from dontpanic_orchestrate.config import resolvers

Classification = Literal["operator-only", "worker-capable"]

# The three role slots a worker executor can be assigned to. Mirrors
# config.roles.RolesConfig / resolvers.Role; kept as a tuple here so status
# rendering iterates a stable order.
ROLES: tuple[str, ...] = ("implementer", "auditor", "goal_auditor")

# Well-known interactive agents that can *operate* DontPanic but have no
# executor (operator-only). Surfaced by ``status`` so the no-arg output names
# the agents the brief calls out (Grok, Gemini) as un-dispatchable, rather than
# only listing the dispatchable executors. Sorted for byte-stable output; any
# name that later gains an executor is filtered out at render time so the two
# lists never contradict each other.
KNOWN_OPERATOR_AGENTS: tuple[str, ...] = ("gemini", "grok")

# Environment variable an operating agent can set to identify itself to the
# status surface. Explicit and overridable; absent → best-effort sniffing, then
# "unknown".
CURRENT_AGENT_ENV = "DONTPANIC_AGENT"


class RegisterWorkerError(ValueError):
    """Raised when ``register-worker`` is asked to register an agent that has
    no executor in :data:`executors.AGENT_REGISTRY`. The CLI maps this to a
    refusal exit code and writes nothing."""


def worker_executors() -> list[str]:
    """Registered worker executor names, sorted for byte-stable output. These
    are exactly the agents DontPanic can dispatch; everyone else is
    operator-only."""
    return sorted(executors.AGENT_REGISTRY)


def is_worker_capable(name: str) -> bool:
    """True when ``name`` has a real executor and can be dispatched as a
    worker. False means operator-only."""
    return name in executors.AGENT_REGISTRY


def classify(name: str) -> Classification:
    """Classify ``name`` from the executor registry alone (F002 acceptance
    #2). ``worker-capable`` iff a real executor exists; else ``operator-only``."""
    return "worker-capable" if is_worker_capable(name) else "operator-only"


def resolve_roles(project_dir: Path) -> dict[str, str]:
    """Resolve the effective agent for each role through the layered config
    chain (per-call > project > global > fallback). Read-only — does not
    write any config."""
    return {role: resolvers.resolve_role(project_dir, role) for role in ROLES}


def detect_current_agent() -> str | None:
    """Best-effort identity of the agent currently operating DontPanic.

    Explicit ``$DONTPANIC_AGENT`` wins (any agent can announce itself); failing
    that, sniff a well-known agent-CLI env marker. Returns ``None`` when no
    signal is present (e.g. a human shell), so :func:`render_status` prints
    generic guidance instead of guessing. Reads live env — not byte-stable, by
    design, since ``status`` is a live snapshot, not the deterministic brief.
    """
    explicit = os.environ.get(CURRENT_AGENT_ENV, "").strip().lower()
    if explicit:
        return explicit
    if os.environ.get("CLAUDECODE", "").strip():
        return "claude"
    return None


def known_operator_only_agents() -> list[str]:
    """Known interactive agents with no executor — they can operate DontPanic
    but cannot be dispatched. Filters out any name that has gained an executor
    so this never contradicts :func:`worker_executors`."""
    return [a for a in KNOWN_OPERATOR_AGENTS if not is_worker_capable(a)]


def _workflow_one_line() -> str:
    """The canonical workflow as a single line (the brief stores it across two
    lines for the full render)."""
    return agent_brief.CANONICAL_WORKFLOW.replace("\n", " ")


def render_status(project_dir: Path, *, name: str | None = None) -> str:
    """Render ``dontpanic agent status``: registered worker executors, known
    operator-only agents, the effective role assignments, and a classification
    block for either the named agent (``name`` given) or the detected current
    agent (no-arg path).

    The classification block is *always* rendered: with ``name`` it classifies
    that agent; without, it classifies the current agent (or reports it as
    unknown), so the no-arg output never silently omits who is operating
    (F002-i0 finding). Executor / role / operator-only lists are sorted and
    fixed-order; only the current-agent line varies with live env.
    """
    workers = worker_executors()
    operator_only = known_operator_only_agents()
    roles = resolve_roles(project_dir)

    lines: list[str] = ["DontPanic agent status", ""]

    lines.append("WORKER EXECUTORS (dispatchable as workers):")
    if workers:
        lines.extend(f"  - {w}" for w in workers)
    else:
        lines.append("  (none registered)")
    lines.append("")

    lines.append("KNOWN OPERATOR-ONLY AGENTS (can operate, NOT dispatchable):")
    if operator_only:
        lines.extend(f"  - {a}" for a in operator_only)
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append("CONFIGURED ROLES (effective, layered config):")
    for role in ROLES:
        agent = roles[role]
        tag = "worker-capable" if is_worker_capable(agent) else "operator-only — NOT dispatchable"
        lines.append(f"  - {role}: {agent} ({tag})")
    lines.append("")

    # Classification block — an explicitly named agent, else the detected
    # current agent. Always present so the no-arg path still classifies the
    # operator rather than only listing executors and roles.
    target = name if name is not None else detect_current_agent()
    if target is not None:
        label = "AGENT" if name is not None else "CURRENT AGENT"
        cls = classify(target)
        dispatchable = "yes" if cls == "worker-capable" else "no"
        lines.append(f"{label}: {target}")
        lines.append(f"  classification: {cls}")
        lines.append(f"  can be dispatched as a worker: {dispatchable}")
        if cls == "operator-only":
            lines.append(
                f"  {target} can operate DontPanic by running its CLI, but has no "
                "executor and cannot be registered as a worker."
            )
        lines.append("")
    else:
        lines.append("CURRENT AGENT: unknown")
        lines.append(
            f"  Set ${CURRENT_AGENT_ENV} to classify the current agent. Any agent "
            "can operate DontPanic; only the worker executors above are dispatchable."
        )
        lines.append("")

    lines.append(
        "Any agent can operate DontPanic; only the worker executors above can "
        "be dispatched."
    )
    return "\n".join(lines) + "\n"


def render_setup(name: str) -> str:
    """Render ``dontpanic agent setup <name>``: operator setup guidance for any
    named interactive agent, plus worker setup guidance gated on whether
    ``name`` has a real executor (F002 acceptance #3).
    """
    capable = is_worker_capable(name)

    lines: list[str] = [
        f"DontPanic setup guidance for: {name}",
        "",
        "OPERATOR SETUP (any agent can do this):",
        f"  {name} can operate DontPanic by running its CLI commands.",
        "  Start here:  dontpanic agent brief",
        f"  Workflow:    {_workflow_one_line()}",
        "",
    ]

    if capable:
        lines.extend(
            [
                "WORKER SETUP (executor present):",
                f"  {name} has a registered executor and CAN be dispatched as a worker.",
                f"  Register a role:  dontpanic agent register-worker {name} --role implementer",
            ]
        )
    else:
        registered = ", ".join(worker_executors()) or "(none)"
        lines.extend(
            [
                "WORKER SETUP (no executor — operator-only):",
                f"  {name} has NO registered executor in DontPanic.",
                f"  {name} can operate DontPanic but CANNOT be registered as a worker",
                "  without an executor. Operate DontPanic as an interactive agent",
                f"  instead; do not configure {name} as a worker.",
                f"  Registered worker executors: {registered}",
            ]
        )
    return "\n".join(lines) + "\n"


def assert_registrable(name: str) -> None:
    """Guard for ``register-worker``: raise :class:`RegisterWorkerError` when
    ``name`` is not a real executor, so the CLI refuses before writing any
    config (F002 acceptance #4)."""
    if not is_worker_capable(name):
        registered = ", ".join(worker_executors()) or "(none)"
        raise RegisterWorkerError(
            f"{name!r} has no executor in DontPanic and cannot be registered as a "
            f"worker. {name} can operate DontPanic as an interactive agent, but only "
            f"these agents are dispatchable workers: {registered}."
        )


__all__ = [
    "CURRENT_AGENT_ENV",
    "Classification",
    "KNOWN_OPERATOR_AGENTS",
    "ROLES",
    "RegisterWorkerError",
    "assert_registrable",
    "classify",
    "detect_current_agent",
    "is_worker_capable",
    "known_operator_only_agents",
    "render_setup",
    "render_status",
    "resolve_roles",
    "worker_executors",
]
