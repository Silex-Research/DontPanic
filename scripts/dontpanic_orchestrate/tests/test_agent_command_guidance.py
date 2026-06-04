"""Prep tests for agent command-surface hardening F001/F002.

Run:
  PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_agent_command_guidance.py
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from dontpanic_orchestrate import command_guidance, command_validation
from dontpanic_orchestrate.command_guidance import (
    Audience,
    CommandClass,
    CommandExample,
    CommandGuidance,
)


def test_command_class_vocabulary_is_closed() -> None:
    assert issubclass(CommandClass, str)
    assert {member.value for member in CommandClass} == {
        "readonly_inspection",
        "lifecycle_mutation",
        "dispatch_paid_work",
        "configuration_mutation",
        "diagnostic_inspection",
        "human_handoff",
    }


def test_guidance_model_accepts_valid_entry_and_serializes_stably() -> None:
    entry = CommandGuidance(
        path=("what-now",),
        command_class=CommandClass.READONLY_INSPECTION,
        audience=(Audience.INTERACTIVE_AGENT,),
        examples=(
            CommandExample(
                argv=("what-now", "<plan>", "--format", "json"),
                description="Inspect current actions.",
            ),
        ),
        predecessor_hints=("Safe to inspect before mutation.",),
        human_escalation_rule="Ask only when DontPanic marks an action as human-required.",
    )

    payload = entry.as_public_dict()

    assert payload == {
        "path": ["what-now"],
        "command_class": "readonly_inspection",
        "audience": ["interactive_agent"],
        "examples": [
            {
                "argv": ["what-now", "<plan>", "--format", "json"],
                "description": "Inspect current actions.",
            }
        ],
        "predecessor_hints": ["Safe to inspect before mutation."],
        "human_escalation_rule": (
            "Ask only when DontPanic marks an action as human-required."
        ),
    }
    assert json.loads(entry.model_dump_json()) == payload


def test_guidance_model_rejects_unknown_class() -> None:
    with pytest.raises(ValidationError):
        CommandGuidance.model_validate(
            {
                "path": ["what-now"],
                "command_class": "kubernetes_orchestration",
                "examples": [],
                "predecessor_hints": [],
                "human_escalation_rule": "Ask a human.",
            }
        )


def test_guidance_model_rejects_malformed_examples() -> None:
    with pytest.raises(ValidationError, match="must start with"):
        CommandGuidance(
            path=("what-now",),
            command_class=CommandClass.READONLY_INSPECTION,
            examples=(
                CommandExample(
                    argv=("dispatch-from-plan", "<plan>"),
                    description="Wrong command path.",
                ),
            ),
            human_escalation_rule="Ask only for human-required decisions.",
        )


def test_inventory_covers_current_validator_vocabulary() -> None:
    inventory = command_guidance.command_guidance_by_command()

    assert set(inventory) == set(command_validation.known_subcommands())
    assert len(inventory) == len(command_validation.known_subcommands())


@pytest.mark.parametrize(
    ("command", "expected_class"),
    [
        ("what-now", CommandClass.READONLY_INSPECTION),
        ("doctor", CommandClass.DIAGNOSTIC_INSPECTION),
        ("dispatch-from-plan", CommandClass.DISPATCH_PAID_WORK),
        ("orchestrate", CommandClass.DISPATCH_PAID_WORK),
        ("approve", CommandClass.LIFECYCLE_MUTATION),
        ("roles", CommandClass.CONFIG_MUTATION),
        ("dashboard", CommandClass.HUMAN_HANDOFF),
    ],
)
def test_representative_inventory_classification(
    command: str,
    expected_class: CommandClass,
) -> None:
    inventory = command_guidance.command_guidance_by_command()
    entry = inventory[command]

    assert entry.command_class is expected_class
    assert entry.examples
    assert entry.predecessor_hints
    assert entry.human_escalation_rule


def test_inventory_payload_is_versioned_and_stable() -> None:
    payload = command_guidance.inventory_public_payload()

    assert payload["schema_version"] == command_guidance.SCHEMA_VERSION
    assert payload["source"] == {
        "command_vocabulary": (
            "dontpanic_orchestrate.command_validation.known_subcommands"
        ),
        "entry_count": len(command_validation.known_subcommands()),
    }
    assert len(payload["commands"]) == len(command_validation.known_subcommands())
    assert payload == json.loads(json.dumps(payload, sort_keys=True))


def test_inventory_is_metadata_not_executable_router() -> None:
    inventory = command_guidance.command_guidance_by_command()

    assert all(not callable(value) for value in inventory.values())
    assert not hasattr(command_guidance, "run")
    assert not hasattr(command_guidance, "execute")
