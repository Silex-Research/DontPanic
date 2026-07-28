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
from dontpanic_orchestrate.executors.ollama_cli import OllamaCLIExecutor
from dontpanic_orchestrate.executors.openrouter_api import OpenRouterAPIExecutor

# AGENT_REGISTRY = worker-DISPATCHABLE executors only. Grok is intentionally NOT
# here: per agent_surface.KNOWN_OPERATOR_AGENTS it is operator-only (it can operate
# DontPanic by running CLI commands but is not a dispatchable worker), and the
# GrokAPIExecutor module (executors/grok_api.py) notes it has no sandboxed tool-use
# / file-edit capability ("a future Grok CLI with tool use would be preferred").
# That module is intentionally NOT imported/registered here yet — registering it
# would let `roles set ... grok` accept a dispatch grok cannot safely perform
# (see test_f004_role_assignment / test_f002_agent_surface_cli, operator-only rc 3).
#
# F014: ollama/openrouter are AUDIT-ONLY harnesses (capabilities:
# non_interactive) — registration alone no longer implies every role: the
# implementer slot is capability-gated per harness (see
# config.worker_profiles.HARNESS_CAPABILITIES + worker_profiles.resolve_worker),
# which is what makes registering a chat-only harness safe where Grok's
# registration was not. gemini stays unregistered: D001 B2 requires proven
# non-interactive CLI smoke before a gemini_cli harness ships. Keys are stable
# harness ids — model version strings are NEVER registry keys (D010/D012).
AGENT_REGISTRY: dict[str, type[BaseExecutor]] = {
    "claude": ClaudeCLIExecutor,
    "codex": CodexCLIExecutor,
    "ollama": OllamaCLIExecutor,
    "openrouter": OpenRouterAPIExecutor,
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
    "OllamaCLIExecutor",
    "OpenRouterAPIExecutor",
    "get_executor",
]
