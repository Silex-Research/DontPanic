"""F005 — operator-set calibration for vendor-native windows.

Reads ~/.jarvis/quota_calibration.json. Separate from ~/.jarvis/quota_state.json
because the latter is generated state (overwritten on every quota_check.py
refresh) and calibration is operator configuration that must survive refreshes.

Currently scoped to Claude. Anthropic does not publish the consumer Max plan
weekly token budget, so the only way to convert local weighted_tokens_local_proxy
into a comparable percent_of_plan number is for the operator to sample the
claude.ai/settings/usage dashboard and run:

    python -m jarvis_orchestrate calibrate-claude --dashboard-pct 13 --window rolling_7d

That records:

    ratio = dashboard_pct / observed_native_at_sample_time

so F006 can compute observed_native * ratio at trip-check time. The longer
operators wait between samples, the more drift accumulates (cache pricing
shifts, model mix changes); quota_check.py emits a stderr warning when the
sample is older than STALE_WARNING_DAYS.

File shape (schema_version 1):

    {
      "schema_version": 1,
      "claude": {
        "rolling_7d": {
          "ratio": 2.245e-08,
          "confidence": "manual",
          "source": "operator_dashboard_sample",
          "dashboard_pct": 13.0,
          "observed_native": 578811576,
          "stamped_at": "2026-04-30T17:30:00+00:00"
        }
      }
    }
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

CALIBRATION_FILE = Path.home() / ".jarvis" / "quota_calibration.json"
CALIBRATION_SCHEMA_VERSION = 1
SUPPORTED_WINDOWS = {"rolling_7d", "rolling_5h"}
STALE_WARNING_DAYS = 7

# Confidence ladder: uncalibrated (no operator input), manual (this command's
# output), auto (reserved — would require a vendor API that does not exist for
# the consumer Max plan; never set automatically).
CONFIDENCE_LEVELS = {"uncalibrated", "manual", "auto"}


class CalibrationError(Exception):
    """Raised on malformed calibration file or invalid calibrate input."""


def load(path: Path | None = None) -> dict[str, Any]:
    """Read calibration sticky file. Returns {} (empty dict) when the file is
    absent, malformed, or has the wrong schema_version. Never raises — quota
    refresh must not crash on calibration-file issues. Callers needing strict
    validation use validate() directly.
    """
    p = path or CALIBRATION_FILE
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("schema_version") != CALIBRATION_SCHEMA_VERSION:
        return {}
    return data


def get_for_window(data: dict[str, Any], vendor: str, window: str) -> dict[str, Any] | None:
    """Return the merged calibration block for vendor.window, or None.

    Output is the shape that goes into vendors.<v>.windows.<w>.calibration:
    {ratio, confidence, source, stamped_at}. Extra fields like dashboard_pct
    and observed_native stay in the sticky file but are not echoed into
    quota_state.json (those are operator-input metadata, not breaker inputs).
    """
    vblock = data.get(vendor)
    if not isinstance(vblock, dict):
        return None
    wblock = vblock.get(window)
    if not isinstance(wblock, dict):
        return None
    ratio = wblock.get("ratio")
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool):
        return None
    return {
        "ratio": float(ratio),
        "confidence": wblock.get("confidence") or "manual",
        "source": wblock.get("source"),
        "stamped_at": wblock.get("stamped_at"),
    }


def write_calibration(
    *,
    vendor: str,
    window: str,
    dashboard_pct: float,
    observed_native: float,
    confidence: str = "manual",
    source: str = "operator_dashboard_sample",
    now: dt.datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Validate inputs, compute ratio, merge into the sticky file via atomic
    tmp+os.replace, return the written entry. Preserves any other
    vendor/window entries already present.

    Raises CalibrationError on validation failures. Window name is restricted
    to SUPPORTED_WINDOWS so we don't quietly accept rolling_24h etc. (Claude
    has no 24h window in the v2 vendors block). The atomic-write is what makes
    this safe to run while quota_check.py may be reading the same file.
    """
    if not (0 < dashboard_pct <= 100):
        raise CalibrationError(f"dashboard_pct must be in (0, 100]; got {dashboard_pct!r}")
    if not isinstance(observed_native, (int, float)) or observed_native <= 0:
        raise CalibrationError(
            f"observed_native must be a positive number; got {observed_native!r}"
        )
    if window not in SUPPORTED_WINDOWS:
        raise CalibrationError(f"window must be one of {sorted(SUPPORTED_WINDOWS)}; got {window!r}")
    if confidence not in CONFIDENCE_LEVELS:
        raise CalibrationError(
            f"confidence must be one of {sorted(CONFIDENCE_LEVELS)}; got {confidence!r}"
        )

    p = path or CALIBRATION_FILE
    p.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if p.is_file():
        try:
            parsed = json.loads(p.read_text())
            if (
                isinstance(parsed, dict)
                and parsed.get("schema_version") == CALIBRATION_SCHEMA_VERSION
            ):
                existing = parsed
        except (OSError, json.JSONDecodeError):
            existing = {}

    if not existing:
        existing = {"schema_version": CALIBRATION_SCHEMA_VERSION}

    ratio = dashboard_pct / float(observed_native)
    stamped_at = (now or dt.datetime.now(dt.timezone.utc)).isoformat()

    entry = {
        "ratio": ratio,
        "confidence": confidence,
        "source": source,
        "dashboard_pct": float(dashboard_pct),
        "observed_native": float(observed_native),
        "stamped_at": stamped_at,
    }

    vendors = existing.setdefault(vendor, {})
    if not isinstance(vendors, dict):
        vendors = existing[vendor] = {}
    vendors[window] = entry

    # Atomic write: tmp file in the same directory + os.replace. Prevents
    # quota_check.py from reading a half-written file if it runs mid-write,
    # and prevents data loss if the process is interrupted between truncate
    # and write. Same-dir tmp is required for os.replace to be atomic on
    # the same filesystem.
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2) + "\n")
    os.replace(tmp, p)
    return entry


def is_stale(
    calibration_block: dict[str, Any] | None,
    *,
    now: dt.datetime | None = None,
    threshold_days: int = STALE_WARNING_DAYS,
) -> bool:
    """Return True when the block has a stamped_at older than threshold_days.

    Treats absent / malformed timestamps as not-stale (caller's job to handle
    those separately — this function specifically asks 'is this aged?').
    """
    if not isinstance(calibration_block, dict):
        return False
    stamped = calibration_block.get("stamped_at")
    if not isinstance(stamped, str):
        return False
    try:
        ts = dt.datetime.fromisoformat(stamped.replace("Z", "+00:00"))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    cutoff = (now or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(days=threshold_days)
    return ts < cutoff
