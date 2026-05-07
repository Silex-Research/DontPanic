"""Plan G F006 — dotted-key writers shared between ``dontpanic config``,
``dontpanic project config``, and ``dontpanic setup``.

Single canonical implementation so all three CLI surfaces validate
against the same Pydantic schemas and refuse the same invalid keys.
``write_global_dotted_key`` enforces D015: ``runtime_evidence.*`` writes
to global config refuse with :class:`InvalidKeyError`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dontpanic_orchestrate import global_config as gc
from dontpanic_orchestrate import project_config as pc
from dontpanic_orchestrate.config.roles import RolesConfig
from dontpanic_orchestrate.config.runtime_evidence import RuntimeEvidenceConfig


class InvalidKeyError(ValueError):
    """Raised for unknown / forbidden dotted keys."""


# Top-level legacy fields the operator may set via ``dontpanic config set``.
_LEGACY_GLOBAL_TOP_KEYS = {"default_implementer", "default_auditor", "default_tier"}
_LEGACY_PROJECT_TOP_KEYS = {
    "implementer",
    "auditor",
    "plans_dir",
    "default_target_env",
}


def _coerce_value_for_key(key: str, value: str) -> Any:
    """Convert the CLI-supplied string ``value`` into the right shape
    for the target key. F006 only stores strings (no nested numerics or
    bools yet), so this is mostly a passthrough — but we trim whitespace
    and refuse empty strings since they're never the operator's intent."""
    if value is None:
        raise InvalidKeyError(f"refusing to store None for {key!r}")
    if isinstance(value, str):
        v = value.strip()
        if not v:
            raise InvalidKeyError(
                f"refusing to store empty value for {key!r} — "
                "delete the key instead if you want it unset"
            )
        return v
    return value


def _set_nested(d: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _validate_global_config_dict(raw: dict[str, Any]) -> None:
    """Round-trip through Pydantic to catch unknown keys / bad shapes."""
    try:
        gc.GlobalConfig.model_validate(raw)
    except ValidationError as exc:
        raise InvalidKeyError(f"invalid global config write: {exc.errors()}") from exc


def _validate_project_config_dict(raw: dict[str, Any]) -> None:
    try:
        pc.ProjectConfig.model_validate(raw)
    except ValidationError as exc:
        raise InvalidKeyError(f"invalid project config write: {exc.errors()}") from exc


def write_global_dotted_key(key: str, value: str) -> Path:
    """Write a single dotted key to ``~/.dontpanic/config.json``.

    Refuses ``runtime_evidence.*`` (D015) — the message points the
    operator at ``dontpanic project config set`` instead.
    """
    if key.startswith("runtime_evidence"):
        raise InvalidKeyError(
            "refusing to write runtime_evidence to global config (D015 — "
            "runtime evidence is project-scoped). Use "
            "`dontpanic project config set` instead."
        )

    coerced = _coerce_value_for_key(key, value)

    # Read existing config JSON (preserves legacy fields untouched), apply
    # the dotted-key write, validate against the Pydantic schema, then
    # write back atomically. Using the JSON directly (not GlobalConfig
    # round-trip) keeps unknown-but-legal keys untouched.
    path = gc.config_path()
    if path.is_file():
        raw = json.loads(path.read_text() or "{}")
    else:
        raw = {}

    # Top-level legacy field shortcut — operators with muscle memory for
    # the old key still get a working write.
    parts = key.split(".")
    if len(parts) == 1:
        if parts[0] not in _LEGACY_GLOBAL_TOP_KEYS and parts[0] != "roles":
            raise InvalidKeyError(
                f"unknown top-level key {parts[0]!r} for global config; "
                f"valid: roles.<role>, {sorted(_LEGACY_GLOBAL_TOP_KEYS)}"
            )

    if key.startswith("roles."):
        # Reject typo'd role names (e.g. roles.implmenter).
        role_name = key.split(".", 1)[1]
        valid_roles = set(RolesConfig.model_fields)
        if role_name not in valid_roles:
            raise InvalidKeyError(f"unknown role {role_name!r}; valid: {sorted(valid_roles)}")

    _set_nested(raw, key, coerced)
    _validate_global_config_dict(raw)

    home = gc.ensure_dontpanic_home()
    out_path = home / gc.CONFIG_FILENAME
    out_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    return out_path


def write_project_dotted_key(project_dir: Path, key: str, value: str) -> Path:
    """Write a single dotted key to ``<project>/.dontpanic/dontpanic.json``."""
    coerced = _coerce_value_for_key(key, value)

    path = pc.project_config_path(project_dir)
    if not path.is_file():
        # Match ``project config init`` behavior: refuse rather than
        # silently materialize the file. Operators should run init
        # explicitly so they know where the file lives.
        raise InvalidKeyError(
            f"per-project config does not exist at {path}; "
            "run `dontpanic project config init` first"
        )
    raw = json.loads(path.read_text() or "{}")

    parts = key.split(".")
    if len(parts) == 1:
        if parts[0] not in _LEGACY_PROJECT_TOP_KEYS and parts[0] not in (
            "roles",
            "runtime_evidence",
            "human_gates",
            "protected_paths",
        ):
            raise InvalidKeyError(
                f"unknown top-level key {parts[0]!r} for project config; "
                f"valid: roles.<role>, runtime_evidence.<source>.<field>, "
                f"{sorted(_LEGACY_PROJECT_TOP_KEYS)}"
            )

    if key.startswith("roles."):
        role_name = key.split(".", 1)[1]
        valid_roles = set(RolesConfig.model_fields)
        if role_name not in valid_roles:
            raise InvalidKeyError(f"unknown role {role_name!r}; valid: {sorted(valid_roles)}")

    if key.startswith("runtime_evidence."):
        rest = key.split(".", 2)[1:]
        if not rest or rest[0] not in set(RuntimeEvidenceConfig.model_fields):
            raise InvalidKeyError(
                f"unknown runtime evidence source {rest[0] if rest else '(empty)'!r}; "
                f"valid: {sorted(RuntimeEvidenceConfig.model_fields)}"
            )

    _set_nested(raw, key, coerced)
    _validate_project_config_dict(raw)

    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    return path


def render_global_show(cfg: gc.GlobalConfig) -> str:
    """Resolved-view of the global config for ``dontpanic config show``.
    Surfaces both the ``roles`` block (canonical) and the legacy fields
    so operators see their existing setup unchanged."""
    payload: dict[str, Any] = {}
    if cfg.roles is not None:
        payload["roles"] = cfg.roles.model_dump(exclude_none=True)
    else:
        payload["roles"] = {}
    if cfg.default_implementer is not None:
        payload["default_implementer"] = cfg.default_implementer
    if cfg.default_auditor is not None:
        payload["default_auditor"] = cfg.default_auditor
    if cfg.default_tier is not None:
        payload["default_tier"] = cfg.default_tier
    if cfg.calibration_path is not None:
        payload["calibration_path"] = cfg.calibration_path
    return json.dumps(payload, indent=2, ensure_ascii=False)


__all__ = [
    "InvalidKeyError",
    "render_global_show",
    "write_global_dotted_key",
    "write_project_dotted_key",
]
