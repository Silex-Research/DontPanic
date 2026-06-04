"""Plan 2026-06-03-001 F006 — versioned local guide artifact.

A loadable, version-stamped DontPanic operating guide for agent/harness
environments that want an offline, version-matched "start here" document
without network access — and without maintaining a *second* command manual.

The guide is **generated**, never hand-maintained: its body is composed from
the live operating brief (:mod:`agent_brief`) and the F002 command-guidance
inventory (:mod:`command_guidance`). Those are the same sources of truth the
root help, the ``agent commands`` JSON surface, and the per-command help footers
read, so the guide cannot drift from the real command surface. Adding a command
class, an example, or editing the brief flows into the guide automatically; the
F006 tests assert that parity.

What the guide adds over the brief alone is the *agent operating policy* an
interactive harness needs to behave safely offline:

- the START HERE flow (inspect before mutating);
- the OPERATOR vs WORKER role distinction (embedded from the brief verbatim);
- the closed COMMAND CLASSES vocabulary with one SAFE EXAMPLE per class, drawn
  from the inventory;
- the LOCAL DECISION HANDOFF rule pointing at the dashboard / human-handoff
  surface;
- the no-inter-feature-prompt policy: do not ask the human between features
  unless DontPanic itself surfaces required human input.

Determinism: :func:`render_guide` is byte-stable for the same brief + inventory
(it embeds the deterministic brief text and sorts inventory projections), so a
managed/cached copy can detect staleness via :data:`RenderedGuide.content_hash`.

This module is read-only with respect to command behavior: it imports
``agent_brief`` and ``command_guidance`` metadata only and never resolves a
command path back to a handler or invokes one.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict

from dontpanic_orchestrate import agent_brief, command_guidance
from dontpanic_orchestrate.command_guidance import CommandGuidance

GUIDE_VERSION = "1.0"
"""Version of the guide layout/policy, independent of the DontPanic runtime
version and the brief generator version. Bump when the guide's structure or
required policy text changes."""

GUIDE_FILENAME = "agent-guide.md"
"""On-disk filename for the materialized guide under the DontPanic home. The
locator is ``<dontpanic_home>/agent-guide.md``."""


# ──────────────────────────────  canonical policy text  ──────────────────────────────

# The no-inter-feature-prompt policy (plan acceptance F006(2)). Asserted for
# presence by tests so it can never silently drift out of the guide. This is the
# product invariant that prevents an outer agent from manually driving
# feature-to-feature continuation or pausing for confirmation DontPanic did not
# ask for.
NO_INTER_FEATURE_PROMPT_POLICY = (
    "Do not ask the human between features unless DontPanic requires human input.\n"
    "DontPanic surfaces required human input explicitly — as a gate, a\n"
    "human-handoff action, or a dashboard decision. When no such surface is\n"
    "present, continue with the DontPanic-surfaced actions; do not manually drive\n"
    "feature-to-feature continuation and do not pause for confirmation DontPanic\n"
    "did not ask for."
)

# The START HERE flow shown to an offline agent. References the read-only
# discovery surfaces (brief + machine guidance + recommenders) and reuses the
# brief's own canonical workflow line for the lifecycle, so the guide never
# maintains a second copy of the workflow.
_START_HERE = (
    "1. Read the operating brief:   dontpanic agent brief\n"
    "2. Inspect machine guidance:   dontpanic agent commands   (stable JSON:\n"
    "   class, risk, examples, predecessor hints, human-escalation rule).\n"
    "3. Inspect recommended actions before mutating state or dispatching paid\n"
    "   work:   dontpanic next --format json   /   dontpanic what-now <plan>\n"
    "4. Execute only commands DontPanic surfaces as automatable actions or\n"
    "   explicit ready candidates. Follow the canonical lifecycle:\n"
    f"{agent_brief.CANONICAL_WORKFLOW}"
)


# ──────────────────────────────  typed output  ──────────────────────────────


class RenderedGuide(BaseModel):
    """Deterministic guide render plus the metadata a managed copy needs.

    ``text`` is the guide body and contains no hash (so the hash is not
    self-referential). ``content_hash`` is computed over the guide version and
    the body together, so either a layout bump or a fact change (brief or
    inventory) moves the hash and signals a stale cached copy.
    """

    model_config = ConfigDict(extra="forbid")

    guide_version: str
    brief_generator_version: str
    dontpanic_version: str
    content_hash: str
    text: str


# ──────────────────────────────  rendering helpers  ──────────────────────────────


def _content_hash(guide_version: str, text: str) -> str:
    payload = f"{guide_version}\n{text}".encode()
    return hashlib.sha256(payload).hexdigest()


def _entries_by_class(
    inventory: tuple[CommandGuidance, ...],
) -> dict[command_guidance.CommandClass, list[CommandGuidance]]:
    """Group inventory entries by class, each class's entries sorted by command
    so the rendered projection is deterministic."""
    grouped: dict[command_guidance.CommandClass, list[CommandGuidance]] = {}
    for entry in inventory:
        grouped.setdefault(entry.command_class, []).append(entry)
    for entries in grouped.values():
        entries.sort(key=lambda e: e.command)
    return grouped


def _render_command_classes(
    grouped: dict[command_guidance.CommandClass, list[CommandGuidance]],
) -> list[str]:
    """One line per class present in the inventory, in the inventory's caution
    order (least → most caution). Each line carries the class label and its
    shared escalation rule, projected from the inventory — never restated."""
    lines: list[str] = []
    for command_class in command_guidance._CLASS_RISK_ORDER:
        entries = grouped.get(command_class)
        if not entries:
            continue
        label = command_guidance.command_class_label(command_class)
        rule = command_guidance._ESCALATION_BY_CLASS[command_class]
        lines.append(f"- {label}: {rule}")
    return lines


def _render_safe_examples(
    grouped: dict[command_guidance.CommandClass, list[CommandGuidance]],
) -> list[str]:
    """One safe example per class, taken verbatim from the inventory. Each
    rendered line is a real ``CommandExample.argv`` so the F006 parity test can
    match it back to the inventory."""
    lines: list[str] = []
    for command_class in command_guidance._CLASS_RISK_ORDER:
        entries = grouped.get(command_class)
        if not entries:
            continue
        example = None
        owner = None
        for entry in entries:
            if entry.examples:
                example = entry.examples[0]
                owner = entry
                break
        if example is None or owner is None:
            continue
        label = command_guidance.command_class_label(command_class)
        lines.append(f"# {label} — {example.description}")
        lines.append(f"dontpanic {' '.join(example.argv)}")
    return lines


def _render_local_decision_handoff(
    grouped: dict[command_guidance.CommandClass, list[CommandGuidance]],
) -> list[str]:
    """Human-handoff guidance, projected from the inventory's HUMAN_HANDOFF
    entries (the local decision surface, e.g. ``dashboard``)."""
    entries = grouped.get(command_guidance.CommandClass.HUMAN_HANDOFF, [])
    rule = command_guidance._ESCALATION_BY_CLASS[
        command_guidance.CommandClass.HUMAN_HANDOFF
    ]
    lines = [
        "When DontPanic requires a human decision or visual inspection, hand off",
        "to the local decision surface instead of guessing:",
        f"  {rule}",
    ]
    for entry in entries:
        if entry.examples:
            example = entry.examples[0]
            # Description on its own comment line; the command line is exact
            # inventory argv only, so the F006 parity test can match every
            # rendered `dontpanic ...` line back to the inventory.
            lines.append(f"  # {example.description}")
            lines.append(f"  dontpanic {' '.join(example.argv)}")
    return lines


# ──────────────────────────────  rendering  ──────────────────────────────


def render_guide(
    *,
    brief: agent_brief.RenderedBrief | None = None,
    inventory: tuple[CommandGuidance, ...] | None = None,
) -> RenderedGuide:
    """Render the deterministic, version-stamped local operating guide.

    The brief and inventory default to live program facts but can be injected
    for testing. The output is byte-stable for the same inputs.
    """
    if brief is None:
        brief = agent_brief.generate_brief()
    if inventory is None:
        inventory = command_guidance.command_guidance_inventory()

    grouped = _entries_by_class(inventory)
    dontpanic_version = agent_brief.collect_brief_inputs().dontpanic_version

    sections: list[str] = [
        f"# DontPanic agent operating guide (guide {GUIDE_VERSION}, "
        f"runtime {dontpanic_version}, brief generator {brief.generator_version})",
        "",
        "Offline, version-matched 'start here' for interactive agents and",
        "harnesses. Generated from the operating brief and the command-guidance",
        "inventory — never a second hand-maintained manual.",
        "",
        "## START HERE",
        _START_HERE,
        "",
        "## OPERATING BRIEF (role distinction + supported commands)",
        "",
        # Embed the brief verbatim: this carries the OPERATOR vs WORKER role
        # distinction, the not-IT-orchestration clarification, the supported
        # command list, and the canonical workflow, all kept in lockstep with
        # the live brief.
        brief.text.rstrip("\n"),
        "",
        "## COMMAND CLASSES",
        "Every command falls into one of these classes. Treat the more cautious",
        "classes (configuration/lifecycle/dispatch) as write surfaces:",
        *_render_command_classes(grouped),
        "",
        "## SAFE EXAMPLES",
        "Read-only/diagnostic examples are safe to run before mutation; mutating,",
        "configuration, and dispatch examples require a DontPanic-surfaced action",
        "or explicit human approval first.",
        *_render_safe_examples(grouped),
        "",
        "## LOCAL DECISION HANDOFF",
        *_render_local_decision_handoff(grouped),
        "",
        "## NO INTER-FEATURE PROMPTS",
        NO_INTER_FEATURE_PROMPT_POLICY,
    ]
    text = "\n".join(sections) + "\n"
    return RenderedGuide(
        guide_version=GUIDE_VERSION,
        brief_generator_version=brief.generator_version,
        dontpanic_version=dontpanic_version,
        content_hash=_content_hash(GUIDE_VERSION, text),
        text=text,
    )


# ──────────────────────────────  locator / materialization  ──────────────────────────────


def guide_path(home):
    """On-disk locator for the materialized guide under a DontPanic home.

    ``home`` is a :class:`pathlib.Path` (the resolved DontPanic home). Pure: it
    computes the path but does not read, write, or create anything.
    """
    return home / GUIDE_FILENAME


def write_guide(home) -> object:
    """Materialize the guide to the locator path under ``home`` and return it.

    The caller is responsible for ensuring ``home`` exists (the CLI passes the
    ``ensure_dontpanic_home()`` result). Byte-stable content: re-writing an
    up-to-date guide produces an identical file.
    """
    path = guide_path(home)
    path.write_text(render_guide().text, encoding="utf-8")
    return path


__all__ = [
    "GUIDE_FILENAME",
    "GUIDE_VERSION",
    "NO_INTER_FEATURE_PROMPT_POLICY",
    "RenderedGuide",
    "guide_path",
    "render_guide",
    "write_guide",
]
