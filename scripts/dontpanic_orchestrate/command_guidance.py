"""Agent-facing command guidance metadata.

Plan 2026-06-03-001 F001/F002 prep. This module is deliberately pure:
it describes command surfaces for humans and interactive agents, but never
imports the CLI router and never invokes a command handler. The command
vocabulary is projected from :mod:`command_validation`; the metadata here
classifies that vocabulary for safe discovery.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from dontpanic_orchestrate import command_validation

SCHEMA_VERSION = "1.0"


class CommandClass(str, Enum):
    """Closed risk/action vocabulary for agent-facing command guidance."""

    READONLY_INSPECTION = "readonly_inspection"
    LIFECYCLE_MUTATION = "lifecycle_mutation"
    DISPATCH_PAID_WORK = "dispatch_paid_work"
    CONFIG_MUTATION = "configuration_mutation"
    DIAGNOSTIC_INSPECTION = "diagnostic_inspection"
    HUMAN_HANDOFF = "human_handoff"


class Audience(str, Enum):
    """Who a guidance entry is intended to help."""

    HUMAN = "human"
    INTERACTIVE_AGENT = "interactive_agent"


class CommandExample(BaseModel):
    """One safe example for a guided command path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    argv: tuple[str, ...]
    description: str

    @field_validator("argv")
    @classmethod
    def _argv_nonempty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("example argv must not be empty")
        if any(not token or token.isspace() for token in value):
            raise ValueError("example argv tokens must be non-empty")
        return value

    @field_validator("description")
    @classmethod
    def _description_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("example description must not be empty")
        return value


