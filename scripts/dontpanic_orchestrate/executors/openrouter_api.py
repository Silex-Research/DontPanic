"""OpenRouter API executor — chat completions over HTTPS (F014, Track D3).

OpenRouter is a HARNESS (D012): one transport adapter, unbounded model
slugs (``openai/gpt-5.2``, ``x-ai/grok-4.5``, …) carried as DATA on
``DispatchTask.model``. There is no default model and no model is ever an
AGENT_REGISTRY key.

Read-oriented harness: a chat completion has NO sandboxed tool use or
file editing, so the adapter declares ``non_interactive`` only and may
hold audit-style roles (auditor / goal_auditor), never implementer. The
refusal is enforced at resolution (worker_profiles) and again here as
defense-in-depth.

Availability is an env probe (``OPENROUTER_API_KEY``) — there is no CLI
binary. The key is read from the dispatch env at call time and is never
embedded in argv, results, or errors. Model discovery for the doctor
stays in :mod:`model_catalog` (models API + offline cache).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request

from dontpanic_orchestrate.executors.base import (
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)

API_KEY_ENV = "OPENROUTER_API_KEY"
CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
_REQUEST_TIMEOUT_SECONDS = 600

CAPABILITIES: frozenset[str] = frozenset({"non_interactive"})
"""F014 capability declaration: chat-only, no file_edit / tool_use. Must
stay in sync with ``config.worker_profiles.HARNESS_CAPABILITIES`` — the
drift test in test_f014_harness_adapters asserts they agree."""


def _post_chat(payload: dict, api_key: str, timeout: int) -> dict:
    """POST the chat-completion payload; returns the decoded JSON body.

    Module-level seam so unit tests monkeypatch this instead of the
    network. Raises OSError/HTTPError/JSONDecodeError on failure — the
    executor converts those into a failed DispatchResult.
    """
    request = urllib.request.Request(  # noqa: S310 — fixed https vendor endpoint
        CHAT_COMPLETIONS_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode())


class OpenRouterAPIExecutor(BaseExecutor):
    agent_name = "openrouter"
    cli_binary = None  # API harness — availability is the env-key probe
    capabilities = CAPABILITIES

    def is_available(self) -> bool:
        return bool(os.environ.get(API_KEY_ENV, "").strip())

    def availability_hint(self) -> str:
        return (
            f"{self.agent_name}: set {API_KEY_ENV} "
            "(create a key at https://openrouter.ai/keys)"
        )

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        started = dt.datetime.now(dt.timezone.utc)

        error = self._refusal_error(task)
        if error is not None:
            return self._failure(task, started, error=error)

        api_key = (task.subprocess_env or {}).get(API_KEY_ENV) or os.environ.get(
            API_KEY_ENV, ""
        )
        if not api_key.strip():
            return self._failure(
                task,
                started,
                error=f"{API_KEY_ENV} is not set; export it or add it to the dispatch env",
            )

        payload = {
            "model": task.model,
            "messages": [{"role": "user", "content": self._build_prompt(task)}],
        }
        try:
            body = _post_chat(payload, api_key.strip(), _REQUEST_TIMEOUT_SECONDS)
            choices = body.get("choices") or []
            summary = ((choices[0].get("message") or {}).get("content") or "").strip()
        except Exception as exc:  # noqa: BLE001 — dispatch must not raise (BaseExecutor contract)
            return self._failure(task, started, error=str(exc))

        completed = dt.datetime.now(dt.timezone.utc)
        usage = body.get("usage") or {}
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso(started),
            completed_at=_iso(completed),
            success=bool(summary),
            summary=summary,
            model_version=body.get("model"),
            # raw_response is the model's reply text, mirroring the CLI
            # harnesses' raw-stdout contract: completion/sufficiency
            # callers parse it as the auditor's response. The vendor
            # envelope must never land here (i1 — codex audit i0 high:
            # a valid assistant `[]` parsed as dispatch_response_malformed).
            raw_response=summary,
            error=None if summary else "empty completion from OpenRouter",
            quota_consumed={
                "tokens_in": int(usage.get("prompt_tokens") or 0),
                "tokens_out": int(usage.get("completion_tokens") or 0),
            },
        )

    def _refusal_error(self, task: DispatchTask) -> str | None:
        if task.agent_role == "implementer" or task.permission_policy == "implementer":
            return (
                "openrouter harness refuses implementer dispatch: chat completions "
                "have no file_edit/tool_use sandbox (capabilities: non_interactive "
                "only). Assign a coding harness (claude/codex) to the implementer role."
            )
        if not task.model:
            return (
                "no model configured for openrouter dispatch; set profile.model or a "
                "role-level model override (an OpenRouter slug such as "
                "openai/gpt-5.2). Models are data, never registry keys (D010)."
            )
        return None

    def _failure(
        self, task: DispatchTask, started: dt.datetime, *, error: str
    ) -> DispatchResult:
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso(started),
            completed_at=_iso(dt.datetime.now(dt.timezone.utc)),
            success=False,
            summary="",
            error=error,
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
