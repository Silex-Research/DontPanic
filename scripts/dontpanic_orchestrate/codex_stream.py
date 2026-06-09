"""Shared Codex CLI response parsing (plan 2026-06-08-006).

The Codex CLI emits its turn as line-delimited JSON events; the useful payload
is the ``item.text`` of the ``item.completed`` event whose ``item.type ==
'agent_message'``. The post-impl completion-audit path (F2C-D008) already had a
robust extractor for this, but it lived privately in ``completion_dispatch`` —
which *imports* ``sufficiency_auditor``, so the pre-impl sufficiency path could
not reuse it without a circular import. This module is the shared home so BOTH
audit boundaries parse Codex output identically.

It also adds :func:`coerce_first_json_value`, which tolerates the "Extra data"
shape (a valid JSON value followed by trailing prose) that strict
``json.loads`` rejects — the exact failure that discarded a paid Codex
sufficiency response during the 2026-06-08 dogfood.
"""

from __future__ import annotations

import json
from typing import Any

_RECOGNIZED_CODEX_STREAM_TYPES: frozenset[str] = frozenset(
    {
        "thread.started",
        "turn.started",
        "turn.completed",
        "item.started",
        "item.completed",
    }
)
"""Positive shape gate (D008(a)). :func:`extract_codex_streaming_payload`
returns ``None`` unless at least one parsed line carries a ``type`` in this set,
so arbitrary line-delimited JSON is not misread as a Codex stream."""


def extract_codex_streaming_payload(response: str) -> str | None:
    """Conservative Codex JSONL streaming-output extractor (moved verbatim from
    ``completion_dispatch._extract_codex_streaming_payload``).

    Returns the last ``agent_message`` text when ``response`` is recognizably a
    Codex event stream; ``None`` otherwise (caller falls through to raw-JSON).
    Per-line tolerant: a single malformed line never aborts the scan.
    """
    if not response:
        return None

    saw_recognized_shape = False
    agent_message_texts: list[str] = []

    for line in response.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type not in _RECOGNIZED_CODEX_STREAM_TYPES:
            continue
        saw_recognized_shape = True
        if event_type != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "agent_message":
            continue
        text = item.get("text", "")
        if not isinstance(text, str) or not text.strip():
            continue
        agent_message_texts.append(text)

    if not saw_recognized_shape:
        return None
    if not agent_message_texts:
        return None
    return agent_message_texts[-1]


def strip_code_fence(text: str) -> str:
    """Tolerate ``` fenced output. The prompt asks for raw JSON; agents fence anyway."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            inner = stripped[first_newline + 1 :]
            if inner.endswith("```"):
                inner = inner[: -len("```")]
            return inner.strip()
    return stripped


def coerce_first_json_value(text: str) -> Any:
    """Parse the first complete JSON value out of ``text``, tolerating trailing
    content (the "Extra data" shape) that strict ``json.loads`` rejects.

    Strategy: try a clean parse first; on failure, scan for the first ``[`` or
    ``{`` and use ``raw_decode`` (which reads exactly one value and ignores the
    rest). Raises ``json.JSONDecodeError`` only if no JSON value can be found at
    all — callers translate that into their domain error.
    """
    cleaned = strip_code_fence(text).lstrip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Tolerate ONLY trailing content after a complete leading JSON value
        # (the "Extra data" shape). raw_decode reads the value at the START of
        # the string and ignores what follows. We deliberately do NOT scan
        # forward for the first '['/'{' (audit 2026-06-08): a response like
        # "I could not complete the audit.\n[]" must NOT be silently accepted as
        # an empty findings list — leading prose means the model did not produce
        # findings, and accepting it could let a gated plan lock on a non-answer.
        value, _end = json.JSONDecoder().raw_decode(cleaned)
        return value
