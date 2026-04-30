"""Vendor-native quota tracker helpers.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_quota_check_v2.py
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

import quota_check as qc  # noqa: E402


NOW = dt.datetime(2026, 4, 30, 12, 0, tzinfo=dt.timezone.utc)


def _jwt(payload: dict) -> str:
    def enc(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}."


def test_claude_usage_v2_weights_cache_reads_and_groups_by_model(tmp_path: Path) -> None:
    print("\n[test] claude_usage_v2_weights_cache_reads_and_groups_by_model ...")
    sessions = tmp_path / ".claude" / "projects" / "repo"
    sessions.mkdir(parents=True)
    session = sessions / "session.jsonl"
    session.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-04-30T11:30:00.000Z",
                        "message": {
                            "model": "claude-opus-4-7",
                            "usage": {
                                "input_tokens": 100,
                                "output_tokens": 25,
                                "cache_creation_input_tokens": 10,
                                "cache_read_input_tokens": 1000,
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-04-29T11:30:00.000Z",
                        "message": {
                            "model": "claude-opus-4-7",
                            "usage": {"input_tokens": 999, "output_tokens": 999},
                        },
                    }
                ),
            ]
        )
        + "\n"
    )
    os.utime(session, (NOW.timestamp(), NOW.timestamp()))

    usage = qc._claude_usage_v2("rolling_5h", sessions_dir=tmp_path / ".claude" / "projects", now=NOW)

    assert usage["observed_unit"] == "weighted_tokens_local_proxy"
    assert usage["observed_native"] == 235.0
    assert usage["models"]["claude-opus-4-7"]["cache_read_input_tokens"] == 1000
    assert usage["diagnostics"]["messages"] == 1
    print("  ✓ cache reads weighted at 0.1x and old messages excluded")


def test_codex_usage_v2_reads_state_sqlite_threads(tmp_path: Path) -> None:
    print("\n[test] codex_usage_v2_reads_state_sqlite_threads ...")
    db = tmp_path / "state_5.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE threads (id TEXT, model TEXT, tokens_used INTEGER, updated_at INTEGER, updated_at_ms INTEGER)"
    )
    recent_ms = int((NOW - dt.timedelta(hours=1)).timestamp() * 1000)
    old_ms = int((NOW - dt.timedelta(days=8)).timestamp() * 1000)
    conn.executemany(
        "INSERT INTO threads VALUES (?, ?, ?, ?, ?)",
        [
            ("a", "gpt-5.5", 100, recent_ms // 1000, recent_ms),
            ("b", "gpt-5.5", 200, recent_ms // 1000, recent_ms),
            ("c", "gpt-5.4", 50, old_ms // 1000, old_ms),
        ],
    )
    conn.commit()
    conn.close()

    usage = qc._codex_usage_v2("rolling_5h", db_path=db, now=NOW)

    assert usage["observed_unit"] == "tokens_local_proxy"
    assert usage["observed_native"] == 300
    assert usage["models"]["gpt-5.5"] == {"tokens_local_proxy": 300, "threads": 2}
    assert "gpt-5.4" not in usage["models"]
    print("  ✓ Codex uses SQLite thread tokens, not history.jsonl line count")


def test_gemini_usage_v2_counts_requests_and_keeps_token_diagnostics(tmp_path: Path) -> None:
    print("\n[test] gemini_usage_v2_counts_requests_and_keeps_token_diagnostics ...")
    chats = tmp_path / "hash" / "chats"
    chats.mkdir(parents=True)
    (chats / "session-2026-04-30T11-00-demo.json").write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "timestamp": "2026-04-30T11:00:00.000Z",
                        "type": "assistant",
                        "model": "gemini-2.5-pro",
                        "tokens": {"input": 10, "output": 20, "total": 30},
                    },
                    {
                        "timestamp": "2026-04-30T11:01:00.000Z",
                        "type": "user",
                        "content": "hello",
                    },
                    {
                        "timestamp": "2026-04-28T11:01:00.000Z",
                        "type": "assistant",
                        "model": "gemini-2.5-pro",
                        "tokens": {"total": 999},
                    },
                ]
            }
        )
    )

    usage = qc._gemini_usage_v2(tmp_dir=tmp_path, now=NOW)

    assert usage["observed_unit"] == "requests"
    assert usage["observed_native"] == 1
    assert usage["diagnostics"]["tokens_total"] == 30
    assert usage["diagnostics"]["tokens_total_present"] is True
    assert usage["models"]["gemini-2.5-pro"]["requests"] == 1
    print("  ✓ Gemini uses requests/day primary with tokens as diagnostics")


def test_grok_usage_v2_absent_until_local_signal_exists(tmp_path: Path) -> None:
    print("\n[test] grok_usage_v2_absent_until_local_signal_exists ...")
    absent = qc._grok_usage_v2(grok_dir=tmp_path / ".grok", env={})
    assert absent["diagnostics"]["signal"] == "absent"
    api = qc._grok_usage_v2(grok_dir=tmp_path / ".grok", env={"XAI_API_KEY": "x"})
    assert api["diagnostics"]["signal"] == "api"
    print("  ✓ Grok reports absent instead of false 0%")


def test_codex_tier_detection_decodes_nested_id_token(tmp_path: Path) -> None:
    print("\n[test] codex_tier_detection_decodes_nested_id_token ...")
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "tokens": {
                    "id_token": _jwt(
                        {"https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}}
                    )
                }
            }
        )
    )

    detected = qc._detect_codex_tier(auth)

    assert detected["tier"] == "plus"
    assert detected["signal"] == "ok"
    print("  ✓ Codex tier comes from auth.json JWT payload")


def test_tier_detection_is_fail_soft(tmp_path: Path, monkeypatch) -> None:
    print("\n[test] tier_detection_is_fail_soft ...")
    bad_auth = tmp_path / "auth.json"
    bad_auth.write_text("{not json")
    assert qc._detect_codex_tier(bad_auth)["tier"] == "unknown"

    oauth = tmp_path / "oauth_creds.json"
    oauth.write_text("{}")
    assert qc._detect_gemini_tier(oauth_path=oauth, env={})["tier"] == "code_assist_individuals"
    assert qc._detect_gemini_tier(oauth_path=tmp_path / "missing", env={"GEMINI_API_KEY": "x"})[
        "tier"
    ] == "ai_studio_api"
    assert qc._detect_gemini_tier(oauth_path=tmp_path / "missing", env={})["tier"] == "unknown"

    caps = tmp_path / "quota_caps.json"
    caps.write_text(json.dumps({"defaults": {"claude_tier": "max_20x"}}))
    assert qc._detect_claude_tier(caps)["tier"] == "max_20x"

    assert qc._detect_grok_tier(grok_dir=tmp_path / "missing", env={})["tier"] == "absent"
    print("  ✓ malformed/missing tier sources never crash")
