"""F007 Slice 2 — manual touch state for the interactive-backoff admission gate.

Operator runs `jarvis-orchestrate claude-touch` (or any future `interactive-touch
<agent>`) to record that they just made a human Claude request. The supervisor
reads this file pre-dispatch; if the volley is `class == autonomous` AND Claude
is in agents_required AND the touch is within JARVIS_INTERACTIVE_BACKOFF_MINUTES
(default 30), it pauses via the synthetic `defer:interactive_backoff` gate.

State path: ~/.jarvis/interactive_state.json
Test isolation: set JARVIS_INTERACTIVE_STATE_PATH to a tempfile (the conftest
autouse fixture does this for every test, mirroring F006's
JARVIS_BREAKER_HISTORY_PATH and EC13's JARVIS_ACTIVE_SUPERVISORS_PATH).

File shape:
  {
    "claude": {"last_human_request_at": "2026-04-26T19:30:00Z"}
  }

Future agents (gemini, etc.) get their own keys; only `claude` is wired in
this slice because it's the load-bearing case for the autonomous-vs-human
quota collision.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

_DEFAULT_STATE_PATH = Path.home() / ".jarvis" / "interactive_state.json"
STATE_PATH = _DEFAULT_STATE_PATH
DEFAULT_BACKOFF_MINUTES = 30.0


def _effective_state_path() -> Path:
    env_override = os.environ.get("JARVIS_INTERACTIVE_STATE_PATH")
    if env_override:
        return Path(env_override)
    return STATE_PATH


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_state() -> dict:
    p = _effective_state_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict) -> None:
    p = _effective_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def touch(agent: str, *, at: dt.datetime | None = None) -> str:
    """Record a human request for `agent`. Returns the ISO timestamp written."""
    ts = _iso(at if at is not None else _now())
    state = _read_state()
    bucket = state.get(agent) or {}
    if not isinstance(bucket, dict):
        bucket = {}
    bucket["last_human_request_at"] = ts
    state[agent] = bucket
    _write_state(state)
    return ts


def last_human_request_at(agent: str) -> dt.datetime | None:
    """Return the last human-request timestamp for `agent`, or None when no
    touch has ever been recorded (or the value is missing/malformed)."""
    state = _read_state()
    bucket = state.get(agent) or {}
    if not isinstance(bucket, dict):
        return None
    raw = bucket.get("last_human_request_at")
    if not isinstance(raw, str):
        return None
    try:
        # Accept both "Z" and "+00:00" suffix forms.
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def backoff_minutes() -> float:
    """Effective backoff window. Honors JARVIS_INTERACTIVE_BACKOFF_MINUTES so
    tests can shrink it without monkey-patching."""
    raw = os.environ.get("JARVIS_INTERACTIVE_BACKOFF_MINUTES")
    if raw is None:
        return DEFAULT_BACKOFF_MINUTES
    try:
        v = float(raw)
        return v if v > 0 else DEFAULT_BACKOFF_MINUTES
    except ValueError:
        return DEFAULT_BACKOFF_MINUTES


def is_within_backoff(agent: str, *, now: dt.datetime | None = None) -> tuple[bool, float | None]:
    """Returns (within_backoff, minutes_remaining_or_None).

    minutes_remaining is None when no touch is recorded, else how many minutes
    of the backoff window are left (clamped to >=0).
    """
    last = last_human_request_at(agent)
    if last is None:
        return False, None
    elapsed_min = ((now if now is not None else _now()) - last).total_seconds() / 60.0
    window = backoff_minutes()
    remaining = window - elapsed_min
    return remaining > 0, max(0.0, remaining)


__all__ = [
    "DEFAULT_BACKOFF_MINUTES",
    "STATE_PATH",
    "backoff_minutes",
    "is_within_backoff",
    "last_human_request_at",
    "touch",
]
