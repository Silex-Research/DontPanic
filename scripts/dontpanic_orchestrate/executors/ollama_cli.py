"""Ollama CLI executor — invokes `ollama run <model> <prompt>` (F014, Track D3).

Read-oriented harness: `ollama run` is a plain non-interactive chat
completion with NO sandboxed tool use or file editing, so the adapter
declares ``non_interactive`` only and may hold audit-style roles
(auditor / goal_auditor), never implementer. The refusal is enforced at
resolution (worker_profiles) and again here as defense-in-depth.

Model ids (``llama3.2:latest`` and friends) are DATA carried on
``DispatchTask.model`` (D010/D012) — there is no default model baked into
the adapter; dispatch without a resolved model is refused with an
operator-fixable message. Model discovery for the doctor lives in
:mod:`model_catalog` (``ollama list`` / ``ollama show``), which keeps its
dedicated discovery surface for this harness.
"""

from __future__ import annotations

import datetime as dt
import shutil

from dontpanic_orchestrate.executors.base import (
    BaseExecutor,
    DispatchResult,
    DispatchTask,
    check_forbidden_flags,
)
from dontpanic_orchestrate.subprocess_runner import run_subprocess

DEFAULT_BIN = "ollama"

CAPABILITIES: frozenset[str] = frozenset({"non_interactive"})
"""F014 capability declaration: chat-only, no file_edit / tool_use. Must
stay in sync with ``config.worker_profiles.HARNESS_CAPABILITIES`` — the
drift test in test_f014_harness_adapters asserts they agree."""


class OllamaCLIExecutor(BaseExecutor):
    agent_name = "ollama"
    cli_binary = DEFAULT_BIN
    capabilities = CAPABILITIES

    def __init__(self, binary: str = DEFAULT_BIN) -> None:
        self.binary = shutil.which(binary) or binary

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        started = dt.datetime.now(dt.timezone.utc)

        refusal = self._refusal_error(task)
        if refusal is not None:
            return self._failure(task, started, error=refusal)

        prompt = self._build_prompt(task)
        # Model is data resolved upstream (profile.model / role-level model);
        # there is no sane harness default for a local model store.
        argv: list[str] = [self.binary, "run", str(task.model), prompt]
        check_forbidden_flags(argv)

        proc = run_subprocess(
            argv,
            input_data=b"",
            env=task.subprocess_env or None,
            cwd=task.cwd,
        )
        completed = dt.datetime.now(dt.timezone.utc)
        raw = proc.stdout.decode(errors="replace")

        if proc.timed_out:
            return self._failure(
                task,
                started,
                completed=completed,
                raw=raw,
                error=f"timeout after {proc.timeout_seconds}s",
                proc=proc,
            )
        if proc.exit_code != 0 or not raw.strip():
            return self._failure(
                task,
                started,
                completed=completed,
                raw=raw,
                error=f"exit={proc.exit_code}; stderr={proc.stderr[:300].decode(errors='replace')}",
                proc=proc,
            )

        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso(started),
            completed_at=_iso(completed),
            success=True,
            summary=raw.strip(),
            model_version=None,  # requested model is recorded separately (D016)
            raw_response=raw,
            quota_consumed={},  # ollama run surfaces no token usage
            subprocess_result=proc,
        )

    def _refusal_error(self, task: DispatchTask) -> str | None:
        if task.agent_role == "implementer" or task.permission_policy == "implementer":
            return (
                "ollama harness refuses implementer dispatch: `ollama run` has no "
                "file_edit/tool_use sandbox (capabilities: non_interactive only). "
                "Assign a coding harness (claude/codex) to the implementer role."
            )
        if not task.model:
            return (
                "no model configured for ollama dispatch; set profile.model or a "
                "role-level model override (e.g. llama3.2:latest). Models are data, "
                "never registry keys (D010)."
            )
        return None

    def _failure(
        self,
        task: DispatchTask,
        started: dt.datetime,
        *,
        completed: dt.datetime | None = None,
        raw: str = "",
        error: str,
        proc: object | None = None,
    ) -> DispatchResult:
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso(started),
            completed_at=_iso(completed or dt.datetime.now(dt.timezone.utc)),
            success=False,
            summary="",
            raw_response=raw,
            error=error,
            subprocess_result=proc,
        )

    def _build_prompt(self, task: DispatchTask) -> str:
        override = (task.extra_context or {}).get("prompt_override")
        if override:
            return str(override)
        steps_block = "\n".join(f"- {s}" for s in task.feature_steps) or "(none specified)"
        return f"""You are the {task.agent_role} for plan {task.plan_id}, iteration {task.iteration}.

Plan directory: {task.plan_dir}
Feature: {task.feature_id}
Description: {task.feature_description}
Acceptance: {task.feature_acceptance}

Steps:
{steps_block}

You are a read-oriented reviewer: assess the feature against its acceptance criteria.
Reply with a single concise paragraph (3-6 sentences) summarizing your assessment.
Do NOT output JSON; the supervisor wraps your reply.
"""


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")
