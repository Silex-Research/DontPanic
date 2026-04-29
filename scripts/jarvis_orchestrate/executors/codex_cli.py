"""Codex CLI executor — invokes `codex exec --json`.

Codex emits newline-delimited JSON events to stdout; the agent's response is the
`item.text` field of the `item.completed` event whose `item.type == agent_message`.
Usage data appears in the `turn.completed` event.

F005b: role-aware permission policy. Global flags (--ask-for-approval,
--sandbox) are inserted BEFORE the `exec` subcommand per Codex CLI
convention; `codex --help` confirms these are global, not subcommand-local.
None preserves legacy behavior (no flags) for synthetic-disagreement mocks.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess

from jarvis_orchestrate.executors.base import (
    BaseExecutor,
    DispatchResult,
    DispatchTask,
    check_forbidden_flags,
)

DEFAULT_BIN = "codex"

# F005b — Codex implementer: workspace-write sandbox enforces edit-in-cwd at
# the OS level. Auditor: read-only sandbox refuses any write at the OS level
# regardless of what command Codex tries — the right place for command-running
# audit (pytest --collect-only, git log/diff/status, etc.) since the kernel
# enforces no-mutation. See D012.
_IMPLEMENTER_FLAGS: tuple[str, ...] = (
    "--ask-for-approval",
    "never",
    "--sandbox",
    "workspace-write",
)
_AUDITOR_FLAGS: tuple[str, ...] = (
    "--ask-for-approval",
    "never",
    "--sandbox",
    "read-only",
)


def _permission_flags(policy: str | None) -> tuple[str, ...]:
    if policy == "implementer":
        return _IMPLEMENTER_FLAGS
    if policy == "auditor":
        return _AUDITOR_FLAGS
    return ()


class CodexCLIExecutor(BaseExecutor):
    agent_name = "codex"
    cli_binary = DEFAULT_BIN

    def __init__(self, binary: str = DEFAULT_BIN) -> None:
        self.binary = shutil.which(binary) or binary

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        prompt = self._build_prompt(task)
        started = dt.datetime.now(dt.timezone.utc)

        # Global flags MUST come before the `exec` subcommand per Codex CLI.
        argv: list[str] = [self.binary]
        argv.extend(_permission_flags(task.permission_policy))
        argv.extend(["exec", "--json", prompt])
        # F005b — final pre-dispatch assertion that no bypass flag slipped in.
        check_forbidden_flags(argv)

        try:
            proc = subprocess.run(
                argv,
                input="",
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

        summary, usage = self._parse_event_stream(raw)

        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso(started),
            completed_at=_iso(completed),
            success=bool(summary),
            summary=summary,
            model_version=None,  # codex CLI doesn't surface model version in event stream
            raw_response=raw,
            quota_consumed={
                "tokens_in": int(usage.get("input_tokens") or 0)
                + int(usage.get("cached_input_tokens") or 0),
                "tokens_out": int(usage.get("output_tokens") or 0)
                + int(usage.get("reasoning_output_tokens") or 0),
            },
        )

    def _parse_event_stream(self, stdout: str) -> tuple[str, dict]:
        """Walk newline-JSON events, extract last agent_message text + last turn usage."""
        text = ""
        usage: dict = {}
        for line in stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    text = (item.get("text") or "").strip()
            elif etype == "turn.completed":
                usage = event.get("usage") or {}
        return text, usage

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

Execute the feature according to your role. If verification commands are specified, run them.
Reply with a single concise paragraph (3-6 sentences) summarizing exactly what you did and the outcome.
Do NOT output JSON; the supervisor wraps your reply.
"""


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")
