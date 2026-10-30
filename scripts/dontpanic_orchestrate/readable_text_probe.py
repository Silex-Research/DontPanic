"""Read-only probe: render the last real DontPanic job lines OLD vs NEW.

Reads ``invocations.jsonl`` and ``dashboard/event-actions.jsonl`` under the
DontPanic home (never writes them), takes the last ``LIMIT`` records of each,
and prints a markdown comparison. Every cell is passed through
:func:`readable_text.redact` before it is emitted.

Run: ``PYTHONPATH=scripts python -m dontpanic_orchestrate.readable_text_probe``
"""

from __future__ import annotations

import getpass
import json
import re
import socket
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import readable_text as rt

LIMIT = 20
_HOME = Path.home() / ".dontpanic"

#: inbox event kind -> (status, reason) for the NEW rendering.
_EVENT_STATUS: dict[str, tuple[str, str]] = {
    "gate_hit": (rt.BLOCKED, "approval needed"),
    "volley_start": (rt.RUNNING, "volley starting"),
    "volley_terminal": (rt.BLOCKED, "volley stopped"),
    "breaker_tripped": (rt.BLOCKED, "breaker tripped"),
}
_GATE_RE = re.compile(r"gates? `([^`]+)`")
_TAIL_RE = re.compile(r" — (.+)$")


def tail_jsonl(path: Path, limit: int = LIMIT) -> list[dict[str, Any]]:
    """Last ``limit`` JSON objects of a JSONL file (read-only; bad lines skipped)."""
    if not path.is_file():
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=limit)
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return list(rows)


def _scrub(text: str) -> str:
    text = rt.redact(text)
    for word in {getpass.getuser(), socket.gethostname().split(".")[0]}:
        if len(word) >= 3:
            text = re.sub(re.escape(word), "[redacted-name]", text, flags=re.I)
    return text.replace("|", "\\|").replace("\n", " ")


def invocation_old_new(rec: Mapping[str, Any]) -> tuple[str, str]:
    command = str(rec.get("command") or "")
    result = str(rec.get("result") or "")
    plan = rec.get("plan")
    old = f"{command} → {result}"
    new = rt.invocation_status(result, command, str(plan) if plan else None)
    return old, new


def event_old_new(rec: Mapping[str, Any]) -> tuple[str, str]:
    title = str(rec.get("title") or "")
    band = str(rec.get("band") or "")
    detail = str(rec.get("detail") or "").split(" Reference:")[0]
    old = f"[{band}] {title}. {detail}"
    parts = str(rec.get("dedupe_key") or "").split(":")
    kind = parts[1] if len(parts) > 1 else ""
    plan = parts[2] if len(parts) > 2 else title
    status, reason = _EVENT_STATUS.get(kind, (rt.BLOCKED, "needs attention"))
    tail = _TAIL_RE.search(title)
    if kind in ("volley_terminal", "breaker_tripped") and tail:
        reason = tail.group(1)
    gate = None
    if kind == "gate_hit":
        m = _GATE_RE.search(str(rec.get("detail") or ""))
        gate = m.group(1) if m else None
    return old, rt.rollup_item(status, plan, reason, gate=gate)


def _table(rows: Sequence[tuple[str, str]]) -> str:
    lines = ["| # | Old | New |", "|---|-----|-----|"]
    for i, (old, new) in enumerate(rows, start=1):
        lines.append(f"| {i} | {_scrub(old)} | {_scrub(new)} |")
    return "\n".join(lines)


def render(home: Path = _HOME, limit: int = LIMIT) -> str:
    inv = [invocation_old_new(r) for r in tail_jsonl(home / "invocations.jsonl", limit)]
    ev = [
        event_old_new(r)
        for r in tail_jsonl(home / "dashboard" / "event-actions.jsonl", limit)
    ]
    out = [
        "# Readable text probe",
        "",
        "**Can you find the blocked job faster?** The same real entries, old wording "
        "against new wording. Scan the left column for the blocked job, then the right.",
        "",
        f"Entries: {len(inv)} command records and {len(ev)} dashboard event actions "
        f"(the last {limit} of each; fewer means fewer exist). Paths, ids and "
        "tokens are redacted.",
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
        "Stopped), and its tense says whether the job is still going.",
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
