#!/usr/bin/env python3
"""F020 — per-model weekly token consumption tracker.

Writes ~/.jarvis/quota_state.json. Supervisor reads before every dispatch
to enforce per-tier quota caps + interactive backoff (parent plan F007).

Caps below are configurable estimates — refine as we get real Max plan reset signals.
"""

from __future__ import annotations

import datetime as dt
import base64
import json
import os
import shutil
import sqlite3
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

WINDOWS: dict[str, dt.timedelta] = {
    "rolling_5h": dt.timedelta(hours=5),
    "rolling_24h": dt.timedelta(hours=24),
    "rolling_7d": dt.timedelta(days=7),
}

CACHE_READ_WEIGHT = 0.1


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _window_start(window: str, *, now: dt.datetime | None = None) -> dt.datetime:
    if window not in WINDOWS:
        raise ValueError(f"unknown window: {window}")
    return (now or _utcnow()) - WINDOWS[window]


def _parse_iso_timestamp(raw: Any) -> dt.datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(
            dt.timezone.utc
        )
    except ValueError:
        return None


def _safe_int(raw: Any) -> int:
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _claude_usage_v2(
    window: str,
    *,
    sessions_dir: Path | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Read Claude Code JSONL sessions in the requested rolling window.

    This is a local proxy for subscriber usage, not Anthropic billing truth.
    Cache reads are weighted at 0.1x to avoid the old 1.0x overcount.
    """
    root = sessions_dir or (Path.home() / ".claude" / "projects")
    start = _window_start(window, now=now)
    result: dict[str, Any] = {
        "kind": window,
        "observed_native": 0.0,
        "observed_unit": "weighted_tokens_local_proxy",
        "models": {},
        "diagnostics": {
            "source": str(root),
            "messages": 0,
            "files_read": 0,
            "signal": "ok" if root.is_dir() else "absent",
        },
    }
    if not root.is_dir():
        return result

    models: dict[str, dict[str, float | int]] = {}
    for session_file in root.rglob("*.jsonl"):
        try:
            if session_file.stat().st_mtime < start.timestamp():
                continue
            result["diagnostics"]["files_read"] += 1
            for line in session_file.read_text(errors="ignore").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_iso_timestamp(entry.get("timestamp"))
                if ts is None or ts < start:
                    continue
                message = entry.get("message") or {}
                usage = message.get("usage") or entry.get("usage") or {}
                if not usage:
                    continue
                model = message.get("model") or entry.get("model") or "unknown"
                input_tokens = _safe_int(usage.get("input_tokens"))
                output_tokens = _safe_int(usage.get("output_tokens"))
                cache_creation = _safe_int(usage.get("cache_creation_input_tokens"))
                cache_read = _safe_int(usage.get("cache_read_input_tokens"))
                weighted = (
                    input_tokens
                    + output_tokens
                    + cache_creation
                    + (cache_read * CACHE_READ_WEIGHT)
                )
                bucket = models.setdefault(
                    model,
                    {
                        "weighted_tokens": 0.0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "messages": 0,
                    },
                )
                bucket["weighted_tokens"] += weighted
                bucket["input_tokens"] += input_tokens
                bucket["output_tokens"] += output_tokens
                bucket["cache_creation_input_tokens"] += cache_creation
                bucket["cache_read_input_tokens"] += cache_read
                bucket["messages"] += 1
                result["diagnostics"]["messages"] += 1
        except OSError:
            continue

    result["models"] = models
    result["observed_native"] = round(
        sum(float(v["weighted_tokens"]) for v in models.values()), 2
    )
    return result


def _codex_usage_v2(
    window: str,
    *,
    db_path: Path | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Read Codex CLI's local thread token proxy from state_5.sqlite."""
    path = db_path or (Path.home() / ".codex" / "state_5.sqlite")
    start = _window_start(window, now=now)
    result: dict[str, Any] = {
        "kind": window,
        "observed_native": 0,
        "observed_unit": "tokens_local_proxy",
        "models": {},
        "diagnostics": {
            "source": str(path),
            "threads": 0,
            "signal": "ok" if path.is_file() else "absent",
        },
    }
    if not path.is_file():
        return result

    cutoff_ms = int(start.timestamp() * 1000)
    query = """
        SELECT COALESCE(model, '') AS model, COUNT(*) AS threads, SUM(tokens_used) AS tokens
        FROM threads
        WHERE COALESCE(updated_at_ms, updated_at * 1000) >= ?
        GROUP BY COALESCE(model, '')
    """
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            rows = conn.execute(query, (cutoff_ms,)).fetchall()
    except sqlite3.Error as exc:
        result["diagnostics"]["signal"] = "schema_mismatch"
        result["diagnostics"]["error"] = str(exc)
        return result

    models: dict[str, dict[str, int]] = {}
    total = 0
    thread_count = 0
    for model, threads, tokens in rows:
        name = model or "unknown"
        token_count = int(tokens or 0)
        threads_count = int(threads or 0)
        models[name] = {"tokens_local_proxy": token_count, "threads": threads_count}
        total += token_count
        thread_count += threads_count
    result["models"] = models
    result["observed_native"] = total
    result["diagnostics"]["threads"] = thread_count
    return result


def _gemini_usage_v2(
    *,
    tmp_dir: Path | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Read Gemini CLI chat sessions for the last 24h.

    Google publishes request/day limits for Code Assist; token totals are kept
    only as diagnostics when present.
    """
    root = tmp_dir or (Path.home() / ".gemini" / "tmp")
    start = _window_start("rolling_24h", now=now)
    result: dict[str, Any] = {
        "kind": "rolling_24h",
        "observed_native": 0,
        "observed_unit": "requests",
        "models": {},
        "diagnostics": {
            "source": str(root),
            "sessions": 0,
            "messages": 0,
            "tokens_total": 0,
            "tokens_total_present": False,
            "signal": "ok" if root.is_dir() else "absent",
        },
    }
    if not root.is_dir():
        return result

    models: dict[str, dict[str, int]] = {}
    for session_file in root.glob("*/chats/session-*.json"):
        try:
            data = json.loads(session_file.read_text(errors="ignore"))
        except (OSError, json.JSONDecodeError):
            continue
        seen_session = False
        for message in data.get("messages") or []:
            ts = _parse_iso_timestamp(message.get("timestamp"))
            if ts is None or ts < start:
                continue
            if message.get("type") == "info":
                continue
            model = message.get("model") or "unknown"
            bucket = models.setdefault(
                model, {"requests": 0, "messages": 0, "tokens_total": 0}
            )
            bucket["messages"] += 1
            result["diagnostics"]["messages"] += 1
            if message.get("type") in {"assistant", "model"} or message.get("tokens"):
                bucket["requests"] += 1
                result["observed_native"] += 1
            tokens = message.get("tokens") or {}
            if "total" in tokens:
                total = _safe_int(tokens.get("total"))
                bucket["tokens_total"] += total
                result["diagnostics"]["tokens_total"] += total
                result["diagnostics"]["tokens_total_present"] = True
            seen_session = True
        if seen_session:
            result["diagnostics"]["sessions"] += 1
    result["models"] = models
    if not result["diagnostics"]["tokens_total_present"]:
        result["diagnostics"]["tokens_total"] = None
    return result


def _grok_usage_v2(
    *,
    grok_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env_map = env if env is not None else os.environ
    root = grok_dir or (Path.home() / ".grok")
    has_cli_state = root.exists()
    has_api_key = bool(env_map.get("XAI_API_KEY"))
    signal = "api" if has_api_key else "cli_installed" if has_cli_state else "absent"
    return {
        "kind": "none",
        "observed_native": None,
        "observed_unit": None,
        "models": {},
        "diagnostics": {
            "source": str(root),
            "signal": signal,
            "has_api_key": has_api_key,
            "has_cli_state": has_cli_state,
        },
    }


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(decoded)
        return data if isinstance(data, dict) else {}
    except (IndexError, ValueError, json.JSONDecodeError):
        return {}


def _detect_codex_tier(auth_path: Path | None = None) -> dict[str, Any]:
    path = auth_path or (Path.home() / ".codex" / "auth.json")
    if not path.is_file():
        return {"tier": "unknown", "source": str(path), "signal": "absent"}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"tier": "unknown", "source": str(path), "signal": "parse_error", "error": str(exc)}
    tokens = data.get("tokens") if isinstance(data, dict) else {}
    token = (tokens or {}).get("id_token") or data.get("id_token") or ""
    payload = _decode_jwt_payload(token) if isinstance(token, str) else {}
    auth_claims = payload.get("https://api.openai.com/auth")
    if not isinstance(auth_claims, dict):
        auth_claims = {}
    raw = (
        payload.get("chatgpt_plan_type")
        or auth_claims.get("chatgpt_plan_type")
        or payload.get("plan_type")
        or payload.get("plan")
    )
    tier = _normalize_codex_tier(raw)
    return {
        "tier": tier,
        "source": str(path),
        "signal": "ok" if raw else "missing_claim",
        "claim": "chatgpt_plan_type" if raw else None,
    }


def _normalize_codex_tier(raw: Any) -> str:
    if not isinstance(raw, str) or not raw:
        return "unknown"
    value = raw.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "plus": "plus",
        "chatgpt_plus": "plus",
        "pro": "pro",
        "chatgpt_pro": "pro",
        "pro_5x": "pro_5x",
        "max_5x": "pro_5x",
        "pro_20x": "pro_20x",
        "max_20x": "pro_20x",
        "business": "business",
        "team": "business",
        "enterprise": "enterprise",
    }
    return aliases.get(value, value)


def _detect_gemini_tier(
    *,
    oauth_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env_map = env if env is not None else os.environ
    path = oauth_path or (Path.home() / ".gemini" / "oauth_creds.json")
    has_api_key = bool(env_map.get("GEMINI_API_KEY"))
    if path.is_file():
        return {"tier": "code_assist_individuals", "source": str(path), "signal": "oauth"}
    if has_api_key:
        return {"tier": "ai_studio_api", "source": "GEMINI_API_KEY", "signal": "api_key"}
    return {"tier": "unknown", "source": str(path), "signal": "absent"}


def _detect_claude_tier(caps_path: Path | None = None) -> dict[str, Any]:
    path = caps_path or (Path.home() / ".jarvis" / "quota_caps.json")
    tier = "max_20x"
    signal = "default"
    if path.is_file():
        try:
            data = json.loads(path.read_text())
            configured = (
                ((data.get("claude") or {}).get("tier"))
                or data.get("claude_tier")
                or ((data.get("defaults") or {}).get("claude_tier"))
            )
            if isinstance(configured, str) and configured:
                tier = configured
                signal = "operator_config"
        except (OSError, json.JSONDecodeError):
            signal = "parse_error"
    return {"tier": tier, "source": str(path), "signal": signal}


def _detect_grok_tier(
    *,
    grok_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    usage = _grok_usage_v2(grok_dir=grok_dir, env=env)
    signal = usage["diagnostics"]["signal"]
    if signal == "api":
        tier = "api"
    elif signal == "cli_installed":
        tier = "cli_installed"
    else:
        tier = "absent"
    return {"tier": tier, "source": usage["diagnostics"]["source"], "signal": signal}


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

    claude_usage = _claude_usage_v2("rolling_7d", now=now)
    claude_used = int(claude_usage.get("observed_native") or 0)
    codex_usage = _codex_usage_v2("rolling_7d", now=now)
    codex_used = int(codex_usage.get("observed_native") or 0)
    gemini_usage = _gemini_usage_v2(now=now)
    gemini_used = int(gemini_usage.get("observed_native") or 0)
    grok_usage = _grok_usage_v2()
    ollama_loaded = _ollama_models_loaded()

    state = {
        "generated": now.isoformat(),
        "week_start": WEEK_START.isoformat(),
        "models": {
            "claude": {
                "used": claude_used,
                "limit": CAPS["claude"]["limit"],
                "unit": claude_usage.get("observed_unit") or CAPS["claude"]["unit"],
                "percent_weekly": _percent(claude_used, CAPS["claude"]["limit"]),
                "plan": CAPS["claude"]["plan"],
            },
            "codex": {
                "used": codex_used,
                "limit": None,
                "unit": codex_usage.get("observed_unit") or CAPS["codex"]["unit"],
                "percent_weekly": None,
                "plan": "local SQLite token proxy; v2 caps pending",
            },
            "gemini": {
                "used": gemini_used,
                "limit": 1_000,
                "unit": gemini_usage.get("observed_unit") or CAPS["gemini"]["unit"],
                "percent_weekly": _percent(gemini_used, 1_000),
                "plan": "Code Assist Individuals daily request cap",
            },
            "grok": {
                "used": None,
                "limit": None,
                "unit": None,
                "percent_weekly": None,
                "plan": f"signal: {grok_usage['diagnostics']['signal']}",
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
        elif used is not None:
            print(f"  {model:<8} {used:>12} {unit:<18} ({info.get('plan', '')})")
        else:
            extra = info.get("loaded_models") or info.get("plan", "")
            print(f"  {model:<8} {str(extra):>30}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
