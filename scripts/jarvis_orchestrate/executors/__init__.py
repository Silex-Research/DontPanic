"""Per-vendor agent executors. Each implements BaseExecutor.dispatch()."""
from jarvis_orchestrate.executors.base import BaseExecutor, DispatchResult
from jarvis_orchestrate.executors.claude_cli import ClaudeCLIExecutor

__all__ = ["BaseExecutor", "DispatchResult", "ClaudeCLIExecutor"]
