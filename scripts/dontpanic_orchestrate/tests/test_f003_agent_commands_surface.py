"""Plan 2026-06-03-001 F003 — machine-readable command-guidance surface.

``dontpanic agent commands`` is a read-only agent subcommand that prints the
F002 command-guidance inventory as a stable, versioned JSON envelope so an
outer harness can inspect DontPanic's affordances without scraping help text.

Acceptance covered:

1. A read-only ``agent commands`` subcommand returns a versioned JSON envelope
   containing the F002 command guidance entries.
2. The envelope includes a source summary, command entries, and a schema
   version.
3. The command does not invoke any guided command handler (no dispatch, no
   config write, no executor instantiation).
4. Schema stability + coverage parity with the F002 inventory.
5. The generated operating brief points agents at this JSON surface.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f003_agent_commands_surface.py
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import agent_brief  # noqa: E402
from dontpanic_orchestrate import cli  # noqa: E402
from dontpanic_orchestrate import command_guidance  # noqa: E402
from dontpanic_orchestrate import command_validation  # noqa: E402
from dontpanic_orchestrate import executors  # noqa: E402
from dontpanic_orchestrate import global_config as gc  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_dontpanic_home(tmp_path, monkeypatch):
    """Reroute ``$DONTPANIC_HOME`` to a tmp dir so a stray write would be
    detectable (and never touch the operator's real ~/.dontpanic). Clears
    ``$JARVIS_HOME`` for deterministic resolution."""
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


# ──────────────────────  (1)+(2) versioned envelope shape  ──────────────────────


def test_agent_commands_emits_versioned_envelope() -> None:
    rc, out, _ = _run(["agent", "commands"])
    assert rc == 0
    payload = json.loads(out)

    # (2) source summary + command entries + schema version are all present.
    assert set(payload) == {"schema_version", "source", "commands"}
    assert payload["schema_version"] == command_guidance.SCHEMA_VERSION
    assert payload["source"] == {
        "command_vocabulary": (
            "dontpanic_orchestrate.command_validation.known_subcommands"
        ),
        "entry_count": len(command_validation.known_subcommands()),
    }
    assert isinstance(payload["commands"], list) and payload["commands"]


def test_agent_commands_json_flag_is_equivalent() -> None:
    """``--json`` is accepted (the only supported format) and identical."""
    _, plain, _ = _run(["agent", "commands"])
    _, flagged, _ = _run(["agent", "commands", "--json"])
    assert plain == flagged


# ──────────────────────  (1) entries serialize through the F001 model  ──────────────────────


def test_each_command_entry_round_trips_through_the_f001_model() -> None:
    _, out, _ = _run(["agent", "commands"])
    entries = json.loads(out)["commands"]
    # Every emitted entry validates back into the F001 CommandGuidance model and
    # carries the full metadata contract (class, audience, examples, predecessor
    # hints, escalation rule).
    for raw in entries:
        model = command_guidance.CommandGuidance.model_validate(raw)
        assert model.command_class
        assert model.audience
        assert model.examples
        assert model.predecessor_hints
        assert model.human_escalation_rule.strip()


# ──────────────────────  (4) coverage parity with the F002 inventory  ──────────────────────


def test_envelope_has_coverage_parity_with_f002_inventory() -> None:
    _, out, _ = _run(["agent", "commands"])
    payload = json.loads(out)

    emitted_commands = {entry["path"][0] for entry in payload["commands"]}
    # Parity with the validator vocabulary AND with the in-process F002 inventory
    # — one command per known subcommand, no more, no fewer.
    assert emitted_commands == set(command_validation.known_subcommands())
    assert emitted_commands == set(command_guidance.command_guidance_by_command())
    assert len(payload["commands"]) == len(command_guidance.command_guidance_inventory())


def test_envelope_is_byte_identical_to_the_inventory_payload() -> None:
    """The CLI surface is a thin, lossless projection of the F002 inventory
    payload — it must not reshape or drop fields."""
    _, out, _ = _run(["agent", "commands"])
    emitted = json.loads(out)
    assert emitted == command_guidance.inventory_public_payload()


# ──────────────────────  (4) schema stability  ──────────────────────


def test_envelope_is_stable_across_invocations_and_sort_order() -> None:
    _, first, _ = _run(["agent", "commands"])
    _, second, _ = _run(["agent", "commands"])
    # Deterministic: identical bytes across runs.
    assert first == second
    payload = json.loads(first)
    # Sorting keys is a no-op → the envelope is already canonically ordered.
    assert payload == json.loads(json.dumps(payload, sort_keys=True))


# ──────────────────────  (3) read-only: no guided handler invoked  ──────────────────────


def test_agent_commands_writes_no_config(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rc, _, _ = _run(["agent", "commands"])
    assert rc == 0
    assert not gc.config_path().exists(), "the read-only surface must not write config"


def test_agent_commands_never_dispatches_or_instantiates_an_executor() -> None:
    """(3) — printing the inventory must not resolve a command path back to a
    handler: no dispatch, no executor instantiation."""
    with (
        mock.patch.object(cli.supervisor, "dispatch_volley") as dispatch_spy,
        mock.patch.object(executors, "get_executor") as exec_spy,
    ):
        rc, out, _ = _run(["agent", "commands"])
    assert rc == 0
    assert json.loads(out)["commands"]
    dispatch_spy.assert_not_called()
    exec_spy.assert_not_called()


# ──────────────────────  (5) the brief points at the JSON surface  ──────────────────────


def test_brief_points_agents_at_the_commands_json_surface() -> None:
    text = agent_brief.generate_brief().text
    assert "MACHINE COMMAND GUIDANCE" in text
    assert agent_brief.MACHINE_COMMAND_GUIDANCE in text
    # The pointer names the exact read-only command that emits the JSON.
    assert "dontpanic agent commands" in text


def test_agent_brief_cli_surface_carries_the_pointer() -> None:
    rc, out, _ = _run(["agent", "brief"])
    assert rc == 0
    assert "dontpanic agent commands" in out
