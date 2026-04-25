"""BaseExecutor — common interface for vendor-specific agent dispatchers.

Each implementation translates a `DispatchTask` (plan + feature + role) into
an invocation of the vendor's CLI/API and returns a normalized `DispatchResult`.
The supervisor consumes these to build per-iteration Audit JSONs.

Subclasses override `dispatch()` and may override `is_available()`. The default
`is_available()` checks if the CLI binary is on PATH; override for richer probes
(auth state, env vars, network reachability).
"""
from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DispatchTask:
    plan_id: str
    plan_dir: Path
    feature_id: str
    feature_description: str
    feature_acceptance: str
    feature_steps: list[str]
    agent_role: str  # implementer | auditor | verifier | security | currency | …
    iteration: int = 0
    extra_context: dict[str, Any] = field(default_factory=dict)
    subprocess_env: dict[str, str] = field(default_factory=dict)


@dataclass
class DispatchResult:
    agent: str
    agent_role: str
    iteration: int
    started_at: str          # ISO8601 UTC
    completed_at: str        # ISO8601 UTC
    success: bool            # subprocess exit 0 + non-empty response
    summary: str             # one-paragraph human-readable
    model_version: str | None = None
    raw_response: str = ""   # full stdout from CLI
    error: str | None = None
    quota_consumed: dict[str, Any] = field(default_factory=dict)


class BaseExecutor(ABC):
    agent_name: str = ""             # subclass: "claude" | "codex" | "gemini" | "grok" | "ollama" | …
    cli_binary: str | None = None    # subclass: name of the CLI binary on PATH

    @abstractmethod
    def dispatch(self, task: DispatchTask) -> DispatchResult:
        """Execute the task synchronously. Must not raise on subprocess failure;
        return DispatchResult with success=False instead."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """Default: CLI binary on PATH. Subclasses may add auth/env probes."""
        if not self.cli_binary:
            return False
        return shutil.which(self.cli_binary) is not None

    def availability_hint(self) -> str:
        """Operator-facing message when is_available() returns False."""
        if not self.cli_binary:
            return f"{self.agent_name}: no CLI binary configured"
        return f"{self.agent_name}: install/auth `{self.cli_binary}` (not on PATH)"
