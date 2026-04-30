"""F004 — operator-editable per-vendor quota caps.

Reads ~/.jarvis/quota_caps.json. Keyed by vendor.tier.window. Loaded by
F006 budget_ceiling to compute trip threshold against the v2 vendors{}
observed state in ~/.jarvis/quota_state.json.

File shape (schema_version 1):

    {
      "schema_version": 1,
      "defaults": {"claude_tier": "max_20x"},
      "claude": {"max_20x": {
          "rolling_7d": {"cap": 100, "unit": "percent_of_plan"},
          "rolling_5h": {"cap": 100, "unit": "percent_of_plan"}}},
      "codex": {"plus": {"rolling_5h": {"cap": <N>, "unit": "tokens_local_proxy"}}},
      "gemini": {"code_assist_individuals": {"rolling_24h": {"cap": 1000, "unit": "requests"}}},
      "grok": {}
    }

Unit semantics (F006 will compare observed_native vs cap):

- Claude rolling_*: cap unit is `percent_of_plan`. The observed unit in
  vendors{} is `weighted_tokens_local_proxy`. F005's calibration.ratio
  bridges them — F006 must REFUSE or warn when calibration.confidence ==
  "uncalibrated", because dividing weighted tokens by 100 false-trips
  immediately. See plan 2026-04-30-001 features.json F006 description.

- Codex / Gemini: cap unit must equal the corresponding observed_unit
  (`tokens_local_proxy` / `requests`) — no calibration bridge. Validator
  records the convention but does not yet hard-enforce the cross-file
  unit-match (would require coupling to quota_check at validate time);
  F006 will assert at compute time.

- Grok: empty block. F006 skips vendors without a tier+window match.

Reasoning for keeping caps OUT of dashboard/state/costs.json (different
audience: app-level GCP $-spend vs per-vendor agent quota): see
feedback_operator_config_separation.md.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

CAPS_FILE = Path.home() / ".jarvis" / "quota_caps.json"
CAPS_SCHEMA_VERSION = 1


def _effective_caps_path(path: Path | None) -> Path:
    """Honor JARVIS_QUOTA_CAPS_PATH for hermetic test isolation, mirroring the
    JARVIS_QUOTA_STATE_PATH / JARVIS_BREAKER_HISTORY_PATH / etc. pattern. An
    explicit path arg always wins."""
    if path is not None:
        return path
    env_override = os.environ.get("JARVIS_QUOTA_CAPS_PATH")
    if env_override:
        return Path(env_override)
    return CAPS_FILE

KNOWN_VENDORS = {"claude", "codex", "gemini", "grok"}

KNOWN_TIERS: dict[str, set[str]] = {
    "claude": {"max_20x", "max_5x", "pro", "free", "unknown"},
    "codex": {
        "plus", "pro", "pro_5x", "pro_20x", "business", "enterprise", "unknown",
    },
    "gemini": {
        "code_assist_individuals", "code_assist_standard", "code_assist_enterprise",
        "ai_studio_api", "ai_pro", "ai_ultra", "unknown",
    },
    "grok": {
        "absent", "premium", "premium_plus", "supergrok", "supergrok_heavy",
        "api", "cli_installed", "unknown",
    },
}

KNOWN_WINDOWS = {"rolling_2h", "rolling_5h", "rolling_24h", "rolling_7d"}

KNOWN_UNITS = {
    "percent_of_plan",
    "tokens_local_proxy",
    "weighted_tokens_local_proxy",
    "requests",
    "messages_estimate",
}

CODEX_PROVISIONAL_CAP = 1_000_000_000  # 1B tokens — used when no live sample available

CLAUDE_UNCALIBRATED_NOTE = (
    "F006 must skip this window when "
    "vendors.claude.windows.<w>.calibration.confidence == 'uncalibrated' "
    "(see F005 calibrate-claude). Otherwise observed weighted_tokens / 100 "
    "false-trips immediately."
)


class QuotaCapsError(Exception):
    """Raised by load/validate when the caps file is malformed."""


def starter_caps(*, codex_observed_5h: int | None = None) -> dict[str, Any]:
    """Compose a starter caps file dict.

    For Codex, derive cap from current observed rolling_5h * 1.25 if a sample
    is provided; else use a high provisional value (1B tokens) with a note.
    Operator re-runs `quota-caps init` (or edits directly) to refresh.
    """
    if codex_observed_5h is not None and codex_observed_5h > 0:
        codex_cap = math.ceil(codex_observed_5h * 1.25)
        codex_note = (
            f"derived from observed rolling_5h ({codex_observed_5h}) * 1.25 at init; "
            "re-run `quota-caps init` to refresh"
        )
    else:
        codex_cap = CODEX_PROVISIONAL_CAP
        codex_note = (
            f"high provisional ({CODEX_PROVISIONAL_CAP}); tune to ~1.25x observed "
            "rolling_5h or re-run `quota-caps init` after some Codex usage exists"
        )

    return {
        "schema_version": CAPS_SCHEMA_VERSION,
        "defaults": {"claude_tier": "max_20x"},
        "claude": {
            "max_20x": {
                "rolling_7d": {
                    "cap": 100,
                    "unit": "percent_of_plan",
                    "_note": CLAUDE_UNCALIBRATED_NOTE,
                },
                "rolling_5h": {
                    "cap": 100,
                    "unit": "percent_of_plan",
                    "_note": CLAUDE_UNCALIBRATED_NOTE,
                },
            },
        },
        "codex": {
            "plus": {
                "rolling_5h": {
                    "cap": codex_cap,
                    "unit": "tokens_local_proxy",
                    "_note": codex_note,
                },
            },
        },
        "gemini": {
            "code_assist_individuals": {
                "rolling_24h": {
                    "cap": 1000,
                    "unit": "requests",
                    "_note": "Google Code Assist Individuals daily request cap",
                },
            },
        },
        "grok": {},
    }


def validate(data: Any) -> list[str]:
    """Return list of error messages; empty list = valid.

    Rejects unknown vendor / tier / window / unit keys. Permits arbitrary
    fields with leading underscore (e.g. `_note`) so operators can comment
    inline without breaking the loader.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["caps file must be a JSON object"]
    if data.get("schema_version") != CAPS_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {CAPS_SCHEMA_VERSION}, "
            f"got {data.get('schema_version')!r}"
        )

    defaults = data.get("defaults")
    if defaults is not None and not isinstance(defaults, dict):
        errors.append("defaults must be an object if present")

    for vendor, vblock in data.items():
        if vendor in {"schema_version", "defaults"} or vendor.startswith("_"):
            continue
        if vendor not in KNOWN_VENDORS:
            errors.append(f"unknown vendor key: {vendor!r}")
            continue
        if not isinstance(vblock, dict):
            errors.append(f"{vendor} block must be an object")
            continue
        for tier, tblock in vblock.items():
            if tier.startswith("_"):
                continue
            if tier not in KNOWN_TIERS.get(vendor, set()):
                errors.append(f"unknown tier {tier!r} under vendor {vendor!r}")
                continue
            if not isinstance(tblock, dict):
                errors.append(f"{vendor}.{tier} must be an object")
                continue
            for window, wblock in tblock.items():
                if window.startswith("_"):
                    continue
                if window not in KNOWN_WINDOWS:
                    errors.append(
                        f"unknown window {window!r} under {vendor}.{tier}"
                    )
                    continue
                if not isinstance(wblock, dict):
                    errors.append(f"{vendor}.{tier}.{window} must be an object")
                    continue
                cap = wblock.get("cap")
                unit = wblock.get("unit")
                if not isinstance(cap, (int, float)) or isinstance(cap, bool) or cap < 0:
                    errors.append(
                        f"{vendor}.{tier}.{window}.cap must be non-negative number, "
                        f"got {cap!r}"
                    )
                if not isinstance(unit, str) or unit not in KNOWN_UNITS:
                    errors.append(
                        f"{vendor}.{tier}.{window}.unit must be one of "
                        f"{sorted(KNOWN_UNITS)}, got {unit!r}"
                    )
    return errors


