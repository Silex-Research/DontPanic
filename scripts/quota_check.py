#!/usr/bin/env python3
"""F020 — per-model weekly token consumption tracker.

Writes ~/.jarvis/quota_state.json. Supervisor reads before every dispatch
to enforce per-tier quota caps + interactive backoff (parent plan F007).

Caps below are configurable estimates — refine as we get real Max plan reset signals.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

# Weekly caps (estimates — Task #698 will refine via real reset cadence).
CAPS: dict[str, dict[str, Any]] = {
    "claude": {"limit": 1_000_000_000, "unit": "tokens", "plan": "Max ~1B/wk estimate"},
    "codex": {"limit": 300, "unit": "calls", "plan": "300/week ChatGPT Plus"},
    "gemini": {"limit": 1_500, "unit": "calls", "plan": "AI Studio free tier daily; weekly approx"},
    "grok": {"limit": 50, "unit": "calls", "plan": "self-imposed soft cap"},
    "ollama": {"limit": None, "unit": None, "plan": "unmetered (local)"},
}

WEEK_START = dt.datetime.now(dt.timezone.utc) - dt.timedelta(
    days=dt.datetime.now(dt.timezone.utc).weekday()
)
WEEK_START = WEEK_START.replace(hour=0, minute=0, second=0, microsecond=0)


def _claude_tokens_this_week() -> int:
    """Sum input+output tokens from Claude Code session jsonl files since Monday 00:00 UTC."""
    sessions_dir = Path.home() / ".claude" / "projects"
    if not sessions_dir.is_dir():
        return 0

    total = 0
    week_ts = WEEK_START.timestamp()
    for session_file in sessions_dir.rglob("*.jsonl"):
        try:
            if session_file.stat().st_mtime < week_ts:
                continue
            for line in session_file.read_text(errors="ignore").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                usage = entry.get("message", {}).get("usage") or entry.get("usage") or {}
                total += int(usage.get("input_tokens") or 0)
                total += int(usage.get("output_tokens") or 0)
                total += int(usage.get("cache_read_input_tokens") or 0)
                total += int(usage.get("cache_creation_input_tokens") or 0)
        except OSError:
            continue
    return total


def _codex_calls_this_week() -> int:
    """Best-effort: count entries in ~/.codex/history.jsonl since week start."""
    history = Path.home() / ".codex" / "history.jsonl"
    if not history.is_file():
        return 0
    week_ts = WEEK_START.timestamp()
    count = 0
    if history.stat().st_mtime < week_ts:
        return 0
    for line in history.read_text(errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = entry.get("timestamp") or entry.get("ts")
        if ts and isinstance(ts, (int, float)) and ts >= week_ts:
            count += 1
        else:
            count += 1
    return count


def _gemini_calls_this_week() -> int:
    state = Path.home() / ".config" / "gemini" / "state.json"
    alt = Path.home() / "Documents" / "GitHub" / "Jarvis" / "gemini" / "state.json"
    for p in (state, alt):
        if p.is_file():
            try:
                data = json.loads(p.read_text())
                return int(data.get("weekly_calls") or 0)
            except (json.JSONDecodeError, OSError):
                continue
    return 0


def _grok_calls_this_week() -> int:
    counter = Path.home() / ".jarvis" / "grok_calls.json"
    if not counter.is_file():
        return 0
    try:
        data = json.loads(counter.read_text())
    except (json.JSONDecodeError, OSError):
        return 0
    iso = data.get("week_start")
    if iso != WEEK_START.isoformat():
        return 0
    return int(data.get("calls") or 0)


def _ollama_models_loaded() -> list[str]:
    if not shutil.which("ollama"):
        return []
    try:
        out = subprocess.run(
            ["ollama", "ps"], capture_output=True, text=True, timeout=5, check=False
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if out.returncode != 0:
        return []
    lines = out.stdout.strip().splitlines()
    if len(lines) <= 1:
        return []
    return [line.split()[0] for line in lines[1:] if line.strip()]


def _percent(used: int, limit: int | None) -> float | None:
    if limit is None or limit <= 0:
        return None
    return round(100.0 * used / limit, 2)


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc)

    claude_used = _claude_tokens_this_week()
    codex_used = _codex_calls_this_week()
    gemini_used = _gemini_calls_this_week()
    grok_used = _grok_calls_this_week()
    ollama_loaded = _ollama_models_loaded()

    state = {
        "generated": now.isoformat(),
        "week_start": WEEK_START.isoformat(),
        "models": {
            "claude": {
                "used": claude_used,
                "limit": CAPS["claude"]["limit"],
                "unit": CAPS["claude"]["unit"],
                "percent_weekly": _percent(claude_used, CAPS["claude"]["limit"]),
                "plan": CAPS["claude"]["plan"],
            },
            "codex": {
                "used": codex_used,
                "limit": CAPS["codex"]["limit"],
                "unit": CAPS["codex"]["unit"],
                "percent_weekly": _percent(codex_used, CAPS["codex"]["limit"]),
                "plan": CAPS["codex"]["plan"],
            },
            "gemini": {
                "used": gemini_used,
                "limit": CAPS["gemini"]["limit"],
                "unit": CAPS["gemini"]["unit"],
                "percent_weekly": _percent(gemini_used, CAPS["gemini"]["limit"]),
                "plan": CAPS["gemini"]["plan"],
            },
            "grok": {
                "used": grok_used,
                "limit": CAPS["grok"]["limit"],
                "unit": CAPS["grok"]["unit"],
                "percent_weekly": _percent(grok_used, CAPS["grok"]["limit"]),
                "plan": CAPS["grok"]["plan"],
            },
            "ollama": {
                "loaded_models": ollama_loaded,
                "limit": None,
                "unit": None,
                "percent_weekly": None,
                "plan": CAPS["ollama"]["plan"],
            },
        },
    }

    out_dir = Path.home() / ".jarvis"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "quota_state.json"
    out_path.write_text(json.dumps(state, indent=2))

    print(f"✓ Wrote {out_path}")
    for model, info in state["models"].items():
        used = info.get("used")
        pct = info.get("percent_weekly")
        unit = info.get("unit") or "—"
        if pct is not None:
            print(f"  {model:<8} {used:>12} {unit:<6} ({pct}% of weekly)")
        else:
            extra = info.get("loaded_models") or info.get("plan", "")
            print(f"  {model:<8} {str(extra):>30}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
