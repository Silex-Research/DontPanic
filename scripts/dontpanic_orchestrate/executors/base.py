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
from typing import Any, Literal

# F005b — non-interactive permission policy.
# Forbidden flags shortcut the permission system entirely and would defeat
# the role allowlist. Both Claude bypass flags + the Codex bypass.
FORBIDDEN_FLAGS: frozenset[str] = frozenset(
    {
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
        "--dangerously-bypass-approvals-and-sandbox",
    }
)


def check_forbidden_flags(argv: list[str]) -> None:
    """Raise ValueError if any forbidden bypass flag is in argv.

    Called by every executor before subprocess.run as a final pre-dispatch
    assertion. Defense-in-depth — produced argv should never contain these,
    but if a future change introduces an override path the guard catches it.
    """
    for flag in argv:
        if flag in FORBIDDEN_FLAGS:
            raise ValueError(f"forbidden flag in argv: {flag}")


# F005b — single source of truth for role → permission_policy mapping.
# Used by BOTH dispatch_single_agent (supervisor.py ~line 352) and
# dispatch_volley (supervisor.py ~line 1076). Unknown roles fall through
# to None so legacy code paths and synthetic-disagreement mocks behave
# exactly as before this change.
def _derive_permission_policy(
    agent_role: str | None,
) -> Literal["implementer", "auditor"] | None:
    if agent_role == "implementer":
        return "implementer"
    if agent_role == "auditor":
        return "auditor"
    return None


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
    # F023 EC11: agent subprocess cwd. Supervisor sets this to the consumer
    # repo root when the env registry resolves so .firebaserc / xcconfig / etc.
    # are picked up naturally. None means inherit supervisor cwd.
    cwd: Path | None = None
    # F005b: non-interactive permission policy derived from agent_role.
    # None = legacy / explicit no-policy (executors emit no permission flags,
    # preserving pre-F005b behavior for synthetic-disagreement mocks etc.).
    permission_policy: Literal["implementer", "auditor"] | None = None
    # F012 (D1/D011): resolved vendor model-id override. None = harness CLI
    # default (pre-F012 behavior); when set, executors forward it via the
    # vendor's model flag. Models are data, never registry keys (D010).
    model: str | None = None


@dataclass
class DispatchResult:
    agent: str
    agent_role: str
    iteration: int
    started_at: str  # ISO8601 UTC
    completed_at: str  # ISO8601 UTC
    success: bool  # subprocess exit 0 + non-empty response
    summary: str  # one-paragraph human-readable
    model_version: str | None = None
    raw_response: str = ""  # full stdout from CLI
    error: str | None = None
    quota_consumed: dict[str, Any] = field(default_factory=dict)
    # Plan 2026-05-04-003 F001: internal runner metadata consumed by later
    # envelope-durability features. Not serialized directly into audit JSON.
    subprocess_result: Any | None = None


class BaseExecutor(ABC):
    agent_name: str = ""  # subclass: "claude" | "codex" | "gemini" | "grok" | "ollama" | …
    cli_binary: str | None = None  # subclass: name of the CLI binary on PATH

    # F014 — the adapter's capability declaration (F011 vocabulary:
    # file_edit / tool_use / non_interactive). Conservative default: a
    # harness that does not explicitly declare more is audit-capable only
    # and can never hold the implementer role. Must agree with
    # config.worker_profiles.HARNESS_CAPABILITIES (the authoritative table
    # for role gating) — test_f014_harness_adapters guards the two against
    # drift.
    capabilities: frozenset[str] = frozenset({"non_interactive"})

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

    def list_models(self) -> list[str] | None:
        """F015 (D4) — optional model-catalog discovery. ``None`` means this
        harness has no discovery surface (documented pass-through): any
        freeform model string is forwarded to the vendor CLI via
        ``DispatchTask.model`` unverified. A harness adapter with a real
        catalog (a future ollama/openrouter executor) overrides this to
        return discovered model ids. Models are data, never AGENT_REGISTRY
        keys (D010)."""
        return None

    def availability_hint(self) -> str:
        """Operator-facing message when is_available() returns False."""
        if not self.cli_binary:
            return f"{self.agent_name}: no CLI binary configured"
        return f"{self.agent_name}: install/auth `{self.cli_binary}` (not on PATH)"
