"""F005 — calibration_loader.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_calibration_loader.py
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from jarvis_orchestrate import calibration_loader as cal


NOW = dt.datetime(2026, 4, 30, 12, 0, tzinfo=dt.timezone.utc)


def test_load_returns_empty_when_file_missing(tmp_path: Path) -> None:
    print("\n[test] load_returns_empty_when_file_missing ...")
    assert cal.load(tmp_path / "missing.json") == {}
    print("  ✓ missing file → {} (fail-soft, no exception)")


def test_load_returns_empty_on_malformed_json(tmp_path: Path) -> None:
    print("\n[test] load_returns_empty_on_malformed_json ...")
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert cal.load(p) == {}
    print("  ✓ malformed JSON → {} (no crash during quota refresh)")


def test_load_returns_empty_on_wrong_schema_version(tmp_path: Path) -> None:
    print("\n[test] load_returns_empty_on_wrong_schema_version ...")
    p = tmp_path / "wrong.json"
    p.write_text(json.dumps({"schema_version": 99, "claude": {"rolling_7d": {"ratio": 0.5}}}))
    assert cal.load(p) == {}
    print("  ✓ schema_version != 1 ignored (forward-incompat safety)")


def test_write_calibration_round_trip(tmp_path: Path) -> None:
    print("\n[test] write_calibration_round_trip ...")
    p = tmp_path / "quota_calibration.json"
    entry = cal.write_calibration(
        vendor="claude",
        window="rolling_7d",
        dashboard_pct=13.0,
        observed_native=585_072_343.7,
        now=NOW,
        path=p,
    )
    assert entry["ratio"] == pytest.approx(13.0 / 585_072_343.7)
    assert entry["confidence"] == "manual"
    assert entry["dashboard_pct"] == 13.0
    assert entry["observed_native"] == 585_072_343.7
    loaded = cal.load(p)
    assert loaded["claude"]["rolling_7d"]["ratio"] == entry["ratio"]
    assert loaded["schema_version"] == cal.CALIBRATION_SCHEMA_VERSION
    print("  ✓ write → load → fields match")


def test_write_calibration_preserves_other_window(tmp_path: Path) -> None:
    print("\n[test] write_calibration_preserves_other_window ...")
    p = tmp_path / "quota_calibration.json"
    cal.write_calibration(
        vendor="claude", window="rolling_7d",
        dashboard_pct=13.0, observed_native=585_000_000, now=NOW, path=p,
    )
    cal.write_calibration(
        vendor="claude", window="rolling_5h",
        dashboard_pct=9.0, observed_native=18_000_000, now=NOW, path=p,
    )
    loaded = cal.load(p)
    assert loaded["claude"]["rolling_7d"]["dashboard_pct"] == 13.0
    assert loaded["claude"]["rolling_5h"]["dashboard_pct"] == 9.0
    print("  ✓ writing rolling_5h does not erase rolling_7d entry")


@pytest.mark.parametrize(
    "kwargs, error_substr",
    [
        # Regex special chars escaped for pytest.raises(match=...) since match=
        # is re.search; literal "(0, 100]" would parse as a group.
        ({"dashboard_pct": 0}, r"must be in \(0, 100\]"),
        ({"dashboard_pct": -5}, r"must be in \(0, 100\]"),
        ({"dashboard_pct": 101}, r"must be in \(0, 100\]"),
        ({"observed_native": 0}, "positive number"),
        ({"observed_native": -100}, "positive number"),
        ({"window": "rolling_24h"}, "must be one of"),
        ({"window": "weekly"}, "must be one of"),
        ({"confidence": "auto-from-vendor-api"}, "must be one of"),
    ],
)
def test_write_calibration_validates_inputs(tmp_path: Path, kwargs, error_substr) -> None:
    print(f"\n[test] write_calibration_validates_inputs ({list(kwargs.keys())}) ...")
    base = {
        "vendor": "claude",
        "window": "rolling_7d",
        "dashboard_pct": 13.0,
        "observed_native": 585_000_000,
        "now": NOW,
        "path": tmp_path / "out.json",
    }
    base.update(kwargs)
    with pytest.raises(cal.CalibrationError, match=error_substr):
        cal.write_calibration(**base)
    print(f"  ✓ rejected with {error_substr!r}")


def test_get_for_window_returns_breaker_shape(tmp_path: Path) -> None:
    """get_for_window strips the operator-input metadata (dashboard_pct,
    observed_native) and returns only the four fields F006 will read into
    vendors.<v>.windows.<w>.calibration."""
    print("\n[test] get_for_window_returns_breaker_shape ...")
    p = tmp_path / "out.json"
    cal.write_calibration(
        vendor="claude", window="rolling_7d",
        dashboard_pct=13.0, observed_native=585_000_000, now=NOW, path=p,
    )
    data = cal.load(p)
    block = cal.get_for_window(data, "claude", "rolling_7d")
    assert set(block.keys()) == {"ratio", "confidence", "source", "stamped_at"}
    assert block["confidence"] == "manual"
    assert "dashboard_pct" not in block
    assert "observed_native" not in block
    print("  ✓ breaker-shape projection drops operator-input metadata")


def test_get_for_window_returns_none_on_miss(tmp_path: Path) -> None:
    print("\n[test] get_for_window_returns_none_on_miss ...")
    p = tmp_path / "out.json"
    cal.write_calibration(
        vendor="claude", window="rolling_7d",
        dashboard_pct=13.0, observed_native=585_000_000, now=NOW, path=p,
    )
    data = cal.load(p)
    assert cal.get_for_window(data, "claude", "rolling_5h") is None
    assert cal.get_for_window(data, "codex", "rolling_5h") is None
    assert cal.get_for_window({}, "claude", "rolling_7d") is None
    print("  ✓ None on any vendor/window miss; safe to chain into uncalibrated default")


def test_is_stale_threshold_boundary(tmp_path: Path) -> None:
    print("\n[test] is_stale_threshold_boundary ...")
    fresh = {"stamped_at": (NOW - dt.timedelta(days=3)).isoformat()}
    aged = {"stamped_at": (NOW - dt.timedelta(days=8)).isoformat()}
    edge = {"stamped_at": (NOW - dt.timedelta(days=7, seconds=1)).isoformat()}

    assert not cal.is_stale(fresh, now=NOW)
    assert cal.is_stale(aged, now=NOW)
    assert cal.is_stale(edge, now=NOW)
    assert not cal.is_stale({}, now=NOW)  # no stamp → not stale
    assert not cal.is_stale(None, now=NOW)
    assert not cal.is_stale({"stamped_at": "garbage"}, now=NOW)
    print(f"  ✓ stale at >{cal.STALE_WARNING_DAYS}d; missing/malformed timestamps treated as not-stale")


def test_quota_check_integrates_calibration_into_vendors_block(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: write a calibration to a sticky file path, point the loader
    at it via monkeypatched CALIBRATION_FILE, run _build_state via the public
    quota_check entry, confirm vendors.claude.windows.rolling_7d.calibration
    carries the manual block (ratio + stamped_at) — and rolling_5h stays
    uncalibrated."""
    print("\n[test] quota_check_integrates_calibration_into_vendors_block ...")
    import sys as _sys
    _sys.path.insert(0, "scripts")
    import quota_check as qc

    cal_path = tmp_path / "quota_calibration.json"
    cal.write_calibration(
        vendor="claude", window="rolling_7d",
        dashboard_pct=13.0, observed_native=585_072_343.7,
        now=NOW, path=cal_path,
    )
    monkeypatch.setattr(cal, "CALIBRATION_FILE", cal_path)

    # Stub the vendor helpers to avoid touching the real machine state.
    monkeypatch.setattr(qc, "_claude_usage_v2",
        lambda window, **_: {"kind": window, "observed_native": 100, "observed_unit": "weighted_tokens_local_proxy",
                             "models": {}, "diagnostics": {"signal": "ok"}})
    monkeypatch.setattr(qc, "_codex_usage_v2",
        lambda window, **_: {"kind": window, "observed_native": 0, "observed_unit": "tokens_local_proxy",
                             "models": {}, "diagnostics": {"signal": "ok"}})
    monkeypatch.setattr(qc, "_gemini_usage_v2",
        lambda **_: {"kind": "rolling_24h", "observed_native": 0, "observed_unit": "requests",
                     "models": {}, "diagnostics": {"signal": "ok"}})
    monkeypatch.setattr(qc, "_grok_usage_v2",
        lambda **_: {"kind": "rolling_2h", "observed_native": None, "observed_unit": None,
                     "models": {}, "diagnostics": {"signal": "absent"}})
    monkeypatch.setattr(qc, "_ollama_models_loaded", lambda: [])
    monkeypatch.setattr(qc, "_detect_claude_tier", lambda *a, **k: {"tier": "max_20x", "source": "/fake", "signal": "default"})
    monkeypatch.setattr(qc, "_detect_codex_tier", lambda *a, **k: {"tier": "plus", "source": "/fake", "signal": "ok"})
    monkeypatch.setattr(qc, "_detect_gemini_tier", lambda *a, **k: {"tier": "code_assist_individuals", "source": "/fake", "signal": "oauth"})
    monkeypatch.setattr(qc, "_detect_grok_tier", lambda *a, **k: {"tier": "absent", "source": "/fake", "signal": "absent"})

    state = qc._build_state(now=NOW)

    rolling_7d_cal = state["vendors"]["claude"]["windows"]["rolling_7d"]["calibration"]
    rolling_5h_cal = state["vendors"]["claude"]["windows"]["rolling_5h"]["calibration"]

    assert rolling_7d_cal["confidence"] == "manual"
    assert rolling_7d_cal["ratio"] == pytest.approx(13.0 / 585_072_343.7)
    assert rolling_7d_cal["source"] == "operator_dashboard_sample"
    assert rolling_7d_cal["stamped_at"]

    assert rolling_5h_cal == {
        "ratio": None,
        "confidence": "uncalibrated",
        "source": None,
        "stamped_at": None,
    }
    print("  ✓ rolling_7d carries manual calibration; rolling_5h stays uncalibrated")
