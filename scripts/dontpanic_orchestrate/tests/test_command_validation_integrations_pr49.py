"""PR49 follow-up (r3408996305): the ``integrations`` validator spec mirrors
the real subcommanded CLI (``smoke <integration>`` / ``attest <integration>
--action <id> --outcome passed|failed [--note <text>]``) instead of accepting
any two positionals, which let malformed commands validate as exact_command.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.command_validation import validate_command_tokens  # noqa: E402


@pytest.mark.parametrize(
    "tokens",
    [
        ["integrations", "smoke", "static-dashboard"],
        ["integrations", "smoke", "static-dashboard", "--plans-root", "docs/plans"],
        [
            "integrations",
            "attest",
            "linear-credentials",
            "--action",
            "linear-creds",
            "--outcome",
            "passed",
        ],
        [
            "integrations",
            "attest",
            "firebase-functions-deploy",
            "--action",
            "firebase-deploy",
            "--outcome",
            "failed",
            "--note",
            "region outage",
        ],
    ],
)
def test_real_cli_shapes_validate(tokens: list[str]) -> None:
    result = validate_command_tokens(tokens)
    assert result.ok, result.reason


@pytest.mark.parametrize(
    "tokens",
    [
        ["integrations", "foo", "bar"],  # unknown verb (old spec: ok)
        ["integrations", "smoke"],  # missing integration
        ["integrations", "smoke", "static-dashboard", "x"],  # extra positional
        ["integrations", "attest", "linear-credentials"],  # missing both flags
        ["integrations", "attest", "linear-credentials", "--action", "linear-creds"],
        ["integrations", "attest", "linear-credentials", "--outcome", "passed"],
        ["integrations", "smoke", "static-dashboard", "--action", "x"],  # attest-only flag
        ["integrations", "attest", "x", "--action", "y", "--outcome", "--note"],
        ["integrations"],  # bare verb
    ],
)
def test_malformed_shapes_are_rejected(tokens: list[str]) -> None:
    assert not validate_command_tokens(tokens).ok
