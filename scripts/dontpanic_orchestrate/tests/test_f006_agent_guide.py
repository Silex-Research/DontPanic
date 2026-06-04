"""Plan 2026-06-03-001 F006 — versioned local guide artifact.

A loadable, version-stamped DontPanic operating guide for agent/harness
environments that want an offline, version-matched "start here" document —
without network access and without maintaining a second command manual. The
guide is *generated* from the live operating brief and the F002 command-guidance
inventory, so it can never drift from the real command surface, and it is
locatable/printable from the existing ``dontpanic agent`` surface.

Acceptance covered:

1. A version-stamped local guide artifact exists and can be located or printed
   by an existing DontPanic surface.
2. The guide contains the start-here flow, role distinction, command classes,
   safe examples, local-decision handoff rule, and the
   'do not ask between features unless DontPanic requires human input' policy.
3. The guide is generated from / validated against the generated brief and the
   command inventory.
4. Root help (or the generated brief) points to the guide locator.
5. Tests prove guide existence, required policy text, and command-inventory
   parity.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f006_agent_guide.py
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    agent_brief,
    agent_guide,
    cli,
    command_guidance,
)


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


# ──────────────────────  (1) version-stamped artifact exists  ──────────────────────


def test_guide_is_version_stamped() -> None:
    guide = agent_guide.render_guide()
    assert agent_guide.GUIDE_VERSION in guide.text
    # Stamped with both the guide layout version and the runtime version it was
    # generated against, so a harness can tell whether the guide matches its CLI.
    assert agent_brief.collect_brief_inputs().dontpanic_version in guide.text
    assert guide.guide_version == agent_guide.GUIDE_VERSION
    assert guide.content_hash


def test_guide_render_is_deterministic() -> None:
    assert agent_guide.render_guide().text == agent_guide.render_guide().text
    assert (
        agent_guide.render_guide().content_hash
        == agent_guide.render_guide().content_hash
    )


def test_guide_is_printable_from_the_agent_surface() -> None:
    rc, out, _ = _run(["agent", "guide"])
    assert rc == 0
    assert out == agent_guide.render_guide().text


def test_guide_is_locatable_from_the_agent_surface() -> None:
    rc, out, _ = _run(["agent", "guide", "--path"])
    assert rc == 0
    printed = out.strip()
    assert printed.endswith(agent_guide.GUIDE_FILENAME)


def test_guide_can_be_written_to_the_local_locator(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))
    rc, out, _ = _run(["agent", "guide", "--write"])
    assert rc == 0
    written = Path(out.strip())
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == agent_guide.render_guide().text


# ──────────────────────  (2) required content + policy text  ──────────────────────


def test_guide_contains_start_here_flow() -> None:
    text = agent_guide.render_guide().text
    assert "START HERE" in text
    # The canonical workflow line comes straight from the brief.
    assert agent_brief.CANONICAL_WORKFLOW in text
    assert "dontpanic agent brief" in text
    assert "dontpanic agent commands" in text


def test_guide_contains_role_distinction() -> None:
    text = agent_guide.render_guide().text
    assert "OPERATOR vs WORKER" in text
    assert agent_brief.NOT_IT_ORCHESTRATION in text


def test_guide_contains_every_command_class() -> None:
    text = agent_guide.render_guide().text
    assert "COMMAND CLASSES" in text
    for entry in command_guidance.command_guidance_inventory():
        label = command_guidance.command_class_label(entry.command_class)
        assert label in text


def test_guide_contains_local_decision_handoff_rule() -> None:
    text = agent_guide.render_guide().text
    assert "LOCAL DECISION HANDOFF" in text
    # Points at the local decision surface (the dashboard / human-handoff class).
    assert "dashboard" in text


def test_guide_contains_no_inter_feature_prompt_policy() -> None:
    text = agent_guide.render_guide().text
    assert agent_guide.NO_INTER_FEATURE_PROMPT_POLICY in text
    lowered = text.lower()
    assert "do not ask" in lowered
    assert "between features" in lowered
    assert "requires human input" in lowered


# ──────────────────────  (3)/(5) generated-from parity with brief + inventory  ──────────────────────


def test_guide_embeds_the_generated_brief_verbatim() -> None:
    """(3) — the guide is generated from the brief, not a hand-copied manual:
    the full brief body appears verbatim, so brief edits flow into the guide."""
    text = agent_guide.render_guide().text
    assert agent_brief.generate_brief().text in text


def test_guide_safe_examples_come_from_the_inventory() -> None:
    """(5) command-inventory parity — every safe example in the guide is a real
    inventory example argv, not an ad-hoc string."""
    text = agent_guide.render_guide().text
    real_examples = {
        "dontpanic " + " ".join(example.argv)
        for entry in command_guidance.command_guidance_inventory()
        for example in entry.examples
    }
    assert "SAFE EXAMPLES" in text
    # Every command-like line in the guide — any line that starts with
    # `dontpanic ` once stripped — must be an exact inventory example argv,
    # nothing more (no trailing description, no ad-hoc command). This proves
    # full command-inventory parity, not just that *some* lines match.
    rendered = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("dontpanic ")
    ]
    assert rendered, "guide rendered no `dontpanic ...` command lines"
    drift = [line for line in rendered if line not in real_examples]
    assert not drift, f"guide rendered command lines absent from inventory: {drift}"
    # At least one example per command class with examples is rendered.
    classes_with_examples = {
        entry.command_class
        for entry in command_guidance.command_guidance_inventory()
        if entry.examples
    }
    assert len(rendered) >= len(classes_with_examples)


def test_guide_changes_when_inventory_grows(monkeypatch) -> None:
    """The guide is a projection of the inventory: adding a representative
    example must change the rendered guide, proving it is generated, not static.

    The guide renders one example per class (the alphabetically-first command in
    that class), so the probe sorts first to become the class's chosen example.
    """
    base = agent_guide.render_guide().text

    original = command_guidance.command_guidance_inventory

    def _augmented() -> tuple:
        entries = list(original())
        extra = command_guidance.CommandGuidance(
            path=("aaa-probe",),
            command_class=command_guidance.CommandClass.READONLY_INSPECTION,
            examples=(
                command_guidance.CommandExample(
                    argv=("aaa-probe", "--json"),
                    description="probe example",
                ),
            ),
            predecessor_hints=("probe hint",),
            human_escalation_rule="probe escalation",
        )
        return tuple(entries) + (extra,)

    monkeypatch.setattr(
        command_guidance, "command_guidance_inventory", _augmented
    )
    grown = agent_guide.render_guide().text
    assert grown != base
    assert "dontpanic aaa-probe --json" in grown


# ──────────────────────  (4) root help points at the guide locator  ──────────────────────


def test_root_help_points_at_the_guide_locator() -> None:
    rc, out, _ = _run(["--help"])
    assert rc == 0
    assert "agent guide" in out


def test_root_help_snippet_names_the_guide() -> None:
    snippet = command_guidance.root_help_agent_snippet()
    assert "agent guide" in snippet
