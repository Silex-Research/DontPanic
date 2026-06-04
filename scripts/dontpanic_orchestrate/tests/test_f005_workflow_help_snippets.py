"""Plan 2026-06-03-001 F005 — workflow help policy snippets.

The command help pages an interactive agent most often touches must carry a
short, class-specific agent-guidance footer so read-only, lifecycle-mutation,
dispatch/paid, configuration-mutation, diagnostic, and human-handoff surfaces
teach *different* safe behavior. The footer is projected from the F002 command
inventory through the shared ``command_help_agent_snippet`` helper, not a
per-command ad-hoc string, so help and the JSON guidance surface cannot drift.

Acceptance covered:

1. Representative help output for each command class contains class-appropriate
   agent guidance.
2. Dispatch/paid and lifecycle-mutation help says not to auto-run unless
   DontPanic surfaced an automatable action or the user explicitly approved it.
3. Read-only help says it is safe to inspect before mutation.
4. Human-handoff help points to the local decision surface when available.
5. Tests cover one representative command per class and prove the snippets come
   from the shared inventory/helper, not ad-hoc strings.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f005_workflow_help_snippets.py
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import cli, command_guidance  # noqa: E402
from dontpanic_orchestrate.command_guidance import CommandClass  # noqa: E402


def _help_output(argv: list[str]) -> str:
    """Capture a command's ``--help`` text. argparse exits 0 after printing."""
    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit) as excinfo:
            cli.main(argv)
    assert excinfo.value.code == 0
    return out.getvalue()


# One representative command per closed command class, with the argv that
# reaches that command's argparse ``--help``. ``plan`` is exercised through its
# ``lock`` subcommand (the lifecycle-mutation entry point).
_REPRESENTATIVES: tuple[tuple[str, CommandClass, list[str]], ...] = (
    ("next", CommandClass.READONLY_INSPECTION, ["next", "--help"]),
    ("doctor", CommandClass.DIAGNOSTIC_INSPECTION, ["doctor", "--help"]),
    ("setup", CommandClass.CONFIG_MUTATION, ["setup", "--help"]),
    ("plan", CommandClass.LIFECYCLE_MUTATION, ["plan", "lock", "--help"]),
    (
        "dispatch-from-plan",
        CommandClass.DISPATCH_PAID_WORK,
        ["dispatch-from-plan", "--help"],
    ),
    ("dashboard", CommandClass.HUMAN_HANDOFF, ["dashboard", "--help"]),
)


# ──────────────────────  (5) one representative per class, sourced from the helper  ──────────────────────


@pytest.mark.parametrize(
    ("command", "expected_class", "help_argv"),
    _REPRESENTATIVES,
    ids=[c for c, _, _ in _REPRESENTATIVES],
)
def test_help_embeds_shared_snippet_verbatim(
    command: str,
    expected_class: CommandClass,
    help_argv: list[str],
) -> None:
    """(1)+(5) — each representative's help embeds the shared helper output
    exactly. Because the footer is the helper's return value, it cannot be a
    hand-written restatement, and the inventory class drives the text."""
    # Guard: the representative really is the class we claim to be testing.
    inventory = command_guidance.command_guidance_by_command()
    assert inventory[command].command_class is expected_class

    snippet = command_guidance.command_help_agent_snippet(command)
    out = _help_output(help_argv)
    assert snippet in out


def test_each_class_has_a_distinct_snippet() -> None:
    """(1) — the six classes must teach *different* behavior, not one generic
    block. Distinct command-class labels + inventory text guarantee that."""
    snippets = {
        command: command_guidance.command_help_agent_snippet(command)
        for command, _, _ in _REPRESENTATIVES
    }
    assert len(set(snippets.values())) == len(snippets)


def test_snippet_is_built_from_inventory_fields_not_ad_hoc() -> None:
    """(5) — prove the snippet is composed from the F002 inventory entry's own
    predecessor hints and escalation rule, not a string literal in the helper."""
    for command, _, _ in _REPRESENTATIVES:
        entry = command_guidance.command_guidance_by_command()[command]
        snippet = command_guidance.command_help_agent_snippet(command)
        for hint in entry.predecessor_hints:
            assert hint in snippet
        assert entry.human_escalation_rule in snippet


# ──────────────────────  (3) read-only says it is safe to inspect before mutation  ──────────────────────


def test_readonly_help_says_safe_to_inspect_before_mutation() -> None:
    out = _help_output(["next", "--help"]).lower()
    assert "agent guidance (read-only inspection):" in out
    assert "safe to run before mutation" in out


# ──────────────────────  (2) dispatch + lifecycle: no auto-run without a surfaced action / approval  ──────────────────────


def test_dispatch_help_warns_against_auto_running_paid_work() -> None:
    out = _help_output(["dispatch-from-plan", "--help"])
    lowered = out.lower()
    assert "agent guidance (dispatch / paid work):" in lowered
    # Must say: don't dispatch unless DontPanic surfaced a candidate OR the
    # human approved — both halves of the AC#2 condition.
    assert "do not start paid/dispatch work unless dontpanic surfaced" in lowered
    assert "explicitly approved" in lowered


def test_lifecycle_help_warns_against_auto_mutating() -> None:
    out = _help_output(["plan", "lock", "--help"])
    lowered = out.lower()
    assert "agent guidance (lifecycle mutation):" in lowered
    # AC#2 — both halves: don't auto-run unless DontPanic surfaced an
    # automatable action OR the user explicitly approved it.
    assert "do not auto-run unless dontpanic surfaced" in lowered
    assert "the user explicitly approved it" in lowered
    # ... and the otherwise-ask-the-human (approval) escalation path.
    assert "dontpanic-surfaced lifecycle actions" in lowered
    assert "ask" in lowered


# ──────────────────────  (4) human-handoff points to the local decision surface  ──────────────────────


def test_human_handoff_help_points_to_local_decision_surface() -> None:
    out = _help_output(["dashboard", "--help"]).lower()
    assert "agent guidance (human handoff):" in out
    assert "local decision surface when available" in out


# ──────────────────────  diagnostics + config carry their own class guidance  ──────────────────────


def test_diagnostic_help_carries_diagnostic_guidance() -> None:
    out = _help_output(["doctor", "--help"]).lower()
    assert "agent guidance (diagnostic inspection):" in out
    assert "before changing config or dispatching work" in out


def test_config_help_carries_config_guidance() -> None:
    out = _help_output(["setup", "--help"]).lower()
    assert "agent guidance (configuration mutation):" in out
    assert "inspect status/doctor output before changing config" in out


# ──────────────────────  behavior unchanged: the footer is help-only  ──────────────────────


def test_snippet_helper_raises_for_unknown_command() -> None:
    """The helper projects over the inventory; an unknown command must raise
    rather than emit a stale snippet (mirrors the F004 entrypoint contract)."""
    with pytest.raises(KeyError):
        command_guidance.command_help_agent_snippet("not-a-real-command")
