"""BaseExecutor — common interface for vendor-specific agent dispatchers.

Each implementation translates a `DispatchTask` (plan + feature + role) into
an invocation of the vendor's CLI/API and returns a normalized `DispatchResult`.
The supervisor consumes these to build per-iteration Audit JSONs.
"""
from __future__ import annotations

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
    agent_name: str = ""  # set by subclass

    @abstractmethod
    def dispatch(self, task: DispatchTask) -> DispatchResult:
        """Execute the task synchronously. Must not raise on subprocess failure;
        return DispatchResult with success=False instead."""
        raise NotImplementedError