class CommandGuidance(BaseModel):
    """Typed metadata for one DontPanic command path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: tuple[str, ...]
    command_class: CommandClass
    audience: tuple[Audience, ...] = (
        Audience.HUMAN,
        Audience.INTERACTIVE_AGENT,
    )
    examples: tuple[CommandExample, ...] = ()
    predecessor_hints: tuple[str, ...] = ()
    human_escalation_rule: str

    @field_validator("path")
    @classmethod
    def _path_nonempty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("command path must not be empty")
        if any(not token or token.isspace() or " " in token for token in value):
            raise ValueError("command path tokens must be non-empty argv tokens")
        return value

    @field_validator("audience")
    @classmethod
    def _audience_nonempty(cls, value: tuple[Audience, ...]) -> tuple[Audience, ...]:
        if not value:
            raise ValueError("audience must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("audience values must be unique")
        return value

    @field_validator("human_escalation_rule")
    @classmethod
    def _escalation_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("human escalation rule must not be empty")
        return value

    @model_validator(mode="after")
    def _examples_match_path(self) -> CommandGuidance:
        for example in self.examples:
            if example.argv[: len(self.path)] != self.path:
                raise ValueError(
                    "example argv must start with the command guidance path"
                )
        return self

    @property
    def command(self) -> str:
        """Top-level command token for inventory parity checks."""
        return self.path[0]

    def as_public_dict(self) -> dict[str, object]:
        """Stable JSON-ready shape for future CLI rendering."""
        return self.model_dump(mode="json")


def _example(command: str, *rest: str, description: str) -> CommandExample:
    return CommandExample(argv=(command, *rest), description=description)


# Base class per top-level command — the class of the command's most common
# (often read-only) entry point. Commands whose *riskiest* subcommand is more
# dangerous than this base are bumped up via ``_SUBCOMMAND_CLASS_OVERRIDES``;
# never read this table without going through :func:`_effective_class`.
_CLASS_BY_COMMAND: dict[str, CommandClass] = {
    "agent": CommandClass.READONLY_INSPECTION,
    "approve": CommandClass.LIFECYCLE_MUTATION,
    "architecture": CommandClass.DIAGNOSTIC_INSPECTION,
    "calibrate-claude": CommandClass.CONFIG_MUTATION,
    "capabilities": CommandClass.DIAGNOSTIC_INSPECTION,
    "claude-touch": CommandClass.DIAGNOSTIC_INSPECTION,
    "close": CommandClass.LIFECYCLE_MUTATION,
    "config": CommandClass.CONFIG_MUTATION,
    "dashboard": CommandClass.HUMAN_HANDOFF,
    "dispatch-from-plan": CommandClass.DISPATCH_PAID_WORK,
    "doctor": CommandClass.DIAGNOSTIC_INSPECTION,
    "finalize": CommandClass.LIFECYCLE_MUTATION,
    "init": CommandClass.CONFIG_MUTATION,
    "manifest": CommandClass.CONFIG_MUTATION,
    "mcp": CommandClass.READONLY_INSPECTION,
    "next": CommandClass.READONLY_INSPECTION,
    "orchestrate": CommandClass.DISPATCH_PAID_WORK,
    "plan": CommandClass.LIFECYCLE_MUTATION,
    "plan-review": CommandClass.DIAGNOSTIC_INSPECTION,
    "project": CommandClass.CONFIG_MUTATION,
    "projects": CommandClass.CONFIG_MUTATION,
    "ps": CommandClass.READONLY_INSPECTION,
    "quota-caps": CommandClass.CONFIG_MUTATION,
    "reconcile": CommandClass.CONFIG_MUTATION,
    "resume": CommandClass.LIFECYCLE_MUTATION,
    "roles": CommandClass.CONFIG_MUTATION,
    "setup": CommandClass.CONFIG_MUTATION,
    "showcase": CommandClass.READONLY_INSPECTION,
    "skills": CommandClass.READONLY_INSPECTION,
    "smoke": CommandClass.DIAGNOSTIC_INSPECTION,
    "state": CommandClass.READONLY_INSPECTION,
    "what-now": CommandClass.READONLY_INSPECTION,
}


# Subcommand surfaces that are riskier than a command's base class suggests.
# The inventory advertises the *riskiest* supported subcommand so an agent is
# never told a command is safer than one of its real paths (codex F002-i0):
# ``agent register-worker`` writes ``roles.<role>`` (a guarded config write) and
# ``mcp serve`` starts a long-running local server — neither is read-only.
_SUBCOMMAND_CLASS_OVERRIDES: dict[str, dict[str, CommandClass]] = {
    "agent": {"register-worker": CommandClass.CONFIG_MUTATION},
    "mcp": {"serve": CommandClass.LIFECYCLE_MUTATION},
}


# Caution ordering, least → most caution an agent must exercise. Used to pick
# the riskiest class among a command's base class and its flagged subcommands.
_CLASS_RISK_ORDER: tuple[CommandClass, ...] = (
    CommandClass.READONLY_INSPECTION,
    CommandClass.DIAGNOSTIC_INSPECTION,
    CommandClass.HUMAN_HANDOFF,
    CommandClass.CONFIG_MUTATION,
    CommandClass.LIFECYCLE_MUTATION,
    CommandClass.DISPATCH_PAID_WORK,
)


def _effective_class(command: str) -> CommandClass:
    """Effective class for a top-level command.

    Returns the most cautious of the command's base class and any flagged
    subcommand surface, so a command is never classified as safer than its
    riskiest supported subcommand.
    """
    candidates = [_CLASS_BY_COMMAND[command]]
    candidates.extend(_SUBCOMMAND_CLASS_OVERRIDES.get(command, {}).values())
    return max(candidates, key=_CLASS_RISK_ORDER.index)


_EXAMPLES_BY_COMMAND: dict[str, tuple[CommandExample, ...]] = {
    "agent": (
        _example("agent", "brief", description="Print the generated operating brief."),
        _example(
            "agent",
            "register-worker",
            "<name>",
            "--role",
            "implementer",
            "--dry-run",
            description="Preview assigning a registered worker to a role (guarded write).",
        ),
    ),
    "approve": (
        _example("approve", "<plan>", "<gate>", description="Approve a named gate."),
    ),
    "architecture": (
        _example("architecture", "status", description="Inspect architecture state."),
    ),
    "calibrate-claude": (
        _example(
            "calibrate-claude",
            "--window",
            "rolling_7d",
            "--dashboard-pct",
            "50",
            description="Record a quota calibration sample.",
        ),
    ),
    "capabilities": (
        _example("capabilities", "status", description="Inspect capability status."),
    ),
    "claude-touch": (
        _example("claude-touch", description="Check Claude CLI reachability."),
    ),
    "close": (
        _example(
            "close",
            "--operator-resolved",
            "<plan>",
            "<feature>",
            "--reason",
            "spec_ambiguity",
            description="Close an operator-resolved feature.",
        ),
    ),
    "config": (_example("config", description="Inspect or edit config."),),
    "dashboard": (
        _example("dashboard", "open", description="Open the local decision surface."),
    ),
    "dispatch-from-plan": (
        _example(
            "dispatch-from-plan",
            "<plan>",
            "--feature",
            "<feature>",
            description="Dispatch a specific feature after approval.",
        ),
    ),
    "doctor": (_example("doctor", "--agent", description="Run agent setup checks."),),
    "finalize": (
        _example(
            "finalize",
            "<plan>",
            "--feature",
            "<feature>",
            description="Finalize a signed-off feature without paid work.",
        ),
    ),
    "init": (_example("init", description="Initialize DontPanic state."),),
    "manifest": (
        _example("manifest", "show", "--json", description="Show manifest JSON."),
    ),
    "mcp": (_example("mcp", "serve", description="Start the MCP server."),),
    "next": (
        _example("next", "--format", "json", description="Inspect next safe actions."),
    ),
    "orchestrate": (
        _example(
            "orchestrate",
            "<plan>",
            "--feature",
            "<feature>",
            description="Teaching gateway for dispatching a feature.",
        ),
    ),
    "plan": (_example("plan", "lock", "<plan>", description="Lock a plan."),),
    "plan-review": (
        _example(
            "plan-review",
            "<plan>",
            "--format",
            "json",
            description="Inspect plan scope readiness.",
        ),
    ),
    "project": (_example("project", description="Inspect project config."),),
    "projects": (_example("projects", "list", description="List registered projects."),),
    "ps": (_example("ps", description="List active supervisors."),),
    "quota-caps": (
        _example("quota-caps", "show", description="Inspect quota caps."),
    ),
    "reconcile": (
        _example("reconcile", "homes", "--dry-run", description="Preview home reconciliation."),
    ),
    "resume": (_example("resume", "<plan>", "--all", description="Resume cleared gates."),),
    "roles": (_example("roles", "show", description="Inspect role assignments."),),
    "setup": (_example("setup", description="Configure project/runtime defaults."),),
    "showcase": (_example("showcase", description="Render showcase artifacts."),),
    "skills": (
        _example("skills", "recommend", "--format", "json", description="Inspect skill recommendations."),
    ),
    "smoke": (_example("smoke", description="Run smoke checks."),),
    "state": (_example("state", description="Export state."),),
    "what-now": (
        _example("what-now", "<plan>", "--format", "json", description="Inspect current actions."),
    ),
}


_PREDECESSORS_BY_CLASS: dict[CommandClass, tuple[str, ...]] = {
    CommandClass.READONLY_INSPECTION: ("Safe to run before mutation.",),
    CommandClass.DIAGNOSTIC_INSPECTION: ("Run before changing config or dispatching work.",),
    CommandClass.CONFIG_MUTATION: ("Inspect status/doctor output before changing config.",),
    CommandClass.LIFECYCLE_MUTATION: (
        "Inspect what-now/next first; do not auto-run unless DontPanic surfaced "
        "an automatable action or the user explicitly approved it.",
    ),
    CommandClass.DISPATCH_PAID_WORK: (
        "Inspect next/what-now first; dispatch only with an explicit ready candidate or approval.",
    ),
    CommandClass.HUMAN_HANDOFF: (
        "Use when DontPanic requires a human decision or visual inspection.",
    ),
}


_ESCALATION_BY_CLASS: dict[CommandClass, str] = {
    CommandClass.READONLY_INSPECTION: (
        "Do not ask the human before read-only inspection unless credentials or external services are required."
    ),
    CommandClass.DIAGNOSTIC_INSPECTION: (
        "Report diagnostics plainly; ask the human only for destructive repair or credential decisions."
    ),
    CommandClass.CONFIG_MUTATION: (
        "Ask the human before persistent configuration changes unless DontPanic surfaced an automatable action."
    ),
    CommandClass.LIFECYCLE_MUTATION: (
        "Proceed only for DontPanic-surfaced lifecycle actions; otherwise explain the consequence and ask."
    ),
    CommandClass.DISPATCH_PAID_WORK: (
        "Do not start paid/dispatch work unless DontPanic surfaced a ready candidate or the human explicitly approved it."
    ),
    CommandClass.HUMAN_HANDOFF: (
        "Show the local decision surface when available and avoid repeating the same prompt."
    ),
}


# Per-command overrides for commands whose riskiest subcommand differs from
# their most common entry point, so the generic class-derived text does not
# misdescribe the surface (codex F002-i0). Commands absent here fall back to
# the class-derived defaults above.
_PREDECESSORS_BY_COMMAND: dict[str, tuple[str, ...]] = {
    "agent": (
        "`agent brief`/`status` are read-only; inspect roles/config before the "
        "guarded `agent register-worker` write.",
    ),
    "mcp": (
        "`mcp serve` starts a long-running local MCP server; confirm the host "
        "actually needs it before launching.",
    ),
}


_ESCALATION_BY_COMMAND: dict[str, str] = {
    "agent": (
        "Read-only `agent brief`/`status` need no approval; ask the human before "
        "`agent register-worker`, which assigns a worker to a role."
    ),
    "mcp": (
        "Do not start the MCP server yourself — explain that `mcp serve` is a "
        "long-running process and let the operator or host launch it."
    ),
}


# Canonical agent entrypoint command — the read-only `agent` surface that
# carries `agent brief` (the generated operating brief) and `agent commands`
# (the machine guidance JSON). Projected through the inventory so a renamed or
# removed surface raises rather than leaving a stale root-help pointer.
_AGENT_ENTRYPOINT_COMMAND = "agent"


def root_help_agent_snippet() -> str:
    """Concise 'Start here for AI agents' block for the root ``--help``.

    Plan 2026-06-03-001 F004. This is the discovery pointer, not the manual: it
    names the two canonical agent entrypoints — the generated operating brief
    and the read-only JSON guidance surface — and the inspect-before-mutate
    rule, then stops. The full operating model lives in the generated brief
    (``dontpanic agent brief``); this snippet must never grow into a second copy
    of it. The command token is projected from the guidance inventory, so the
    pointer cannot drift if the ``agent`` surface is ever renamed or dropped.
    """
    entry = command_guidance_by_command()[_AGENT_ENTRYPOINT_COMMAND]
    cmd = entry.command
    return "\n".join(
        (
            "Start here (for AI agents):",
            f"  dontpanic {cmd} brief       Generated operating brief — read this first.",
            f"  dontpanic {cmd} commands    Machine command guidance as stable JSON",
            "                               (class, risk, examples, predecessor hints).",
            "  Inspect recommended actions (`next` / `what-now`) before mutating state",
            "  or dispatching paid work.",
        )
    )


# Human-readable class label for the per-command help footer (F005). Keyed on
# the closed :class:`CommandClass` vocabulary so a new class cannot ship a help
# snippet without a deliberate label here.
_CLASS_HELP_TITLE: dict[CommandClass, str] = {
    CommandClass.READONLY_INSPECTION: "read-only inspection",
    CommandClass.DIAGNOSTIC_INSPECTION: "diagnostic inspection",
    CommandClass.CONFIG_MUTATION: "configuration mutation",
    CommandClass.LIFECYCLE_MUTATION: "lifecycle mutation",
    CommandClass.DISPATCH_PAID_WORK: "dispatch / paid work",
    CommandClass.HUMAN_HANDOFF: "human handoff",
}


def command_help_agent_snippet(command: str) -> str:
    """Class-specific agent-guidance footer for a command's ``--help``.

    Plan 2026-06-03-001 F005. Projects the F002 inventory entry for ``command``
    into a short help footer so an agent reading ``dontpanic <command> --help``
    learns the safe operating policy for that command *class*, not just its
    flags: read-only surfaces say it is safe to inspect before mutation;
    lifecycle-mutation and dispatch/paid surfaces say not to auto-run unless
    DontPanic surfaced an automatable action or the human explicitly approved
    it; human-handoff surfaces point at the local decision surface.

    The text is the inventory's own predecessor hints and escalation rule — not
    a per-command restatement — so help and the JSON guidance surface cannot
    drift, and a renamed/removed command raises here rather than printing a
    stale snippet.
    """
    entry = command_guidance_by_command()[command]
    title = _CLASS_HELP_TITLE[entry.command_class]
    lines = [f"Agent guidance ({title}):"]
    lines.extend(f"  - {hint}" for hint in entry.predecessor_hints)
    lines.append(f"  Human escalation: {entry.human_escalation_rule}")
    return "\n".join(lines)


def known_command_paths() -> tuple[tuple[str, ...], ...]:
    """Projected top-level command paths from the validator vocabulary."""
    return tuple((command,) for command in sorted(command_validation.known_subcommands()))


def command_guidance_inventory() -> tuple[CommandGuidance, ...]:
    """Return metadata entries for every known top-level command.

    This is not an executable router. It is a pure metadata projection used by
    future help/JSON surfaces.
    """
    entries: list[CommandGuidance] = []
    for command in sorted(command_validation.known_subcommands()):
        command_class = _effective_class(command)
        predecessor_hints = _PREDECESSORS_BY_COMMAND.get(
            command, _PREDECESSORS_BY_CLASS[command_class]
        )
        human_escalation_rule = _ESCALATION_BY_COMMAND.get(
            command, _ESCALATION_BY_CLASS[command_class]
        )
        entries.append(
            CommandGuidance(
                path=(command,),
                command_class=command_class,
                examples=_EXAMPLES_BY_COMMAND[command],
                predecessor_hints=predecessor_hints,
                human_escalation_rule=human_escalation_rule,
            )
        )
    return tuple(entries)


def command_guidance_by_command() -> dict[str, CommandGuidance]:
    """Guidance inventory keyed by top-level command token."""
    return {entry.command: entry for entry in command_guidance_inventory()}


def inventory_public_payload() -> dict[str, object]:
    """Stable JSON-ready inventory envelope for the future CLI surface."""
    entries = command_guidance_inventory()
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "command_vocabulary": "dontpanic_orchestrate.command_validation.known_subcommands",
            "entry_count": len(entries),
        },
        "commands": [entry.as_public_dict() for entry in entries],
    }


__all__ = [
    "Audience",
    "CommandClass",
    "CommandExample",
    "CommandGuidance",
    "SCHEMA_VERSION",
    "command_guidance_by_command",
    "command_guidance_inventory",
    "inventory_public_payload",
    "known_command_paths",
]
