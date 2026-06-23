"""F004 — dontpanic operator brief: the agent-facing render of the F001 triage model.

Reads the canonical triage serialization (operator_triage.build_triage) and emits a
brief an operator-agent reads to derive a run-plan (allow_list = agent_runnable +
auto_safe, with commands) and a precise escalation list (needs_auth + needs_decision),
plus the data_quality envelope and an explicit honesty contract. Command-line only;
this module renders the model, it does not execute anything.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from dontpanic_orchestrate import operator_triage as ot

_ESCALATE = ("needs_auth", "needs_decision")  # the human must act
_ALLOW = ("agent_runnable", "auto_safe")      # an agent may run

HONESTY_CONTRACT = (
    "Narrate uncertain items; never fabricate a clean bucket.",
    "Never run needs_auth or needs_decision items — those are the human's.",
    "Run only allow_list items (agent_runnable / auto_safe).",
    "Report what you ran with its evidence reference and dedupe_key.",
    "If the model is stale (state_revision drift), re-read before acting.",
)

_ITEM_FIELDS = (
    "id", "operator_bucket", "scope", "project_name", "run_state",
    "actor_label", "exact_command", "dedupe_key", "duplicate_count",
    # F001 parity (plan 2026-06-06-004): the agent brief must carry the same
    # render-truth + resolution fields the dashboard reads — an agent needs its
    # options (resolution) and the honest freshness_basis (plan-level vs item-level
    # vs none), not a boolean that overstates item freshness.
    "resolution", "asserted_at", "freshness_basis", "provenance_source",
)


def _brief_item(item: Mapping[str, object]) -> dict:
    return {k: item.get(k) for k in _ITEM_FIELDS}


def build_brief(
    model: Mapping[str, object],
    *,
    worktrees: Mapping[str, object] | None = None,
) -> dict:
    """Render the F001 model into the agent brief. Pure; no I/O.

    ``worktrees`` is the Worktree Isolation v0 status model
    (worktrees.build_status_model()) — the SAME model `plan worktree list`
    and the dashboard render; None means the section is omitted entirely
    (older fixtures), while a model with empty bindings renders an honest
    empty section."""
    items = list(model.get("items", []))
    escalate = [_brief_item(i) for i in items if i.get("operator_bucket") in _ESCALATE]
    allow = [_brief_item(i) for i in items if i.get("operator_bucket") in _ALLOW]
    uncertain = [_brief_item(i) for i in items if i.get("operator_bucket") == "uncertain"]
    quiet = sum(1 for i in items if i.get("operator_bucket") == "quiet")
    dq = model.get("data_quality", {})
    summary = {
        "input_count": dq.get("input_count", dq.get("total", len(items))),
        "total": dq.get("total", len(items)),
        "needs_you": len(escalate),
        "agent_can_run": len(allow),
        "uncertain": len(uncertain),
        "quiet": quiet,
    }
    return {
        "schema": "operator-brief/v0",
        "state_revision": model.get("state_revision"),
        "summary": summary,
        "escalate_list": escalate,
        "allow_list": allow,
        "uncertain": uncertain,
        "data_quality": dq,
        "active_worktrees": dict(worktrees) if worktrees is not None else None,
        "honesty_contract": list(HONESTY_CONTRACT),
    }


def render_text(brief: Mapping[str, object]) -> str:
    """A tight, agent/human-readable digest of the brief."""
    s = brief.get("summary", {})
    lines: list[str] = []
    lines.append(
        f"Operator triage · {s.get('input_count', 0)} raw → {s.get('total', 0)} unique → "
        f"{s.get('needs_you', 0)} need you"
    )
    lines.append(
        f"  {s.get('agent_can_run', 0)} an agent can run · "
        f"{s.get('uncertain', 0)} uncertain · {s.get('quiet', 0)} quiet"
    )
    lines.append("")
    lines.append("NEEDS YOU (human):")
    if brief.get("escalate_list"):
        for i in brief["escalate_list"]:
            scope = f"[{i.get('project_name') or 'global'}]"
            cmd = i.get("exact_command") or ""
            lines.append(f"  • {scope} {i.get('operator_bucket')}: {cmd}")
    else:
        lines.append("  (nothing — all handled)")
    if brief.get("uncertain"):
        lines.append("")
        lines.append(f"UNCERTAIN ({len(brief['uncertain'])} — could not classify; do not fabricate):")
        for i in brief["uncertain"]:
            lines.append(f"  • {i.get('id')}")
    wts = brief.get("active_worktrees")
    if wts is not None:
        lines.append("")
        lines.append("ACTIVE WORKTREES:")
        if wts.get("registry_corrupt"):
            lines.append(
                "  ! registry CORRUPT — bindings below may be incomplete "
                f"({wts.get('registry_path')})"
            )
        rows = wts.get("bindings") or []
        if not rows:
            if not wts.get("registry_corrupt"):
                lines.append("  (none)")
        for w in rows:
            if w.get("healthy"):
                state = f"dirty={w.get('dirty')} untracked={w.get('untracked_count')}"
            else:
                state = (
                    f"UNHEALTHY: {w.get('health_reason')} "
                    "(dirty=unknown untracked=unknown)"
                )
            drift = (
                f" current_branch={w.get('current_branch')}"
                if w.get("current_branch") not in (None, w.get("branch")) else ""
            )
            lines.append(
                f"  • {w.get('plan_id')} branch={w.get('branch')}{drift} {state} "
                f"owner={w.get('owner_actor')}"
            )
    lines.append("")
    lines.append(f"AGENT MAY RUN: {s.get('agent_can_run', 0)} item(s) in allow_list (see --json).")
    lines.append("Honesty contract: " + " ".join(brief.get("honesty_contract", [])))
    return "\n".join(lines)


def _default_fleet_path() -> Path:
    home = os.environ.get("DONTPANIC_HOME") or os.path.expanduser("~/.dontpanic")
    return Path(home) / "dashboard" / "fleet-what-now.json"


def load_fleet_items(path: str | os.PathLike[str] | None = None) -> list[dict]:
    p = Path(path) if path else _default_fleet_path()
    data = json.loads(Path(p).read_text())
    return list(data.get("items", []))


def _live_supervisors() -> list[dict]:
    """Live SupervisorEntry rows (alive pids), best-effort and read-only.

    Delegates to ``active_supervisors.live_supervisor_rows()`` so there is one
    source of truth for the operator-triage run_state join — the CLI brief and
    the dashboard build sites read identically shaped rows.
    """
    try:
        from dontpanic_orchestrate import active_supervisors as asup

        return asup.live_supervisor_rows()
    except Exception:
        return []


def _live_worktrees() -> dict | None:
    """The Worktree Isolation v0 status model, best-effort and read-only —
    a corrupt registry is RENDERED by the model (registry_corrupt), never
    swallowed; only an unexpected probe crash degrades to None."""
    try:
        from dontpanic_orchestrate import worktrees as _wt

        return _wt.build_status_model()
    except Exception:
        return None


def build_operator_brief(
    *,
    items: Sequence[Mapping[str, object]] | None = None,
    fixture: str | os.PathLike[str] | None = None,
    dedupe: bool = True,
    live_supervisors: Sequence[Mapping[str, object]] | None = None,
    worktrees: Mapping[str, object] | None = None,
) -> dict:
    """Compose load -> triage -> brief. ``items``/``fixture`` for tests; default reads
    the operator-home fleet state and the live supervisor registry."""
    if items is None:
        items = load_fleet_items(fixture)
    if live_supervisors is None:
        live_supervisors = _live_supervisors()
    if worktrees is None:
        worktrees = _live_worktrees()
    model = ot.build_triage(
        items, safety_class_for=lambda _it: None, live_supervisors=live_supervisors, dedupe=dedupe
    )
    return build_brief(model, worktrees=worktrees)


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dontpanic operator", add_help=True)
    sub = parser.add_subparsers(dest="cmd")
    brief = sub.add_parser("brief", help="render the operator triage brief")
    fmt = brief.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="emit JSON (agent-readable)")
    fmt.add_argument("--text", action="store_true", help="emit a text digest (default)")
    brief.add_argument("--fixture", default=None, help="read items from this file instead of the home fleet state")
    brief.add_argument("--no-dedupe", action="store_true", help="do not collapse duplicates")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.cmd != "brief":
        parser.print_help()
        return 2
    out = build_operator_brief(fixture=args.fixture, dedupe=not args.no_dedupe)
    if args.json:
        print(json.dumps(out, indent=1))
    else:
        print(render_text(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
