"""v3 F002 cost-lever tests.

Plan 2026-05-11-002-fix-harness-frictions-v3 F002 ships two narrow
levers that are safe with OAuth/keychain auth (i.e. won't break the
operator's subscription-based dispatch):

  1. `--exclude-dynamic-system-prompt-sections` on every Claude CLI
     dispatch — moves cwd/env/git/memory paths from the cached system
     prompt into the first user message, improving cache-reuse and
     reducing `cache_creation_input_tokens` per dispatch.

  2. `TEST_DISCIPLINE_NOTE` in the implementer prompt — instructs the
     agent to prefer targeted tests over full sweeps. Each subsequent
     turn re-reads prior tool output from the cache, so a 1800-line
     `pytest -q` (let alone `-v`) inflates every later turn's input.

The original F002 acceptance referenced "trim the prompt template to
<1.5M input tokens" but inspection found the prompt template is already
~5KB; the real cost driver is the agent's autonomous tool-use loop, not
the prompt text. These tests pin the two safe levers we control, leaving
re-measurement as a follow-up dispatch.

`--bare` was considered and rejected: it disables OAuth auth so it would
break the operator's current subscription-based setup. Recorded in the
plan's decisions.jsonl as D-entry rationale for why F002 took this shape
rather than the original "trim to <1.5M" framing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dontpanic_orchestrate.executors.base import DispatchTask
from dontpanic_orchestrate.executors.claude_cli import ClaudeCLIExecutor
from dontpanic_orchestrate.prompts import (
    TEST_DISCIPLINE_NOTE,
    implementer_prompt,
)


# ---------------------------------------------------------------------------
# Lever 1: --exclude-dynamic-system-prompt-sections on every dispatch
# ---------------------------------------------------------------------------


class _ArgvCapture:
    """Drop-in for run_subprocess that records argv and returns a fake proc."""

    def __init__(self) -> None:
        self.argv: list[str] = []

    def __call__(self, argv, *, input_data=None, env=None, cwd=None):  # noqa: ANN001
        self.argv = list(argv)

        class _Proc:
            stdout = b'{"result": "ok", "usage": {"input_tokens": 1, "output_tokens": 1}}'
            stderr = b""
            exit_code = 0
            timed_out = False
            timeout_seconds = 0.0

        return _Proc()


def _make_task(role: str) -> DispatchTask:
    return DispatchTask(
        plan_id="2026-05-11-002-fix-harness-frictions-v3",
        plan_dir=Path("/tmp"),
        feature_id="F002",
        feature_description="test",
        feature_acceptance="test",
        feature_steps=["step"],
        agent_role=role,
        permission_policy=role if role in {"implementer", "auditor"} else None,
    )


def test_implementer_dispatch_includes_exclude_dynamic_prompt_flag(monkeypatch):
    """Implementer must dispatch with --exclude-dynamic-system-prompt-sections."""
    capture = _ArgvCapture()
    monkeypatch.setattr(
        "dontpanic_orchestrate.executors.claude_cli.run_subprocess",
        capture,
    )
    executor = ClaudeCLIExecutor()
    executor.dispatch(_make_task("implementer"))
    assert "--exclude-dynamic-system-prompt-sections" in capture.argv, (
        f"flag missing from argv: {capture.argv!r}"
    )


def test_auditor_dispatch_includes_exclude_dynamic_prompt_flag(monkeypatch):
    """Auditor dispatch also gets the cache-friendly flag (cheap; no harm)."""
    capture = _ArgvCapture()
    monkeypatch.setattr(
        "dontpanic_orchestrate.executors.claude_cli.run_subprocess",
        capture,
    )
    executor = ClaudeCLIExecutor()
    executor.dispatch(_make_task("auditor"))
    assert "--exclude-dynamic-system-prompt-sections" in capture.argv


def test_legacy_no_policy_dispatch_still_gets_flag(monkeypatch):
    """Legacy / synthetic mocks (no permission_policy) still get the cache flag.

    The flag is a pre-permission-policy concern (system prompt rendering),
    so it belongs on every dispatch, not gated on policy.
    """
    capture = _ArgvCapture()
    monkeypatch.setattr(
        "dontpanic_orchestrate.executors.claude_cli.run_subprocess",
        capture,
    )
    executor = ClaudeCLIExecutor()
    task = _make_task("implementer")
    task.permission_policy = None
    executor.dispatch(task)
    assert "--exclude-dynamic-system-prompt-sections" in capture.argv


def test_flag_appears_before_permission_flags(monkeypatch):
    """argv ordering: -p, --output-format json, --exclude-dynamic-..., then policy.

    Ordering matters for readability of the dispatch logs but is not a
    correctness requirement of the Claude CLI itself.
    """
    capture = _ArgvCapture()
    monkeypatch.setattr(
        "dontpanic_orchestrate.executors.claude_cli.run_subprocess",
        capture,
    )
    executor = ClaudeCLIExecutor()
    executor.dispatch(_make_task("implementer"))
    exclude_idx = capture.argv.index("--exclude-dynamic-system-prompt-sections")
    policy_idx = capture.argv.index("--permission-mode")
    assert exclude_idx < policy_idx


# ---------------------------------------------------------------------------
# Lever 2: TEST_DISCIPLINE_NOTE in implementer prompt
# ---------------------------------------------------------------------------


def test_test_discipline_note_is_exported():
    """TEST_DISCIPLINE_NOTE is a public constant — visible to tests + ad-hoc inspection."""
    from dontpanic_orchestrate import prompts

    assert hasattr(prompts, "TEST_DISCIPLINE_NOTE")
    assert "TEST_DISCIPLINE_NOTE" in prompts.__all__


def test_test_discipline_note_mentions_targeted_over_sweep():
    """Body must instruct: targeted tests preferred over full sweeps."""
    body = TEST_DISCIPLINE_NOTE.lower()
    assert "targeted" in body
    assert "sweep" in body
    # Mentions cache_read mechanism so agent understands WHY, not just rule
    assert "cache" in body or "re-read" in body


def test_test_discipline_note_discourages_pytest_v():
    """`pytest -v` produces ~2000 lines of trace per run; agent must default away."""
    body = TEST_DISCIPLINE_NOTE
    assert "-v" in body
    assert "Never" in body or "never" in body


def test_implementer_iter0_prompt_contains_test_discipline():
    """Iteration 0 prompt embeds the discipline note."""
    feature = {
        "id": "F042",
        "description": "tiny test feature",
        "acceptance": "(1) ships; (2) tests pass",
        "steps": ["edit file", "run test"],
    }
    prompt = implementer_prompt(
        plan_id="2026-99-99-001-test-fixture",
        plan_dir=Path("/tmp/fixture"),
        feature=feature,
        iteration=0,
        target_env="dev",
        target_project=None,
    )
    assert "Test discipline" in prompt
    assert "targeted tests" in prompt or "targeted test file" in prompt


def test_implementer_iterN_prompt_contains_test_discipline():
    """Iteration N≥1 (with prior auditor findings) also contains the note."""
    feature = {
        "id": "F042",
        "description": "tiny test feature",
        "acceptance": "(1) ships",
        "steps": ["edit"],
    }
    prompt = implementer_prompt(
        plan_id="2026-99-99-001-test-fixture",
        plan_dir=Path("/tmp/fixture"),
        feature=feature,
        iteration=1,
        prior_auditor_path=Path("/does/not/exist.json"),
        target_env="dev",
        target_project=None,
    )
    assert "Test discipline" in prompt


# ---------------------------------------------------------------------------
# Prompt template size invariant: pin the actual measurement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("iteration", [0, 1])
def test_implementer_prompt_total_size_well_under_10kb(iteration):
    """Sanity bound: the assembled prompt (excluding tool-use loop) is small.

    The original D007 finding hypothesized prompt-template bloat as the
    cost driver. This test pins the actual size: a docs-style feature's
    full prompt is well under 10KB. The 4.92M `tokens_in` in the v3 F001
    baseline does NOT come from this surface — it accumulates from the
    agent's autonomous tool-use loop (cache_read of prior tool results).

    If this test ever fails (prompt > 10KB), someone has bloated the
    template and the original D007 hypothesis becomes relevant again.
    """
    feature = {
        "id": "F042",
        "description": "Tiny docs-style feature description (one paragraph).",
        "acceptance": "(1) ships; (2) tests pass.",
        "steps": ["edit one file", "run targeted test"],
    }
    prompt = implementer_prompt(
        plan_id="2026-99-99-001-test-fixture",
        plan_dir=Path("/tmp/fixture"),
        feature=feature,
        iteration=iteration,
        prior_auditor_path=Path("/does/not/exist.json") if iteration else None,
        target_env="dev",
        target_project=None,
    )
    assert len(prompt) < 10_000, (
        f"implementer prompt grew to {len(prompt)} bytes — "
        f"prompt-template bloat is now real (D007 hypothesis becomes relevant)"
    )
