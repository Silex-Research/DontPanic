"""Plan 2026-06-04-004 F003 — freshness + refresh contract.

Each page shows generated_at + data age and the exact refresh trigger; a view
past the staleness threshold is visibly flagged.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from dontpanic_orchestrate import state_cli, state_projection

_T0 = dt.datetime(2026, 6, 4, 12, 0, 0, tzinfo=dt.timezone.utc)


def test_fresh_view_is_not_stale_and_carries_refresh_command():
    now = _T0 + dt.timedelta(seconds=60)
    f = state_projection.freshness_status(_T0, now=now)
    assert f["generated_at"] == "2026-06-04T12:00:00Z"
    assert f["data_age_seconds"] == 60
    assert f["is_stale"] is False
    assert f["refresh_command"] == "dontpanic dashboard build"
    assert f["staleness_threshold_seconds"] == 900


def test_view_past_threshold_is_flagged_stale():
    now = _T0 + dt.timedelta(seconds=901)
    f = state_projection.freshness_status(_T0, now=now)
    assert f["is_stale"] is True
    assert f["data_age_seconds"] == 901


def test_clock_skew_never_reports_negative_age():
    now = _T0 - dt.timedelta(seconds=30)  # "now" before generated_at
    f = state_projection.freshness_status(_T0, now=now)
    assert f["data_age_seconds"] == 0
    assert f["is_stale"] is False


def test_custom_threshold_is_honoured():
    now = _T0 + dt.timedelta(seconds=120)
    f = state_projection.freshness_status(_T0, now=now, threshold_seconds=60)
    assert f["is_stale"] is True
    assert f["staleness_threshold_seconds"] == 60


def test_manifest_carries_freshness_block(tmp_path: Path):
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    out_dir = tmp_path / "state"
    assert (
        state_cli._export_dashboard_main(
            ["--out", str(out_dir), "--plans-root", str(plans_root)]
        )
        == 0
    )
    manifest = json.loads((out_dir / "manifest.json").read_text())
    fr = manifest["freshness"]
    assert fr["refresh_command"] == "dontpanic dashboard build"
    assert "generated_at" in fr
    assert fr["data_age_seconds"] == 0  # age is 0 at write time by construction
    assert fr["is_stale"] is False
    # generated_at is a second-precision Z-suffixed ISO timestamp on the same
    # date as the manifest's captured_at.
    assert fr["generated_at"].endswith("Z") and len(fr["generated_at"]) == 20
    assert fr["generated_at"][:10] == manifest["captured_at"][:10]
