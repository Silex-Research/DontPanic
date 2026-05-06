"""Global config at ``~/.dontpanic/config.json``.

Loaded lazily by the CLI; missing file is OK (returns empty defaults).
Invalid JSON logs a WARNING and returns empty defaults so the CLI still
starts. The path can be overridden by the ``DONTPANIC_HOME`` environment
variable. The legacy ``JARVIS_HOME`` environment variable and ``~/.jarvis``
directory remain read/write-compatible during the staged rename.

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

from dontpanic_orchestrate.config.roles import RolesConfig

_LOG = logging.getLogger(__name__)

DONTPANIC_HOME_ENV = "DONTPANIC_HOME"
"""Preferred test / power-user override for the per-user state directory."""

JARVIS_HOME_ENV = "JARVIS_HOME"
"""Legacy override. Still honored as a fallback for existing installs."""

DEFAULT_DIRNAME = ".dontpanic"
"""Preferred directory under ``$HOME`` that holds per-user state."""

LEGACY_DIRNAME = ".jarvis"
"""Legacy per-user state directory, read-compatible during migration."""

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
    ``~/.dontpanic/quota_calibration.json``). When None, the supervisor
    uses the default location."""

    roles: RolesConfig | None = None
    """Plan G F006 / D013 — agent role names by capability
    (``implementer`` / ``auditor`` / ``goal_auditor``). Canonical write
    target for ``dontpanic config set roles.<role> <agent>``. Layered
    with the legacy ``default_implementer`` / ``default_auditor`` fields
    by :func:`config.resolvers.resolve_role`. D015: this Pydantic model
    intentionally has NO ``runtime_evidence`` field — runtime evidence
    is project-scoped only."""


def dontpanic_home() -> Path:
    """Resolve the per-user state directory.

    Precedence:
      1. ``$DONTPANIC_HOME`` if set.
      2. ``$JARVIS_HOME`` if set (legacy compatibility).
      3. ``~/.dontpanic`` if it already exists.
      4. ``~/.jarvis`` if it already exists (legacy compatibility).
      5. ``~/.dontpanic`` for new installs.

    Returns the path; does NOT create it. Callers that need to write
    pass through ``ensure_dontpanic_home()``.
    """
    override = os.environ.get(DONTPANIC_HOME_ENV)
    if override:
        return Path(override).expanduser()
    override = os.environ.get(JARVIS_HOME_ENV)
    if override:
        return Path(override).expanduser()
    preferred = Path.home() / DEFAULT_DIRNAME
    if preferred.exists():
        return preferred
    legacy = Path.home() / LEGACY_DIRNAME
    if legacy.exists():
        return legacy
    return preferred


def jarvis_home() -> Path:
    """Legacy alias for :func:`dontpanic_home`.

    Kept so existing callers and tests continue to work while public
    documentation moves to DontPanic naming.
    """
    return dontpanic_home()


def ensure_dontpanic_home() -> Path:
    """Resolve the per-user state directory and create it if missing.
    Used by writers (F002 registry, future surfaces)."""
    home = dontpanic_home()
    home.mkdir(parents=True, exist_ok=True)
    return home


def ensure_jarvis_home() -> Path:
    """Legacy alias for :func:`ensure_dontpanic_home`."""
    return ensure_dontpanic_home()


def config_path() -> Path:
    """Path to ``config.json`` under ``dontpanic_home()``."""
    return dontpanic_home() / CONFIG_FILENAME


def load_config() -> GlobalConfig:
    """Load the global config from ``config.json``.

    - Missing file → empty :class:`GlobalConfig` (no warning; this is the
      first-run zero state).
    - File present but unreadable / invalid JSON → log a WARNING with
      the path + reason, return empty :class:`GlobalConfig` (so the CLI
      still starts).
    - File present with extra fields → Pydantic raises
      ``ValidationError`` (``extra='forbid'``); we catch + warn + return
      empty so an outdated config doesn't break a newer DontPanic.

    Returns the populated config. Never raises.
    """
    path = config_path()
    if not path.is_file():
        return GlobalConfig()
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning(
            "global config at %s is unreadable or invalid JSON (%s); using empty defaults",
            path,
            exc,
        )
        return GlobalConfig()
    try:
        return GlobalConfig.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError or similar
        _LOG.warning(
            "global config at %s failed schema validation (%s); using empty defaults",
            path,
            exc,
        )
        return GlobalConfig()


def save_config(config: GlobalConfig) -> Path:
    """Persist the global config to ``config.json``. Creates the parent
    directory if needed. Returns the written path. Used by future
    surfaces; F001's ``jarvis`` CLI does not write the config (operators
    edit it directly with their preferred tooling)."""
    home = ensure_dontpanic_home()
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
    "DONTPANIC_HOME_ENV",
    "GlobalConfig",
    "JARVIS_HOME_ENV",
    "LEGACY_DIRNAME",
    "RolesConfig",
    "config_path",
    "dontpanic_home",
    "ensure_dontpanic_home",
    "ensure_jarvis_home",
    "jarvis_home",
    "load_config",
    "merge_with_defaults",
    "save_config",
]
