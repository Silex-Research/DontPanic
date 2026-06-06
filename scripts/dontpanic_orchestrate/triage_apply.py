"""F005 — safe-tier apply engine: dontpanic triage apply --safe.

A command the human or an agent runs in a terminal. It applies ONLY the auto_safe
bucket (reversible derived-state DontPanic may apply). Dry-run is the default; with
--confirm it runs each command via an injected runner and writes a reversible evidence
record. It HARD-REFUSES anything that is not auto_safe (credentials, approvals,
agent_runnable, project mutations). Off by default; no browser/console invocation
(that boundary is plan 2026-06-06-002).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess  # noqa: S404 — used with shell=False + shlex.split only
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from dontpanic_orchestrate import operator_brief as ob
from dontpanic_orchestrate import operator_triage as ot

_AUTO_SAFE = ot.OperatorBucket.AUTO_SAFE.value

# A command runner: maps a command string to a result dict (rc/stdout/stderr).
Runner = Callable[[str], Mapping[str, object]]


class NotSafeToApply(Exception):
    """Raised when an item that is not auto_safe is offered to the apply engine."""


def assert_safe_appliable(item: Mapping[str, object]) -> None:
    bucket = item.get("operator_bucket")
    if bucket != _AUTO_SAFE:
        raise NotSafeToApply(
            f"item {item.get('id')!r} is {bucket!r}, not auto_safe — refused "
            f"(credentials/approvals/agent-runnable/mutations are never applied by this engine)"
        )


def _why_safe(item: Mapping[str, object]) -> str:
    return "classified auto_safe: reversible derived-state DontPanic may apply"


def build_apply_plan(model: Mapping[str, object]) -> dict:
    """The dry-run plan: only auto_safe items, with their command + why-safe."""
    items = list(model.get("items", []))
    safe = [i for i in items if i.get("operator_bucket") == _AUTO_SAFE]
    refused = sum(1 for i in items if i.get("operator_bucket") in ("needs_auth", "needs_decision", "agent_runnable"))
    plan_items = [
        {
            "id": i.get("id"),
            "command": i.get("exact_command"),
            "why_safe": _why_safe(i),
            "scope": i.get("scope"),
            "run_state": i.get("run_state"),
            "dedupe_key": i.get("dedupe_key"),
        }
        for i in safe
    ]
    return {"scope": "fleet", "count": len(plan_items), "items": plan_items, "refused": refused}


def _subprocess_runner(command: str) -> dict:
    """Default runner: shell=False via shlex.split, captured, bounded. Never shell=True."""
    args = shlex.split(command)
    proc = subprocess.run(  # noqa: S603 — shell=False, args from a model-provided command
        args, capture_output=True, text=True, timeout=600, check=False
    )
    return {"rc": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def _default_evidence_path() -> Path:
    home = os.environ.get("DONTPANIC_HOME") or os.path.expanduser("~/.dontpanic")
    return Path(home) / "dashboard" / "safe-apply-evidence.jsonl"


def apply_safe(
    model: Mapping[str, object],
    *,
    confirm: bool = False,
    runner: Runner | None = None,
    evidence_path: str | os.PathLike[str] | None = None,
    now: str = "",
) -> dict:
    """Dry-run (default) or, with confirm=True, apply each auto_safe item via runner,
    writing a reversible evidence record. Refused count reports what it will NOT touch."""
    plan = build_apply_plan(model)
    base = {"plan": plan, "refused": plan["refused"], "applied": []}
    if not confirm:
        return {
            **base,
            "mode": "dry_run",
            "message": (
                f"Would apply {plan['count']} auto_safe item(s); leaves {plan['refused']} "
                f"for a human / agent. Re-run with --confirm to apply. The confirmed tier "
                f"is never run without --confirm."
            ),
        }
    runner = runner or _subprocess_runner
    ev_path = Path(evidence_path) if evidence_path else _default_evidence_path()
    safe_items = [i for i in model.get("items", []) if i.get("operator_bucket") == _AUTO_SAFE]
    applied: list[dict] = []
    for item in safe_items:
        assert_safe_appliable(item)
        command = item.get("exact_command") or ""
        result = runner(command)
        record = {
            "item_id": item.get("id"),
            "command": command,
            "why_safe": _why_safe(item),
            "ran_at": now,
            "rc": result.get("rc"),
            "change_summary": str(result.get("stdout") or "")[-500:],
            "reversible": True,  # derived-state apply is re-runnable/idempotent
            "confirmed_by": "operator --confirm",
        }
        applied.append(record)
    _write_evidence(ev_path, applied)
    return {**base, "applied": applied, "mode": "applied", "evidence_path": str(ev_path)}


def _write_evidence(path: Path, records: Sequence[Mapping[str, object]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _render_apply_text(out: Mapping[str, object]) -> str:
    plan = out["plan"]
    lines = [
        f"triage apply --safe ({out['mode']}) · {plan['count']} auto_safe · "
        f"{out['refused']} left for a human/agent",
    ]
    for i in plan["items"]:
        lines.append(f"  • {i['command']}  ({i['why_safe']})")
    if out["mode"] == "dry_run":
        lines.append("")
        lines.append(str(out.get("message", "")))
    else:
        lines.append("")
        lines.append(f"Applied {len(out['applied'])} · evidence: {out.get('evidence_path')}")
    return "\n".join(lines)


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dontpanic triage", add_help=True)
    sub = parser.add_subparsers(dest="cmd")
    apply = sub.add_parser("apply", help="apply the safe (auto_safe) tier")
    apply.add_argument("--safe", action="store_true", help="REQUIRED — apply only the auto_safe tier")
    apply.add_argument("--confirm", action="store_true", help="actually run (default is dry-run)")
    apply.add_argument("--fixture", default=None, help="read items from this file instead of the home fleet state")
    apply.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.cmd != "apply":
        parser.print_help()
        return 2
    if not args.safe:
        print("triage apply requires --safe (no blanket apply). Try: dontpanic triage apply --safe", flush=True)
        return 2
    items = ob.load_fleet_items(args.fixture)
    model = ot.build_triage(items, safety_class_for=lambda _it: None, live_supervisors=[], dedupe=True)
    out = apply_safe(model, confirm=args.confirm)
    if args.json:
        print(json.dumps(out, indent=1))
    else:
        print(_render_apply_text(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
