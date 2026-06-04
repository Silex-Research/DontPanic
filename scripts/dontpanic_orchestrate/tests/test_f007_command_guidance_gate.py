"""Plan 2026-06-03-001 F007 — future-command guidance gate.

Regression coverage so a new top-level command, or a newly surfaced automatable
example, cannot ship without command guidance and validation coverage. The
guidance inventory is a projection over
:func:`command_validation.known_subcommands`; without these gates the only
signal of drift is a ``KeyError`` deep inside the inventory builder (a command
added to the validator vocabulary with no class/example entry) or a silently
missing help footer (a workflow command wired without the agent-guidance
epilog). These tests turn both into loud, readable failures.

Acceptance covered:

1. A test fails when the command-validation top-level vocabulary has a command
   with no guidance entry.
2. A test fails when a workflow-critical help page lacks an agent guidance
   section.
3. Automatable examples in command guidance validate against the existing
   command validator.
4. A developer-facing checklist explains how to add or change an agent-facing
   command without drift (asserted present and anchored to the real sources).
5. Command-validation and representative help tests pass (this module plus the
   F001 validator suite and the F005 help-snippet suite).

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f007_command_guidance_gate.py
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    cli,
    command_guidance,
    command_validation,
)

# Repo root — three parents up from scripts/dontpanic_orchestrate/tests/.
_REPO_ROOT = HERE.parents[3]
_CHECKLIST = _REPO_ROOT / "docs" / "AGENT_COMMAND_GUIDANCE_CHECKLIST.md"


def _help_output(argv: list[str]) -> str:
    """Capture a command's ``--help`` text. argparse exits 0 after printing."""
    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit) as excinfo:
            cli.main(argv)
    assert excinfo.value.code == 0
    return out.getvalue()


# ──────────────────  (1) every validator command has a guidance entry  ──────────────────


def test_every_validator_command_has_guidance_today() -> None:
    """The shipped vocabulary must have zero missing-guidance commands.

    This is the standing assertion; if a contributor adds a command to
    ``command_validation._VOCABULARY`` without a class + example entry, this
    fails with the offending command names instead of a deep ``KeyError``.
    """
    missing = command_guidance.missing_guidance_commands()
    assert missing == frozenset(), (
        "validator commands without a command-guidance entry: "
        f"{sorted(missing)} — add a class to _CLASS_BY_COMMAND and an example "
        "to _EXAMPLES_BY_COMMAND (see docs/AGENT_COMMAND_GUIDANCE_CHECKLIST.md)"
    )


