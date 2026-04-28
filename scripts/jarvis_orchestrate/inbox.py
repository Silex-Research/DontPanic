"""F008 Item 1 — INBOX.md format + writer.

Per-plan operator-facing log. Append-only. Each entry is a markdown block
delimited by a `---` separator with a YAML-like header (parseable) followed
by a free-form body. Format chosen so:

  - operator can read it as a regular markdown file in any editor
  - parser can round-trip headers without depending on the body shape
  - new event types can be added without breaking older entries

Format:

    ---
    timestamp: 2026-04-26T12:34:56Z
    event: gate_hit
    plan_id: 2026-04-26-006-infra-...
    gate: pre_impl
    severity: action_required
    ---

    Free-form body. Possibly multi-paragraph. Operator may edit / append
    notes here, but the parser only reads the header block above the
    separator and ignores body modifications.

Reserved event types (not enforced — extra types are passed through):
  - volley_start
  - volley_terminal
  - gate_hit
  - gate_cleared
  - resumed
  - quota_warn
  - error
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INBOX_FILENAME = "INBOX.md"

_HEADER_OPEN = "---"
_HEADER_CLOSE = "---"
_BODY_TERMINATOR = "==="  # Separates one entry's body from the next entry.

# Header lines: `key: value`. Values are stored as strings; the parser does
# not coerce types — callers can interpret as needed.
_HEADER_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")


@dataclass(frozen=True)
class InboxEntry:
    timestamp: str
    event: str
    plan_id: str
    headers: dict[str, str]
    body: str


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def inbox_path(plan_dir: Path) -> Path:
    return plan_dir / INBOX_FILENAME


def append_event(
    plan_dir: Path,
    event: str,
    *,
    plan_id: str,
    body: str = "",
    timestamp: str | None = None,
    **extra_headers: Any,
) -> InboxEntry:
    """Append an entry to <plan_dir>/INBOX.md and return the structured form.

    extra_headers are flattened into the YAML-like header block. Values are
    stringified via str() — pass primitives or pre-serialized strings.
    """
    ts = timestamp or _now_iso()
    headers: dict[str, str] = {
        "timestamp": ts,
        "event": event,
        "plan_id": plan_id,
    }
    for k, v in extra_headers.items():
        if v is None:
            continue
        headers[k] = str(v)

    block = [_HEADER_OPEN]
    for k, v in headers.items():
        block.append(f"{k}: {v}")
    block.append(_HEADER_CLOSE)
    block.append("")
    if body:
        block.append(body.rstrip())
        block.append("")
    block.append(_BODY_TERMINATOR)
    block.append("")  # trailing newline
    chunk = "\n".join(block)

    path = inbox_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(
            f"# INBOX — {plan_id}\n\nOperator-facing event log written by the supervisor.\n\n"
        )
    with path.open("a") as f:
        f.write(chunk)

    return InboxEntry(
        timestamp=ts,
        event=event,
        plan_id=plan_id,
        headers=headers,
        body=body.rstrip(),
    )


def read_events(plan_dir: Path) -> list[InboxEntry]:
    """Parse INBOX.md and return all entries in append order. Tolerant of
    operator-added body content and missing trailing terminators."""
    path = inbox_path(plan_dir)
    if not path.is_file():
        return []
    raw = path.read_text()
    entries: list[InboxEntry] = []
    cursor = 0
    while True:
        # Find the next header opener.
        open_idx = raw.find(f"\n{_HEADER_OPEN}\n", cursor)
        if open_idx == -1:
            # Allow file-start header (no leading newline).
            if cursor == 0 and raw.startswith(f"{_HEADER_OPEN}\n"):
                open_idx = -1  # treat as starting at 0 below
            else:
                break
        header_start = (open_idx + 1) if open_idx >= 0 else 0
        # Find the matching close: next line that is exactly "---" after header_start.
        close_idx = raw.find(f"\n{_HEADER_CLOSE}\n", header_start + len(_HEADER_OPEN))
        if close_idx == -1:
            break
        header_block = raw[header_start + len(_HEADER_OPEN) + 1 : close_idx].strip()
        body_start = close_idx + len(_HEADER_CLOSE) + 2
        # Body runs until the next BODY_TERMINATOR line, or file end.
        term_idx = raw.find(f"\n{_BODY_TERMINATOR}\n", body_start)
        if term_idx == -1:
            term_idx = raw.find(f"\n{_BODY_TERMINATOR}", body_start)
        body_end = term_idx if term_idx != -1 else len(raw)
        body = raw[body_start:body_end].strip("\n")

        headers: dict[str, str] = {}
        for line in header_block.splitlines():
            m = _HEADER_LINE_RE.match(line.strip())
            if m:
                headers[m.group(1)] = m.group(2).strip()

        if "event" in headers and "plan_id" in headers and "timestamp" in headers:
            entries.append(
                InboxEntry(
                    timestamp=headers["timestamp"],
                    event=headers["event"],
                    plan_id=headers["plan_id"],
                    headers=headers,
                    body=body,
                )
            )

        cursor = (term_idx + len(_BODY_TERMINATOR) + 1) if term_idx != -1 else len(raw)
        if cursor >= len(raw):
            break

    return entries


def latest_event(plan_dir: Path, event: str) -> InboxEntry | None:
    """Return the most recent entry with matching event type, or None."""
    for e in reversed(read_events(plan_dir)):
        if e.event == event:
            return e
    return None


__all__ = [
    "INBOX_FILENAME",
    "InboxEntry",
    "append_event",
    "inbox_path",
    "latest_event",
    "read_events",
]
