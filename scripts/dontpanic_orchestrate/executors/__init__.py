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
