"""Scripted smoke executors (plan 2026-08-09-003 F002).

Generalize the original MockClaudeExecutor / MockCodexExecutor to replay
a scenario's replies — including malformed envelopes — while still
subclassing BaseExecutor with is_available() == True. Default
construction (no scenario) preserves the hardcoded signed_off replies
so existing smoke callers are unchanged.

Never reaches the network or invokes a paid CLI.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from dontpanic_orchestrate.executors.base import (
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)
from dontpanic_orchestrate.smoke.chaos import ChaosInjector
from dontpanic_orchestrate.smoke.loader import Scenario, ScriptedReply


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _TimeoutSubprocess:
    """Stand-in matching audit_writer's timeout evidence helpers."""

    timed_out: bool = True
    timeout_seconds: int = 30
    grace_period_used: bool = False
    captured_stdout_bytes: int = 0
    captured_stderr_bytes: int = 0
    stdout: bytes = b""
    stderr: bytes = b""
    worktree_changed: bool | None = False
    env_markers: list[str] = field(default_factory=list)
    exit_code: int | None = None
    pgid: int = 0


@dataclass
class _ExitSubprocess:
    timed_out: bool = False
    timeout_seconds: int = 30
    grace_period_used: bool = False
    captured_stdout_bytes: int = 0
    captured_stderr_bytes: int = 0
    stdout: bytes = b""
    stderr: bytes = b""
    worktree_changed: bool | None = False
    env_markers: list[str] = field(default_factory=list)
    exit_code: int = 1
    pgid: int = 0


def _default_claude_reply(task: DispatchTask) -> ScriptedReply:
    return ScriptedReply(
        agent="claude",
        role=task.agent_role,
        iteration=task.iteration,
        summary=(
            f"[smoke mock claude/{task.agent_role}] "
            f"synthetic implementer envelope for {task.feature_id} "
            f"(iter={task.iteration}). No real CLI invoked."
        ),
        raw_response="signed_off",
        quota_consumed={"tokens_in": 0, "tokens_out": 0},
    )


def _default_codex_reply(task: DispatchTask) -> ScriptedReply:
    return ScriptedReply(
        agent="codex",
        role=task.agent_role,
        iteration=task.iteration,
        summary=(
            "Overall verdict: signed_off.\n"
            f"[smoke mock codex/{task.agent_role}] "
            f"synthetic auditor envelope for {task.feature_id} "
            f"(iter={task.iteration}). No findings; no real CLI invoked."
        ),
        raw_response="signed_off",
        quota_consumed={"tokens_in": 0, "tokens_out": 0},
    )


def _apply_malformed(reply: ScriptedReply) -> ScriptedReply:
    if reply.malformed == "truncated_json":
        truncated = reply.raw_response or reply.summary or '{"audit_status":'
        if truncated.endswith("}"):
            truncated = truncated[:-7]
        return ScriptedReply(
            agent=reply.agent,
            role=reply.role,
            iteration=reply.iteration,
            summary=truncated,
            success=reply.success,
            raw_response=truncated,
            malformed=reply.malformed,
            quota_consumed=dict(reply.quota_consumed),
        )
    if reply.malformed == "missing_keys":
        return ScriptedReply(
            agent=reply.agent,
            role=reply.role,
            iteration=reply.iteration,
            summary="",
            success=reply.success,
            raw_response="",
            malformed=reply.malformed,
            quota_consumed=dict(reply.quota_consumed),
        )
    if reply.malformed == "verdict_mismatch":
        # Leading newline so audit_writer's `[F00N] ` prefix does not sit
        # on the verdict line (detect_verdict_mismatch is line-anchored).
        # A high finding makes the structured status needs_changes/blocked;
        # the supervisor's existing detector then raises.
        summary = (
            "\nOverall verdict: signed_off.\n"
            "FINDING (high, correctness): structured status will disagree "
            "with the narrative verdict line above because of this finding."
        )
        return ScriptedReply(
            agent=reply.agent,
            role=reply.role,
            iteration=reply.iteration,
            summary=summary,
            success=True,
            raw_response=reply.raw_response or "signed_off",
            malformed=reply.malformed,
            quota_consumed=dict(reply.quota_consumed),
        )
    return reply


class _ScriptedExecutor(BaseExecutor):
    cli_binary = None
    call_count: int

    def __init__(
        self,
        scenario: Scenario | None = None,
        *,
        chaos: ChaosInjector | None = None,
    ) -> None:
        self.scenario = scenario
        self.chaos = chaos or ChaosInjector(
            scenario.perturbations if scenario is not None else ()
        )
        self.call_count = 0

    def is_available(self) -> bool:  # noqa: D401 — overrides BaseExecutor
        return True

    def _default_reply(self, task: DispatchTask) -> ScriptedReply:
        raise NotImplementedError

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.call_count += 1
        perturbation = self.chaos.on_dispatch(task.agent_role, self.agent_name)
        if perturbation is not None and perturbation.kind == "timeout":
            return DispatchResult(
                agent=self.agent_name,
                agent_role=task.agent_role,
                iteration=task.iteration,
                started_at=_iso_now(),
                completed_at=_iso_now(),
                success=False,
                summary="",
                error="timeout",
                model_version="smoke-mock",
                raw_response="",
                quota_consumed={"tokens_in": 0, "tokens_out": 0},
                subprocess_result=_TimeoutSubprocess(),
            )
        if perturbation is not None and perturbation.kind == "nonzero_exit":
            exit_code = perturbation.exit_code if perturbation.exit_code is not None else 1
            return DispatchResult(
                agent=self.agent_name,
                agent_role=task.agent_role,
                iteration=task.iteration,
                started_at=_iso_now(),
                completed_at=_iso_now(),
                success=False,
                summary="",
                error=f"exit {exit_code}",
                model_version="smoke-mock",
                raw_response="",
                quota_consumed={"tokens_in": 0, "tokens_out": 0},
                subprocess_result=_ExitSubprocess(exit_code=exit_code),
            )

        reply: ScriptedReply | None = None
        if self.scenario is not None:
            reply = self.scenario.reply_for(
                self.agent_name, task.agent_role, task.iteration
            )
        if reply is None:
            reply = self._default_reply(task)
        reply = _apply_malformed(reply)
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=reply.success,
            summary=reply.summary,
            model_version=None if reply.malformed == "missing_keys" else "smoke-mock",
            raw_response=reply.raw_response,
            quota_consumed=dict(reply.quota_consumed),
        )


class MockClaudeExecutor(_ScriptedExecutor):
    """Synthetic implementer executor. See module docstring."""

    agent_name = "claude"

    def _default_reply(self, task: DispatchTask) -> ScriptedReply:
        return _default_claude_reply(task)


class MockCodexExecutor(_ScriptedExecutor):
    """Synthetic auditor executor. See module docstring."""

    agent_name = "codex"

    def _default_reply(self, task: DispatchTask) -> ScriptedReply:
        return _default_codex_reply(task)
