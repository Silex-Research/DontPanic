"""Per-vendor agent executors + registry.

Lookup: get_executor("claude") → ClaudeCLIExecutor instance.
Add new executors by importing here and registering in AGENT_REGISTRY.
"""

from dontpanic_orchestrate.executors.base import (
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)
from dontpanic_orchestrate.executors.claude_cli import ClaudeCLIExecutor
from dontpanic_orchestrate.executors.codex_cli import CodexCLIExecutor

# AGENT_REGISTRY = worker-DISPATCHABLE executors only. Grok is intentionally NOT
# here: per agent_surface.KNOWN_OPERATOR_AGENTS it is operator-only (it can operate
# DontPanic by running CLI commands but is not a dispatchable worker), and the
# GrokAPIExecutor module (executors/grok_api.py) notes it has no sandboxed tool-use
# / file-edit capability ("a future Grok CLI with tool use would be preferred").
# That module is intentionally NOT imported/registered here yet — registering it
# would let `roles set ... grok` accept a dispatch grok cannot safely perform
# (see test_f004_role_assignment / test_f002_agent_surface_cli, operator-only rc 3).
AGENT_REGISTRY: dict[str, type[BaseExecutor]] = {
    "claude": ClaudeCLIExecutor,
    "codex": CodexCLIExecutor,
}


def get_executor(agent_name: str) -> BaseExecutor:
    """Instantiate the executor for the named agent. Raises KeyError if unknown."""
    cls = AGENT_REGISTRY.get(agent_name)
    if cls is None:
        raise KeyError(f"unknown agent {agent_name!r}; registered: {sorted(AGENT_REGISTRY)}")
    return cls()


__all__ = [
    "AGENT_REGISTRY",
    "BaseExecutor",
    "ClaudeCLIExecutor",
    "CodexCLIExecutor",
    "DispatchResult",
    "DispatchTask",
    "get_executor",
]