def test_missing_guidance_gate_detects_a_new_unguided_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate must actually fire when a new command lands without guidance.

    Simulate a freshly added subcommand by extending the validator vocabulary
    and assert (a) the drift helper names it and (b) building the inventory
    raises — so the regression cannot be a no-op that always passes.
    """
    extended = dict(command_validation._VOCABULARY)
    extended["frobnicate"] = command_validation.SubcommandSpec()
    monkeypatch.setattr(command_validation, "_VOCABULARY", extended)

    # known_subcommands reads _VOCABULARY, so the new command is now "known".
    assert "frobnicate" in command_validation.known_subcommands()

    missing = command_guidance.missing_guidance_commands()
    assert "frobnicate" in missing

    # And the inventory builder itself refuses to project an unguided command.
    with pytest.raises(KeyError):
        command_guidance.command_guidance_inventory()


def test_guidance_inventory_has_exact_parity_with_validator() -> None:
    """No stale guidance entries either: the keysets must match exactly."""
    guided = set(command_guidance.command_guidance_by_command())
    known = set(command_validation.known_subcommands())
    assert guided == known


# ──────────────────  (2) workflow-critical help pages carry agent guidance  ──────────────────


# The argv that reaches each workflow-critical command's argparse ``--help``.
# ``plan`` is exercised through its ``lock`` subcommand (the lifecycle-mutation
# entry point that carries the epilog). The keyset MUST equal
# WORKFLOW_CRITICAL_HELP_COMMANDS — see the parity test below — so a command
# promoted to workflow-critical cannot be added to the constant without also
# wiring (and here exercising) its help page.
_HELP_ARGV: dict[str, list[str]] = {
    "next": ["next", "--help"],
    "doctor": ["doctor", "--help"],
    "setup": ["setup", "--help"],
    "plan": ["plan", "lock", "--help"],
    "dispatch-from-plan": ["dispatch-from-plan", "--help"],
    "dashboard": ["dashboard", "--help"],
}


def test_help_argv_map_matches_workflow_critical_constant() -> None:
    """The help-argv coverage map and the source-of-truth constant agree.

    If a contributor adds a command to WORKFLOW_CRITICAL_HELP_COMMANDS, they
    must also register how to reach its help here, and vice versa.
    """
    assert set(_HELP_ARGV) == set(command_guidance.WORKFLOW_CRITICAL_HELP_COMMANDS)


@pytest.mark.parametrize(
    "command",
    command_guidance.WORKFLOW_CRITICAL_HELP_COMMANDS,
    ids=list(command_guidance.WORKFLOW_CRITICAL_HELP_COMMANDS),
)
def test_workflow_critical_help_carries_agent_guidance_section(command: str) -> None:
    """(2) — each workflow-critical help page must render the agent-guidance
    footer. Removing the epilog wiring in cli.py/dashboard.py breaks this."""
    out = _help_output(_HELP_ARGV[command])
    # The shared helper's footer header...
    assert "Agent guidance (" in out
    # ...and the exact helper output for this command (so it cannot be a
    # hand-written look-alike that drifts from the inventory).
    assert command_guidance.command_help_agent_snippet(command) in out


def test_workflow_critical_commands_cover_every_command_class() -> None:
    """Every closed command class must own at least one workflow-critical help
    page, so no risk level can ship without an agent-guidance surface."""
    inventory = command_guidance.command_guidance_by_command()
    covered = {
        inventory[command].command_class
        for command in command_guidance.WORKFLOW_CRITICAL_HELP_COMMANDS
    }
    assert covered == set(command_guidance.CommandClass)


# ──────────────────  (3) automatable examples validate against the validator  ──────────────────


def test_every_guidance_example_validates_against_command_validator() -> None:
    """(3) — every example surfaced to agents (which includes the automatable
    read-only/diagnostic ones) must be a well-formed command per the existing
    token-shape validator, so a copy-pasteable example can never be malformed."""
    failures: list[str] = []
    for entry in command_guidance.command_guidance_inventory():
        for example in entry.examples:
            result = command_validation.validate_command_tokens(list(example.argv))
            if not result.ok:
                failures.append(f"{' '.join(example.argv)} -> {result.reason}")
    assert not failures, "guidance examples failing command validation:\n" + "\n".join(
        failures
    )


def test_automatable_class_examples_validate() -> None:
    """(3) — narrow the lens to the automatable classes (read-only inspection
    and diagnostic inspection): the surfaces an agent may run without approval.
    Their examples must validate, full stop."""
    automatable = {
        command_guidance.CommandClass.READONLY_INSPECTION,
        command_guidance.CommandClass.DIAGNOSTIC_INSPECTION,
    }
    checked = 0
    for entry in command_guidance.command_guidance_inventory():
        if entry.command_class not in automatable:
            continue
        for example in entry.examples:
            assert command_validation.validate_command_tokens(
                list(example.argv)
            ).ok, f"automatable example failed validation: {' '.join(example.argv)}"
            checked += 1
    # Guard against the loop silently checking nothing.
    assert checked > 0


# ──────────────────  (4) developer-facing checklist exists and is anchored  ──────────────────


def test_new_command_checklist_exists_and_references_the_real_sources() -> None:
    """(4) — the checklist must exist and name every drift-prone surface a
    contributor has to touch, so the doc cannot rot away from the code."""
    assert _CHECKLIST.is_file(), f"missing checklist at {_CHECKLIST}"
    text = _CHECKLIST.read_text(encoding="utf-8")
    for anchor in (
        "command_validation",
        "_CLASS_BY_COMMAND",
        "_EXAMPLES_BY_COMMAND",
        "command_help_agent_snippet",
        "WORKFLOW_CRITICAL_HELP_COMMANDS",
        "missing_guidance_commands",
    ):
        assert anchor in text, f"checklist does not mention {anchor!r}"


# ──────────────────  the gate helper is pure metadata, not a router  ──────────────────


def test_gate_helpers_have_no_side_effects() -> None:
    """missing_guidance_commands is a pure projection — calling it twice yields
    an identical frozenset and never mutates the vocabulary."""
    before = command_validation.known_subcommands()
    first = command_guidance.missing_guidance_commands()
    second = command_guidance.missing_guidance_commands()
    assert first == second
    assert command_validation.known_subcommands() == before
    assert isinstance(command_guidance.WORKFLOW_CRITICAL_HELP_COMMANDS, tuple)