def load(path: Path | None = None) -> dict[str, Any]:
    """Read + validate caps file. Raises QuotaCapsError on any issue."""
    p = _effective_caps_path(path)
    if not p.is_file():
        raise QuotaCapsError(
            f"caps file not found at {p}; "
            "run `python -m jarvis_orchestrate quota-caps init`"
        )
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise QuotaCapsError(f"failed to read caps file at {p}: {exc}") from exc
    errors = validate(data)
    if errors:
        raise QuotaCapsError(
            f"caps file at {p} invalid:\n  " + "\n  ".join(errors)
        )
    return data


def get(
    data: dict[str, Any], vendor: str, tier: str, window: str
) -> dict[str, Any] | None:
    """Return the {cap, unit, ...} block for vendor.tier.window, or None."""
    vblock = data.get(vendor)
    if not isinstance(vblock, dict):
        return None
    tblock = vblock.get(tier)
    if not isinstance(tblock, dict):
        return None
    wblock = tblock.get(window)
    if not isinstance(wblock, dict):
        return None
    return wblock


def init_starter_file(
    path: Path | None = None,
    *,
    codex_observed_5h: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write starter caps file. Returns the data written.

    Refuses to overwrite an existing file unless overwrite=True. Caller is
    responsible for sampling codex usage (keeps loader decoupled from
    quota_check).
    """
    p = path or CAPS_FILE
    if p.is_file() and not overwrite:
        raise QuotaCapsError(
            f"caps file already exists at {p}; pass overwrite=True or delete first"
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    data = starter_caps(codex_observed_5h=codex_observed_5h)
    p.write_text(json.dumps(data, indent=2) + "\n")
    return data


def show(
    data: dict[str, Any] | None = None,
    *,
    path: Path | None = None,
) -> str:
    """Return human-readable summary of effective caps."""
    p = path or CAPS_FILE
    if data is None:
        data = load(p)
    lines: list[str] = []
    lines.append(f"caps file: {p}")
    lines.append(f"schema_version: {data.get('schema_version')}")
    defaults = data.get("defaults") or {}
    if defaults:
        lines.append(f"defaults: {dict(defaults)}")
    for vendor in sorted(KNOWN_VENDORS):
        vblock = data.get(vendor) or {}
        if not vblock:
            lines.append(f"  {vendor:<8} (no caps configured)")
            continue
        for tier, tblock in sorted(vblock.items()):
            if tier.startswith("_") or not isinstance(tblock, dict):
                continue
            for window, wblock in sorted(tblock.items()):
                if window.startswith("_") or not isinstance(wblock, dict):
                    continue
                cap = wblock.get("cap")
                unit = wblock.get("unit")
                note = wblock.get("_note")
                line = (
                    f"  {vendor:<8} {tier:<24} {window:<11} "
                    f"cap={cap} unit={unit}"
                )
                if note:
                    line += f"\n            # {note}"
                lines.append(line)
    return "\n".join(lines)
