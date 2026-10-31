"""Probe: render DontPanic job lines OLD vs NEW from synthetic records.

The records below are synthetic. They copy the shape of real
``invocations.jsonl`` and ``dashboard/event-actions.jsonl`` entries (fields,
old wording, outcome mix) but every plan name, path and agent is made up.
The probe reads no local files, so its output is safe to publish.

Records the templates cannot map (a call that is not a job, an unknown
event kind or an unknown volley outcome) keep their old text and are
flagged instead of being given a guessed status.

Run: ``PYTHONPATH=scripts python -m dontpanic_orchestrate.readable_text_probe``
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from dontpanic_orchestrate import readable_text as rt

UNMAPPED = "(unmapped; old text kept)"

_GATE_RE = re.compile(r"gates? `([^`]+)`")
_BREAKER_RE = re.compile(r"breaker `([^`]+)`")
_FINAL_RE = re.compile(r"with (?:status )?`([a-z_]+)`")

_P = "/path/to/example-project/docs/plans/"
A, B, C, D = (f"example-plan-{x}" for x in "abcd")


def _inv(command: str, result: str, plan: str | None = None) -> dict[str, Any]:
    return {"command": command, "result": result, "plan": plan}


SYNTHETIC_INVOCATIONS: tuple[dict[str, Any], ...] = (
    _inv("plan lock --help", "ok"),
    _inv(f"plan lock {_P}{A}", "ok", A),
    _inv("approve --help", "error"),
    _inv("dispatch-from-plan --help", "ok"),
    _inv(f"approve {A} pre_impl", "error", A),
    _inv(f"dispatch-from-plan {_P}{A} --feature F001 --max-iterations 2", "ok", A),
    _inv(f"dispatch-from-plan {_P}{A} --feature F001 --max-iterations 2 --confirm", "error", A),
    _inv(f"approve {A} on_escalation", "ok", A),
    _inv(f"dispatch-from-plan {_P}{A} --feature F001 --max-iterations 2 --confirm", "interrupted", A),
    _inv("projects add /path/to/example-project", "error"),
    _inv("projects list", "ok"),
    _inv("projects add example-project /path/to/example-project --no-hooks --dry-run", "ok"),
    _inv(f"plan lock {_P}{B}", "error", B),
    _inv(f"plan lock {_P}{B}", "ok", B),
    _inv(f"dispatch-from-plan {_P}{B} --feature F001 --max-iterations 3 --confirm", "ok", B),
    _inv(f"resume {B} --all", "ok", B),
    _inv(f"approve {C} pre_merge", "ok", C),
    _inv(f"dispatch-from-plan {_P}{C} --feature F002 --max-iterations 2 --confirm", "error", C),
    _inv(f"dispatch-from-plan {_P}{D} --feature F001 --max-iterations 1 --confirm", "", D),
    _inv("projects list", "ok"),
)


def _ev(band: str, kind: str, plan: str, title: str, detail: str) -> dict[str, Any]:
    return {"band": band, "title": title, "detail": detail, "dedupe_key": f"supervisor:{kind}:{plan}:F001"}


def _start(plan: str, cap: int) -> dict[str, Any]:
    return _ev("info", "volley_start", plan, f"Active AI work on {plan}", f"Volley begins (cap {cap}).")


def _gate(plan: str, gate: str) -> dict[str, Any]:
    return _ev(
        "needs_action", "gate_hit", plan, f"Approval needed on {plan}",
        f"Supervisor paused at gate `{gate}`. Operator must approve before dispatch continues.",
    )


def _breaker(plan: str, kind: str) -> dict[str, Any]:
    return _ev(
        "needs_action", "breaker_tripped", plan, f"Blocked work on {plan} — breaker `{kind}` tripped",
        f"Circuit breaker `{kind}` tripped. Operator clearance required before dispatch continues.",
    )


def _terminal(plan: str, final: str, rounds: int) -> dict[str, Any]:
    if final == "signed_off":
        return _ev(
            "ready", "volley_terminal", plan, f"AI work finished on {plan}",
            f"Volley completed after {rounds} round(s) with `signed_off`. No action needed.",
        )
    return _ev(
        "needs_action", "volley_terminal", plan, f"Blocked work on {plan} — {final.replace('_', ' ')}",
        f"Volley terminated after {rounds} round(s) with status `{final}`. "
        "Review the audit envelope before deciding next step.",
    )


SYNTHETIC_EVENTS: tuple[dict[str, Any], ...] = (
    _start(A, 2),
    _gate(A, "pre_impl"),
    _start(A, 2),
    _terminal(A, "stopped_cap", 3),
    _breaker(A, "iteration_cap"),
    _start(B, 3),
    _terminal(B, "signed_off", 2),
    _gate(B, "pre_merge"),
    _terminal(B, "merged", 2),
    _start(C, 1),
    _terminal(C, "blocked", 1),
    _gate(C, "pre_impl"),
    _start(C, 2),
    _terminal(C, "stopped_no_progress", 2),
    _ev("needs_action", "verdict_mismatch", C, f"Verdict mismatch on {C}",
        "Auditor verdict and findings disagree. Review before dispatch continues."),
    _start(D, 2),
    _terminal(D, "stopped_budget", 1),
    _breaker(D, "global"),
    _terminal(D, "stopped_some_new_reason", 2),
    _terminal(D, "signed_off", 1),
)


def invocation_old_new(rec: Mapping[str, Any]) -> tuple[str, str | None]:
    command = str(rec.get("command") or "")
    result = str(rec.get("result") or "")
    plan = rec.get("plan")
    old = f"{command} → {result or '(no result)'}"
    return old, rt.invocation_status(result, command, str(plan) if plan else None)


def _terminal_reason(status: str, final: str) -> str:
    if status == rt.STOPPED:
        return "volley stops: " + final.removeprefix("stopped_").replace("_", " ")
    return {
        rt.PASSED: "audit signs off",
        rt.MERGED: "pull request merges into main",
        rt.FAILED: "volley fails",
        rt.BLOCKED: "audit blocks"
        + (": " + final.removeprefix("blocked_").replace("_", " ") if final != "blocked" else ""),
    }[status]


def event_old_new(rec: Mapping[str, Any]) -> tuple[str, str | None]:
    """OLD text and NEW status line for one event action (``None`` = unmapped)."""
    title = str(rec.get("title") or "")
    detail = str(rec.get("detail") or "")
    old = f"[{rec.get('band') or ''}] {title}. {detail}"
    parts = str(rec.get("dedupe_key") or "").split(":")
    kind = parts[1] if len(parts) > 1 else ""
    plan = parts[2] if len(parts) > 2 else ""
    if not plan:
        return old, None
    if kind == "volley_start":
        return old, rt.rollup_item(rt.RUNNING, plan, "volley starting")
    if kind == "gate_hit":
        m = _GATE_RE.search(detail)
        return old, rt.rollup_item(rt.BLOCKED, plan, "approval needed", gate=m.group(1) if m else None)
    if kind == "breaker_tripped":
        m = _BREAKER_RE.search(detail) or _BREAKER_RE.search(title)
        name = m.group(1) if m else "unknown"
        return old, rt.rollup_item(rt.BLOCKED, plan, f"breaker {name} blocks dispatch")
    if kind == "volley_terminal":
        m = _FINAL_RE.search(detail)
        final = m.group(1) if m else ""
        status = rt.terminal_status(final)
        if status is None:
            return old, None
        return old, rt.rollup_item(status, plan, _terminal_reason(status, final))
    return old, None


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _table(rows: Sequence[tuple[str, str | None]]) -> str:
    lines = ["| # | Old | New |", "|---|-----|-----|"]
    for i, (old, new) in enumerate(rows, start=1):
        lines.append(f"| {i} | {_cell(old)} | {_cell(new) if new else UNMAPPED} |")
    return "\n".join(lines)


def render(
    invocations: Sequence[Mapping[str, Any]] = SYNTHETIC_INVOCATIONS,
    events: Sequence[Mapping[str, Any]] = SYNTHETIC_EVENTS,
) -> str:
    inv = [invocation_old_new(r) for r in invocations]
    ev = [event_old_new(r) for r in events]
    out = [
        "# Readable text probe",
        "",
        "**Can you find the blocked job faster?** Old wording against new wording. "
        "Scan the left column for the blocked job, then the right.",
        "",
        f"**These records are synthetic.** The {len(inv)} command records and "
        f"{len(ev)} dashboard event actions copy the shape, wording and outcome mix "
        "of real DontPanic records, but every plan name, path and project is made "
        "up and agent assignments are left out. Regenerate with "
        "`PYTHONPATH=scripts python -m dontpanic_orchestrate.readable_text_probe`.",
        "",
        f"Rows marked {UNMAPPED} are records the templates do not cover: calls that "
        "are not jobs (help, project listing), unknown event kinds and unknown "
        "volley outcomes. They keep their old text rather than a guessed status.",
        "",
        "## Commands and results",
        "",
        _table(inv),
        "",
        "## Dashboard event actions",
        "",
        _table(ev),
        "",
        "## What changed",
        "",
        "- The status word leads every line (Running, Passed, Failed, Blocked, "
        "Stopped, Merged), and its tense says whether the job is still going.",
        "- Volley outcomes map one to one: signed off is Passed, merged is Merged, "
        "stopped_* is Stopped, blocked is Blocked. Unknown outcomes are not mapped.",
        "- One vocabulary: a unit of work is a job and a pass/fail control is a "
        "gate; the gate name sits in a fixed trailing field.",
        "- Failures say fails / blocks / stops, and every line has the same shape: "
        "`Status: job name — reason (fields)`.",
        "- The dashboard event rows show the proposed wording only. The live "
        "dashboard titles are pinned by snapshot fixtures and stay unchanged "
        "until you decide to change that contract.",
        "",
    ]
    return "\n".join(out)


def main() -> None:
    print(render())


if __name__ == "__main__":
    main()
