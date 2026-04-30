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


# F002 — state shape (vendors{} + legacy models{} mirror + uncalibrated block).
# These tests monkeypatch the helpers to keep _build_state() hermetic; the
# helper-level coverage above already exercises the real signal extraction.

def _stub_helpers(monkeypatch) -> None:
    monkeypatch.setattr(
        qc, "_claude_usage_v2",
        lambda window, **_: {
            "kind": window,
            "observed_native": 100.0 if window == "rolling_7d" else 25.0,
            "observed_unit": "weighted_tokens_local_proxy",
            "models": {"claude-opus-4-7": {"weighted_tokens": 100.0}},
            "diagnostics": {"source": "/fake", "messages": 1, "files_read": 1, "signal": "ok"},
        },
    )
    monkeypatch.setattr(
        qc, "_codex_usage_v2",
        lambda window, **_: {
            "kind": window,
            # 5h returns 50, 7d returns 200 — distinct so tests can verify which
            # window feeds the legacy mirror vs vendors{} primary.
            "observed_native": 50 if window == "rolling_5h" else 200,
            "observed_unit": "tokens_local_proxy",
            "models": {"gpt-5.5": {"tokens_local_proxy": 50, "threads": 1}},
            "diagnostics": {"source": "/fake", "threads": 1, "signal": "ok"},
        },
    )
    monkeypatch.setattr(
        qc, "_gemini_usage_v2",
        lambda **_: {
            "kind": "rolling_24h",
            "observed_native": 3,
            "observed_unit": "requests",
            "models": {"gemini-2.5-pro": {"requests": 3}},
            "diagnostics": {"source": "/fake", "signal": "ok", "tokens_total": 90, "tokens_total_present": True},
        },
    )
    monkeypatch.setattr(
        qc, "_grok_usage_v2",
        lambda **_: {
            "kind": "rolling_2h",
            "observed_native": None,
            "observed_unit": None,
            "models": {},
            "diagnostics": {"source": "/fake", "signal": "absent"},
        },
    )
    monkeypatch.setattr(qc, "_ollama_models_loaded", lambda: [])
    monkeypatch.setattr(qc, "_detect_claude_tier", lambda *a, **k: {"tier": "max_20x", "source": "/fake", "signal": "default"})
    monkeypatch.setattr(qc, "_detect_codex_tier", lambda *a, **k: {"tier": "plus", "source": "/fake", "signal": "ok"})
    monkeypatch.setattr(qc, "_detect_gemini_tier", lambda *a, **k: {"tier": "code_assist_individuals", "source": "/fake", "signal": "oauth"})
    monkeypatch.setattr(qc, "_detect_grok_tier", lambda *a, **k: {"tier": "absent", "source": "/fake", "signal": "absent"})
    # Hermetic isolation from operator-set ~/.jarvis/quota_calibration.json (F005):
    # _build_state lazy-imports calibration_loader and calls .load() with no args
    # → reads the real file. Patch .load to return {} so the v2 state-shape tests
    # always see uncalibrated default blocks regardless of operator state.
    from jarvis_orchestrate import calibration_loader as _cal
    monkeypatch.setattr(_cal, "load", lambda *a, **k: {})


def test_build_state_emits_schema_v2_with_vendors_block(monkeypatch) -> None:
    print("\n[test] build_state_emits_schema_v2_with_vendors_block ...")
    _stub_helpers(monkeypatch)

    state = qc._build_state(now=NOW)

    assert state["schema_version"] == 2
    assert "generated" in state
    assert set(state["vendors"].keys()) == {"claude", "codex", "gemini", "grok"}
    assert state["vendors"]["claude"]["tier"] == "max_20x"
    assert state["vendors"]["codex"]["tier"] == "plus"
    assert state["vendors"]["gemini"]["tier"] == "code_assist_individuals"
    assert state["vendors"]["grok"]["tier"] == "absent"
    print("  ✓ schema_version: 2 + vendors{} block with 4 vendors + tier labels")


def test_build_state_claude_windows_have_uncalibrated_block(monkeypatch) -> None:
    print("\n[test] build_state_claude_windows_have_uncalibrated_block ...")
    _stub_helpers(monkeypatch)

    state = qc._build_state(now=NOW)
    claude_windows = state["vendors"]["claude"]["windows"]

    assert set(claude_windows.keys()) == {"rolling_7d", "rolling_5h"}
    for wname, w in claude_windows.items():
        assert w["calibration"] == {
            "ratio": None,
            "confidence": "uncalibrated",
            "source": None,
            "stamped_at": None,
        }, f"window {wname} missing uncalibrated block"
    # Other vendors do NOT carry a calibration block (it is Claude-specific until
    # F005's calibrate-claude command extends).
    assert "calibration" not in state["vendors"]["codex"]["windows"]["rolling_5h"]
    assert "calibration" not in state["vendors"]["gemini"]["windows"]["rolling_24h"]
    print("  ✓ both Claude windows carry explicit-uncalibrated calibration block")


def test_build_state_grok_empty_windows_with_signal(monkeypatch) -> None:
    print("\n[test] build_state_grok_empty_windows_with_signal ...")
    _stub_helpers(monkeypatch)

    state = qc._build_state(now=NOW)
    grok = state["vendors"]["grok"]

    assert grok["windows"] == {}
    assert grok["signal"] == "absent"
    assert grok["tier"] == "absent"
    print("  ✓ Grok block carries empty windows + explicit signal:absent")


def test_build_state_preserves_legacy_models_mirror(monkeypatch) -> None:
    """Confirms F002 keeps the F020 v1 shape so cost-model + cost-guard skills
    keep working until plan 2026-04-29-004 reactivation migrates them."""
    print("\n[test] build_state_preserves_legacy_models_mirror ...")
    _stub_helpers(monkeypatch)

    state = qc._build_state(now=NOW)

    assert "models" in state
    legacy_keys = set(state["models"].keys())
    assert legacy_keys == {"claude", "codex", "gemini", "grok", "ollama"}
    # Claude keeps its (deprecated) percent_weekly approximation against the old
    # 1B/wk divisor — cost-model/cost-guard read used/limit/unit, not the percent.
    assert state["models"]["claude"]["used"] == 100
    assert state["models"]["claude"]["limit"] == qc.CAPS["claude"]["limit"]
    # Codex legacy mirror MUST use rolling_7d (200 in stub) for parity with the
    # post-F001 weekly framing; vendors{}.codex.windows.rolling_5h (50 in stub)
    # is what F006 will read for the breaker. This guards against a subtle shape
    # regression where switching the mirror to rolling_5h would silently shrink
    # cost-model/cost-guard projections.
    assert state["models"]["codex"]["used"] == 200, "legacy codex mirror must use rolling_7d"
    assert state["vendors"]["codex"]["windows"]["rolling_5h"]["observed_native"] == 50
    assert state["vendors"]["codex"]["windows"]["rolling_7d"]["observed_native"] == 200
    # Codex + grok stay at percent_weekly=null (all consumers tolerate null).
    assert state["models"]["codex"]["percent_weekly"] is None
    assert state["models"]["grok"]["percent_weekly"] is None
    # Deprecation marker is visible in state.
    assert "_legacy_mirror_note" in state
    assert "cost-model" in state["_legacy_mirror_note"]
    assert "cost-guard" in state["_legacy_mirror_note"]
    print("  ✓ models{} legacy mirror present, codex on rolling_7d, deprecation marker")
