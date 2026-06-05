"""Plan 2026-06-04-006 F003 — emit-only agent-handoff bundle.

`build_bundle` turns the F002-ordered, safety-classified repair actions into a
machine-readable JSON bundle an external agentic operator (Codex / Claude / Grok)
executes. It is the DEFAULT `dontpanic repair` behavior: emit only, ZERO
mutation. Execution requires the explicit `repair apply` subcommand (F004).

Each emitted action carries the six contract fields — command, safety_class,
apply_tier, clears_when, plain_consequence, scope — plus its id, resolution_class,
and dependency edges. The emitted ``safety_class`` is the EFFECTIVE value from
:func:`repair_safety.resolve_safety`, not the raw producer assertion: an
unclassified or policy-failing action is reported as ``human_required`` so the
bundle never overstates what may auto-run (fail closed, D003).

:func:`action_to_repair_action` adapts a live ActionItem into a
:class:`repair_planner.RepairAction`, reading PRODUCER-ASSERTED safety off the
item (``safety_class`` / ``apply_tier`` / ``repair_kind`` / ``depends_on``) — it
never infers safety. A legacy item whose producer declared none yields None and
therefore fails closed downstream.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from . import action_resolvability as _ar
from . import repair_planner as _rp
from . import repair_safety as _rs


def action_to_repair_action(card: Any) -> _rp.RepairAction:
    """Adapt a live ActionItem (or any duck-typed card) into a RepairAction.

    Reads producer-asserted safety via attribute access; absent fields stay None
    / empty so the safety policy fails them closed. Display fields pass through:
    ``exact_command`` -> command, plus plain_consequence / scope / clears_when /
    resolution_class.
    """
    return _rp.RepairAction(
        id=getattr(card, "id"),
        kind=getattr(card, "repair_kind", None) or getattr(card, "kind", None),
        safety_class=getattr(card, "safety_class", None),
        apply_tier=getattr(card, "apply_tier", None),
        resolution_class=getattr(card, "resolution_class", _ar.RESOLUTION_COMMAND_RESOLVABLE),
        clears_when=getattr(card, "clears_when", None),
        depends_on=tuple(getattr(card, "depends_on", ()) or ()),
        command=getattr(card, "exact_command", None),
        plain_consequence=getattr(card, "plain_consequence", None),
        scope=getattr(card, "scope", None),
    )


def _emit_action(action: _rp.RepairAction) -> dict[str, Any]:
    safety_class, apply_tier = _rs.resolve_safety(action)
    cw = action.clears_when
    return {
        "id": action.id,
        "command": action.command,
        "safety_class": safety_class,
        "apply_tier": apply_tier,
        "resolution_class": action.resolution_class,
        "clears_when": cw.to_dict() if cw is not None else None,
        "plain_consequence": action.plain_consequence,
        "scope": action.scope,
        "depends_on": list(action.depends_on),
    }


def build_bundle(
    actions: "Sequence[_rp.RepairAction]", *, scope: str
) -> dict[str, Any]:
    """Build the dependency-ordered, safety-classified emit bundle. PURE: reads
    ``actions``, mutates nothing, writes nothing. Cyclic actions are surfaced
    under ``deferred`` (reason ``cycle``) rather than dropped silently."""
    ordered, cyclic = _rp.order_actions(actions)
    return {
        "scope": scope,
        "actions": [_emit_action(a) for a in ordered],
        "deferred": [
            {"id": aid, "reason": _rp.DEFER_CYCLE} for aid in sorted(cyclic)
        ],
    }


def render_json(bundle: dict[str, Any]) -> str:
    """Serialize the bundle as indented JSON (the agent-handoff format)."""
    return json.dumps(bundle, indent=2)


def render_human(bundle: dict[str, Any]) -> str:
    """A short human-readable summary of the bundle: scope, per-class counts, and
    the ordered action list."""
    actions = bundle["actions"]
    counts: dict[str, int] = {}
    for a in actions:
        counts[a["safety_class"]] = counts.get(a["safety_class"], 0) + 1
    lines = [f"Repair plan for scope: {bundle['scope']}"]
    # Stable class order so the summary reads the same every run.
    for cls in (_rs.AUTO_SAFE, _rs.HUMAN_REQUIRED, _rs.BLOCKED_EXTERNAL, _rs.INFO):
        lines.append(f"  {cls}: {counts.get(cls, 0)}")
    if bundle["deferred"]:
        lines.append(f"  deferred (cycle): {len(bundle['deferred'])}")
    lines.append("")
    for i, a in enumerate(actions, 1):
        tier = f" [{a['apply_tier']}]" if a["apply_tier"] else ""
        lines.append(f"{i}. ({a['safety_class']}{tier}) {a['id']}: {a['command'] or '—'}")
        if a["plain_consequence"]:
            lines.append(f"     {a['plain_consequence']}")
    return "\n".join(lines) + "\n"
