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
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dontpanic_orchestrate import agent_brief
from dontpanic_orchestrate import executors
from dontpanic_orchestrate.config import resolvers

Classification = Literal["operator-only", "worker-capable"]

# Agents whose harness can spawn sub-agents (an orchestrating harness). This is
# the THIRD, independent capability axis (F002): orthogonal to can_operate and
# can_be_dispatched. Reported only — F002 does NOT act on it (no fan-out, tree
# budget, breaker, or undo; see the scope-guard test). Claude Code Workflow can
# spawn sub-agents → can_orchestrate; Grok cannot. Kept conservative: an agent
# earns this flag by being known to orchestrate, not by being a worker.
ORCHESTRATOR_CAPABLE_AGENTS: frozenset[str] = frozenset({"claude"})

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


@dataclass(frozen=True)
class Capabilities:
    """Three INDEPENDENT capability booleans for a harness (plan
    2026-06-02-001 F002), superseding the flat operator-vs-worker binary.

    A harness may report any combination — these are orthogonal axes, not a
    ladder:

    * ``can_operate`` — drives DontPanic by running its CLI. Any named agent
      can (D002/D006: an unsupported agent is an operator, never a worker
      without a registered executor), so this is always True for a named agent.
    * ``can_be_dispatched`` — has a real executor in
      :data:`executors.AGENT_REGISTRY` and can be dispatched as a worker.
    * ``can_orchestrate`` — the harness can spawn sub-agents (e.g. Claude Code
      Workflow). Reported only — F002 does not act on it.

    Examples: Claude Code Workflow → (True, True, True); Grok → (True, False,
    False) i.e. operate-only.
    """

    name: str
    can_operate: bool
    can_be_dispatched: bool
    can_orchestrate: bool

    def as_dict(self) -> dict[str, object]:
        """Serialise to a stable JSON-friendly dict (key order fixed)."""
        return {
            "name": self.name,
            "can_operate": self.can_operate,
            "can_be_dispatched": self.can_be_dispatched,
            "can_orchestrate": self.can_orchestrate,
        }

    def brief_line(self) -> str:
        """One-line, capability-derived description for the agent brief / status.

        The operate-but-not-dispatch case renders the exact F002 wording
        'can operate DontPanic but is not a dispatchable worker' from
        ``can_operate=True`` / ``can_be_dispatched=False`` — not from a stored
        label — so the text can never drift from the booleans."""
        if self.can_operate and not self.can_be_dispatched:
            tail = (
                " and can orchestrate sub-agents"
                if self.can_orchestrate
                else ""
            )
            return (
                f"{self.name} can operate DontPanic but is not a dispatchable "
                f"worker{tail}."
            )
        if self.can_be_dispatched:
            tail = (
                " and can orchestrate sub-agents"
                if self.can_orchestrate
                else ""
            )
            return (
                f"{self.name} can operate DontPanic and is a dispatchable "
                f"worker{tail}."
            )
        # can_operate is always True for a named agent, so this is unreachable
        # for real inputs; keep an honest fallback rather than asserting.
        return f"{self.name} has no operating capability."


def capabilities(name: str) -> Capabilities:
    """Derive the three INDEPENDENT capability booleans for ``name`` (F002).

    ``can_operate`` is always True for a named agent (D002/D006: any agent can
    operate DontPanic). ``can_be_dispatched`` comes from the executor registry
    alone — the SAME source as :func:`classify`, so the worker axis never
    contradicts the operator/worker text. ``can_orchestrate`` is read from
    :data:`ORCHESTRATOR_CAPABLE_AGENTS` and is reported, never acted on.
    """
    norm = name.strip().lower()
    return Capabilities(
        name=norm,
        can_operate=True,
        can_be_dispatched=is_worker_capable(norm),
        can_orchestrate=norm in ORCHESTRATOR_CAPABLE_AGENTS,
    )


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
        caps = capabilities(target)
        cls = classify(target)
        dispatchable = "yes" if cls == "worker-capable" else "no"
        lines.append(f"{label}: {target}")
        lines.append(f"  classification: {cls}")
        lines.append(f"  can be dispatched as a worker: {dispatchable}")
        # Three INDEPENDENT capability booleans (F002) — the honest superset of
        # the operator/worker binary above; can_orchestrate is reported, not
        # acted on.
        lines.append(f"  can_operate: {str(caps.can_operate).lower()}")
        lines.append(f"  can_be_dispatched: {str(caps.can_be_dispatched).lower()}")
        lines.append(f"  can_orchestrate: {str(caps.can_orchestrate).lower()}")
        lines.append(f"  {caps.brief_line()}")
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


