"""Claude Code CLI executor — invokes `claude -p --output-format json`."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess

from jarvis_orchestrate.executors.base import (
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)

DEFAULT_BIN = "claude"


class ClaudeCLIExecutor(BaseExecutor):
    agent_name = "claude"
    cli_binary = DEFAULT_BIN

    def __init__(self, binary: str = DEFAULT_BIN) -> None:
        self.binary = shutil.which(binary) or binary

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        prompt = self._build_prompt(task)
        started = dt.datetime.now(dt.timezone.utc)

        try:
            proc = subprocess.run(
                [self.binary, "-p", "--output-format", "json"],
                input=prompt,
                capture_output=True,
                env=task.subprocess_env or None,
                cwd=str(task.cwd) if task.cwd else None,
                text=True,
                timeout=600,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            completed = dt.datetime.now(dt.timezone.utc)
            return DispatchResult(
                agent=self.agent_name,
                agent_role=task.agent_role,
                iteration=task.iteration,
                started_at=_iso(started),
                completed_at=_iso(completed),
                success=False,
                summary="",
                error=f"{type(exc).__name__}: {exc}",
            )

        completed = dt.datetime.now(dt.timezone.utc)
        raw = proc.stdout

        if proc.returncode != 0 or not raw.strip():
            return DispatchResult(
                agent=self.agent_name,
                agent_role=task.agent_role,
                iteration=task.iteration,
                started_at=_iso(started),
                completed_at=_iso(completed),
                success=False,
                summary="",
                raw_response=raw,
                error=f"exit={proc.returncode}; stderr={proc.stderr[:300]}",
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
