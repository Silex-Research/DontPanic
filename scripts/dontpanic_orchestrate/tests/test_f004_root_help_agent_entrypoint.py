"""Plan 2026-06-03-001 F004 — root help agent entrypoint.

The bare ``dontpanic --help`` (and the no-args usage) must carry a concise
"Start here (for AI agents)" block that points interactive agents at the
generated operating brief and the read-only JSON guidance surface, and tells
them to inspect recommended actions before mutating state. The block is
rendered from the shared guidance helper (projected over the F002 inventory),
not a hand-maintained command list, and it must not restate the full brief.

Acceptance covered:

1. Root help includes a concise 'Start here for AI agents' section.
2. The section names the generated brief and the JSON guidance surface.
3. The section tells agents to inspect recommended actions before mutation.
4. The text is produced from shared guidance constants / F002 metadata, not a
   separate command list.
5. Tests assert the root help contains the entrypoint and does not duplicate
   the full brief.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f004_root_help_agent_entrypoint.py
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import agent_brief  # noqa: E402
from dontpanic_orchestrate import cli  # noqa: E402
from dontpanic_orchestrate import command_guidance  # noqa: E402


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


# ──────────────────────  (1) the section exists and is concise  ──────────────────────


def test_help_has_start_here_for_agents_section() -> None:
    rc, out, _ = _run(["--help"])
    assert rc == 0
    assert "Start here (for AI agents):" in out


def test_no_args_usage_also_carries_the_entrypoint() -> None:
    """Bare invocation prints usage to stderr and must carry the same pointer so
    an agent that runs ``dontpanic`` with no command is sent to the brief."""
    rc, _, err = _run([])
    assert rc == 2
    assert "Start here (for AI agents):" in err


def test_snippet_is_concise() -> None:
    """(1) 'concise' — the pointer is a handful of lines, not a manual."""
    snippet = command_guidance.root_help_agent_snippet()
    assert snippet.count("\n") <= 8


# ──────────────────────  (2) names brief + JSON guidance surface  ──────────────────────


def test_section_names_generated_brief_and_json_surface() -> None:
    rc, out, _ = _run(["--help"])
    assert rc == 0
    assert "dontpanic agent brief" in out
    assert "dontpanic agent commands" in out


# ──────────────────────  (3) inspect recommended actions before mutation  ──────────────────────


def test_section_tells_agents_to_inspect_before_mutation() -> None:
    rc, out, _ = _run(["--help"])
    assert rc == 0
    lowered = out.lower()
    assert "inspect" in lowered
    assert "before mutating" in lowered
    # Names the read-only recommenders agents should consult first.
    assert "next" in lowered and "what-now" in lowered


# ──────────────────────  (4) sourced from shared guidance, not an ad-hoc list  ──────────────────────


def test_help_renders_the_shared_guidance_helper_verbatim() -> None:
    """The help text embeds the shared helper output exactly, proving the
    section is produced from the guidance module rather than restated inline."""
    rc, out, _ = _run(["--help"])
    assert rc == 0
    assert command_guidance.root_help_agent_snippet() in out


def test_snippet_command_token_is_projected_from_the_inventory() -> None:
    """(4) — the entrypoint token comes from the F002 inventory, so a renamed
    or dropped ``agent`` surface raises rather than leaving a stale pointer."""
    inventory = command_guidance.command_guidance_by_command()
    assert command_guidance._AGENT_ENTRYPOINT_COMMAND in inventory
    cmd = inventory[command_guidance._AGENT_ENTRYPOINT_COMMAND].command
    assert f"dontpanic {cmd} brief" in command_guidance.root_help_agent_snippet()


# ──────────────────────  (5) does not duplicate the full brief  ──────────────────────


def test_help_points_at_the_brief_without_restating_it() -> None:
    """The root help must send agents to the brief, not reproduce it. Assert the
    full brief's distinctive section headers and the not-IT-orchestration block
    are absent from the help output."""
    rc, out, _ = _run(["--help"])
    assert rc == 0

    brief_text = agent_brief.generate_brief().text
    assert brief_text not in out
    # Distinctive full-brief markers must not leak into the concise pointer.
    for marker in (
        "DontPanic operating brief",
        "OPERATOR vs WORKER",
        "SUPPORTED COMMANDS",
        "WORKER EXECUTORS",
        agent_brief.NOT_IT_ORCHESTRATION,
    ):
        assert marker not in out
