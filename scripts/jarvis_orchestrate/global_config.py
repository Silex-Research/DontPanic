"""Plan 2026-05-03-001 F001 — global config at ``~/.jarvis/config.json``.

Loaded lazily by the CLI; missing file is OK (returns empty defaults).
Invalid JSON logs a WARNING and returns empty defaults so the CLI still
starts. The path can be overridden by the ``JARVIS_HOME`` environment
variable so tests can route to a tmp dir without polluting the user's
real home directory.

Schema is intentionally minimal in F001: just the per-user defaults that
the supervisor consults at dispatch time when no per-project override
(F003) exists. Future fields land here only if they are genuinely
per-user (not per-project) — see D004 / D006 in the plan's
``decisions.jsonl`` for the precedence rule.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

_LOG = logging.getLogger(__name__)

JARVIS_HOME_ENV = "JARVIS_HOME"
"""Test / power-user override. When set, ``jarvis_home()`` returns
``Path(os.environ[JARVIS_HOME_ENV])`` instead of ``~/.jarvis``."""

DEFAULT_DIRNAME = ".jarvis"
"""Directory under ``$HOME`` (or ``$JARVIS_HOME``'s parent) that holds
all per-user state. Today: ``config.json``; future: ``projects.json``
(F002), ``audit.jsonl`` (Phase C), etc."""

CONFIG_FILENAME = "config.json"


class GlobalConfig(BaseModel):
    """Per-user defaults consumed by the supervisor at dispatch time.

    All fields are optional — the empty config is the valid zero state.
    F001 ships only the fields documented here; F003 will add per-project
    overrides that take precedence (see D004).
    """

    model_config = ConfigDict(extra="forbid")

    default_implementer: str | None = None
    """Default implementer agent name (e.g., 'claude'). When None, the
    supervisor falls back to its hardcoded default."""

    default_auditor: str | None = None
    """Default auditor agent name (e.g., 'codex'). Different vendor than
    implementer is the cross-vendor adversarial invariant."""

    default_tier: str | None = None
    """Default plan tier when authoring new plans. Not enforced at
    dispatch — the plan's own ``tier`` field always wins."""

    calibration_path: str | None = None
    """Optional pointer to a calibration file (e.g., a non-default
    ``~/.jarvis/quota_calibration.json``). When None, the supervisor
    uses the default location."""


def jarvis_home() -> Path:
    """Resolve the per-user state directory.

    Precedence:
      1. ``$JARVIS_HOME`` if set (used by tests + power users with
         non-standard layouts).
      2. ``~/.jarvis`` otherwise.

    Returns the path; does NOT create it. Callers that need to write
    pass through ``ensure_jarvis_home()``.
    """
    override = os.environ.get(JARVIS_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_DIRNAME


def ensure_jarvis_home() -> Path:
    """Resolve the per-user state directory and create it if missing.
    Used by writers (F002 registry, future surfaces)."""
    home = jarvis_home()
    home.mkdir(parents=True, exist_ok=True)
    return home


def config_path() -> Path:
    """Path to ``config.json`` under ``jarvis_home()``."""
    return jarvis_home() / CONFIG_FILENAME


def load_config() -> GlobalConfig:
    """Load the global config from ``config.json``.

    - Missing file → empty :class:`GlobalConfig` (no warning; this is the
      first-run zero state).
    - File present but unreadable / invalid JSON → log a WARNING with
      the path + reason, return empty :class:`GlobalConfig` (so the CLI
      still starts).
    - File present with extra fields → Pydantic raises
      ``ValidationError`` (``extra='forbid'``); we catch + warn + return
      empty so an outdated config doesn't break a newer Jarvis.

    Returns the populated config. Never raises.
    """
    path = config_path()
    if not path.is_file():
        return GlobalConfig()
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning(
            "global config at %s is unreadable or invalid JSON (%s); "
            "using empty defaults",
            path,
            exc,
        )
        return GlobalConfig()
    try:
        return GlobalConfig.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError or similar
        _LOG.warning(
            "global config at %s failed schema validation (%s); "
            "using empty defaults",
            path,
            exc,
        )
        return GlobalConfig()


def save_config(config: GlobalConfig) -> Path:
    """Persist the global config to ``config.json``. Creates the parent
    directory if needed. Returns the written path. Used by future
    surfaces; F001's ``jarvis`` CLI does not write the config (operators
    edit it directly with their preferred tooling)."""
    home = ensure_jarvis_home()
    path = home / CONFIG_FILENAME
    path.write_text(
        json.dumps(
            config.model_dump(exclude_none=True),
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    return path


def merge_with_defaults(
    config: GlobalConfig,
    *,
    fallback_implementer: str = "claude",
    fallback_auditor: str = "codex",
) -> dict[str, Any]:
    """Resolve effective defaults by overlaying the loaded config on
    hardcoded fallbacks. Returned dict has non-None values for every
    field the supervisor needs at dispatch time. Used by the CLI when
    no per-project override exists (per-project overrides land in F003;
    they will take precedence over this resolved layer per D004)."""
    return {
        "implementer": config.default_implementer or fallback_implementer,
        "auditor": config.default_auditor or fallback_auditor,
        "tier": config.default_tier,
        "calibration_path": config.calibration_path,
    }


__all__ = [
    "CONFIG_FILENAME",
    "DEFAULT_DIRNAME",
    "GlobalConfig",
    "JARVIS_HOME_ENV",
    "config_path",
    "ensure_jarvis_home",
    "jarvis_home",
    "load_config",
    "merge_with_defaults",
    "save_config",
]