def status_payload(project_dir: Path, *, name: str | None = None) -> dict[str, object]:
    """Machine-readable ``dontpanic agent status --json`` payload (F002).

    Reports the target agent's three INDEPENDENT capability booleans
    (``can_operate`` / ``can_be_dispatched`` / ``can_orchestrate``) plus the
    worker roster, known operator-only agents, and the effective per-role
    capabilities. The target is the explicitly named agent, else the detected
    current agent, else ``None`` (no env signal). Read-only — derives entirely
    from the executor registry and layered config; no write, no dispatch.
    """
    target = name if name is not None else detect_current_agent()
    roles = resolve_roles(project_dir)
    return {
        "worker_executors": worker_executors(),
        "known_operator_only_agents": known_operator_only_agents(),
        "roles": {
            role: capabilities(roles[role]).as_dict() for role in ROLES
        },
        "agent": capabilities(target).as_dict() if target is not None else None,
        "current_agent_source": "named" if name is not None else "detected",
    }


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


def assert_registrable(
    name: str, *, role: str | None = None, project_path: Path | None = None
) -> None:
    """Guard for ``register-worker`` / ``roles set``: raise
    :class:`RegisterWorkerError` when ``name`` cannot be dispatched, so the
    CLI refuses before writing any config (F002 acceptance #4).

    F013: ``name`` may also be a defined worker-profile id. The profile
    path applies harness membership + ``allowed_roles`` + capability gates
    (via :mod:`worker_profiles`); gate refusals re-raise as
    :class:`RegisterWorkerError` so every caller keeps one refusal type.
    ``role`` scopes the allowed_roles/capability check to the slot being
    assigned; ``project_path`` includes that project's profile layer.
    """
    if is_worker_capable(name):
        return

    # Lazy import — worker_profiles imports config layers, not this module,
    # so the lazy edge keeps the dependency acyclic.
    from dontpanic_orchestrate import worker_profiles as wp

    profile = wp.load_profiles(project_path).get(name)
    if profile is not None:
        try:
            if role is not None:
                wp.assert_profile_role_allowed(name, profile, role)
            else:
                wp.assert_profile_dispatchable(name, profile)
        except wp.WorkerProfileError as exc:
            raise RegisterWorkerError(str(exc)) from exc
        return

    registered = ", ".join(worker_executors()) or "(none)"
    raise RegisterWorkerError(
        f"{name!r} has no executor in DontPanic and cannot be registered as a "
        f"worker. {name} can operate DontPanic as an interactive agent, but only "
        f"these agents are dispatchable workers: {registered}."
    )


__all__ = [
    "CURRENT_AGENT_ENV",
    "Capabilities",
    "Classification",
    "KNOWN_OPERATOR_AGENTS",
    "ORCHESTRATOR_CAPABLE_AGENTS",
    "ROLES",
    "RegisterWorkerError",
    "assert_registrable",
    "capabilities",
    "classify",
    "detect_current_agent",
    "is_worker_capable",
    "known_operator_only_agents",
    "render_setup",
    "render_status",
    "status_payload",
    "resolve_roles",
    "worker_executors",
]
