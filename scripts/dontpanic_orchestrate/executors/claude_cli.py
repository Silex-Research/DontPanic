"""Claude Code CLI executor — invokes `claude -p --output-format json`.

F005b: role-aware permission policy. When task.permission_policy is set,
the executor prepends non-interactive permission flags so subprocess
dispatch doesn't deadlock on permission prompts. None preserves legacy
behavior (no flags) for synthetic-disagreement mocks and pre-F005b tests.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil

from dontpanic_orchestrate.executors.base import (
    BaseExecutor,
    DispatchResult,
    DispatchTask,
    check_forbidden_flags,
)
from dontpanic_orchestrate.subprocess_runner import run_subprocess

DEFAULT_BIN = "claude"

# F005b — Claude implementer: writes inside cwd auto-allowed, broad Bash + Read.
# Auditor: Read-only, no Bash matchers (matcher-restricted Bash is not truly
# read-only; pytest writes caches, python is arbitrary code execution. See D012.)
_IMPLEMENTER_FLAGS: tuple[str, ...] = (
    "--permission-mode",
    "acceptEdits",
    "--allowedTools",
    "Read Edit Write Bash",
)
_AUDITOR_FLAGS: tuple[str, ...] = (
    "--permission-mode",
    "dontAsk",
    "--allowedTools",
    "Read",
)


def _permission_flags(policy: str | None) -> tuple[str, ...]:
    if policy == "implementer":
        return _IMPLEMENTER_FLAGS
    if policy == "auditor":
        return _AUDITOR_FLAGS
    return ()


class ClaudeCLIExecutor(BaseExecutor):
    agent_name = "claude"
    cli_binary = DEFAULT_BIN

    def __init__(self, binary: str = DEFAULT_BIN) -> None:
        self.binary = shutil.which(binary) or binary

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        prompt = self._build_prompt(task)
        started = dt.datetime.now(dt.timezone.utc)

        argv = [self.binary, "-p", "--output-format", "json"]
        argv.extend(_permission_flags(task.permission_policy))
        # F005b — final pre-dispatch assertion that no bypass flag slipped in.
        check_forbidden_flags(argv)

        proc = run_subprocess(
            argv,
            input_data=prompt,
            env=task.subprocess_env or None,
            cwd=task.cwd,
        )
        completed = dt.datetime.now(dt.timezone.utc)
        raw = proc.stdout.decode(errors="replace")

        if proc.timed_out:
            return DispatchResult(
                agent=self.agent_name,
                agent_role=task.agent_role,
                iteration=task.iteration,
                started_at=_iso(started),
                completed_at=_iso(completed),
                success=False,
                summary="",
                raw_response=raw,
                error=f"timeout after {proc.timeout_seconds}s",
                subprocess_result=proc,
            )

        if proc.exit_code != 0 or not raw.strip():
            return DispatchResult(
                agent=self.agent_name,
                agent_role=task.agent_role,
                iteration=task.iteration,
                started_at=_iso(started),
                completed_at=_iso(completed),
                success=False,
                summary="",
                raw_response=raw,
                error=f"exit={proc.exit_code}; stderr={proc.stderr[:300].decode(errors='replace')}",
                subprocess_result=proc,
            )

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return DispatchResult(
                agent=self.agent_name,
                agent_role=task.agent_role,
                iteration=task.iteration,
                started_at=_iso(started),
                completed_at=_iso(completed),
                success=False,
                summary="",
                raw_response=raw[:1000],
                error=f"JSON decode: {exc}",
                subprocess_result=proc,
            )

        summary = (payload.get("result") or "").strip()
        usage = payload.get("usage") or {}
        model_usage = payload.get("modelUsage") or {}
        model_version = next(iter(model_usage.keys()), None)

        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso(started),
            completed_at=_iso(completed),
            success=bool(summary) and not payload.get("is_error", False),
            summary=summary,
            model_version=model_version,
            raw_response=raw,
            quota_consumed={
                "tokens_in": int(usage.get("input_tokens") or 0)
                + int(usage.get("cache_read_input_tokens") or 0)
                + int(usage.get("cache_creation_input_tokens") or 0),
                "tokens_out": int(usage.get("output_tokens") or 0),
                "cost_usd": payload.get("total_cost_usd"),
                "duration_ms": payload.get("duration_ms"),
            },
            subprocess_result=proc,
        )

    def _build_prompt(self, task: DispatchTask) -> str:
        # Supervisor may inject a fully-formed prompt for volley dispatches.
        override = (task.extra_context or {}).get("prompt_override")
        if override:
            return str(override)
        steps_block = "\n".join(f"- {s}" for s in task.feature_steps) or "(none specified)"
        return f"""You are the {task.agent_role} for plan {task.plan_id}, iteration {task.iteration}.

Plan directory: {task.plan_dir}
Feature to {task.agent_role[:-2] if task.agent_role.endswith("er") else task.agent_role}: {task.feature_id}
Description: {task.feature_description}
Acceptance: {task.feature_acceptance}

Steps:
{steps_block}

Execute the feature. If verification commands are specified in steps, run them and confirm results.
Then reply with a single concise paragraph (3-6 sentences) summarizing exactly what you did and the outcome.
Do NOT output JSON; the supervisor wraps your reply.
"""


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")
