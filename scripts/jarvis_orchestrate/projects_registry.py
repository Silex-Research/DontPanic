"""Plan 2026-05-03-001 F002 — project registry at ``~/.jarvis/projects.json``.

The registry is the single source of truth for "which projects can Jarvis
operate against". F002 is intentionally CRUD-only: no supervisor wiring,
no per-project config consumption (F003 lands those). Operators (or
agents shelling out via ``--json``) call ``jarvis projects add | list |
show | remove`` and the registry's on-disk shape is what F003's lookup
chain will consult at dispatch time.

Storage path obeys ``$JARVIS_HOME`` (test isolation + power-user use)
via :mod:`jarvis_orchestrate.global_config`. Schema is Pydantic v2 with
``extra='forbid'`` so a stale config from an older Jarvis cannot
silently break a newer one — invalid files degrade to empty + WARN.

Project name regex per D003: ``^[a-z0-9][a-z0-9-]{0,63}$`` — DNS-label
shape, no underscores, ≤64 chars. Path is normalized at add time
(``Path.expanduser().resolve()``); a non-directory path refuses with a
clear error before anything lands on disk.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from jarvis_orchestrate import global_config as gc

_LOG = logging.getLogger(__name__)

REGISTRY_FILENAME = "projects.json"

# D003: lowercase, hyphen-separated, no underscores, no leading hyphen,
# max 64 chars. Same shape as DNS labels and most package conventions.
PROJECT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class ProjectsRegistryError(ValueError):
    """Raised by registry helpers for caller-visible failures (collision,
    invalid name, non-existent path, unknown name on update). The CLI maps
    this to exit 2 with the message printed to stderr."""


class ProjectEntry(BaseModel):
    """One registered project. ``name`` is the primary key; ``path`` is
    stored absolute (caller can pass ``~/...`` and it is normalized at
    add time). Optional fields are persisted only when set
    (:func:`save_registry` uses ``exclude_none``)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    created_at: str
    last_used_at: str | None = None
    default_implementer: str | None = None
    default_auditor: str | None = None
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not PROJECT_NAME_PATTERN.fullmatch(v):
            raise ValueError(
                f"project name {v!r} does not match {PROJECT_NAME_PATTERN.pattern} "
                "(lowercase letters, digits, hyphens; no leading hyphen; max 64 chars)"
            )
        return v


class Registry(BaseModel):
    """Wrapper for the on-disk ``projects.json`` shape:
    ``{"projects": [ProjectEntry, ...]}``."""

    model_config = ConfigDict(extra="forbid")

    projects: list[ProjectEntry] = []


def registry_path() -> Path:
    """Path to ``projects.json`` under :func:`gc.jarvis_home`."""
    return gc.jarvis_home() / REGISTRY_FILENAME


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp at second precision. Whole seconds keep the
    on-disk file diff-friendly when operators inspect it."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_registry() -> Registry:
    """Load the registry. Total: missing file → empty (zero state); invalid
    JSON / unreadable / schema-violating → WARN + empty. Never raises."""
    path = registry_path()
    if not path.is_file():
        return Registry()
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning(
            "projects registry at %s is unreadable or invalid JSON (%s); "
            "using empty registry",
            path,
            exc,
        )
        return Registry()
    try:
        return Registry.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError or similar
        _LOG.warning(
            "projects registry at %s failed schema validation (%s); "
            "using empty registry",
            path,
            exc,
        )
        return Registry()


def save_registry(reg: Registry) -> Path:
    """Persist the registry to ``projects.json``. Creates ``$JARVIS_HOME``
    if missing. Returns the written path."""
    home = gc.ensure_jarvis_home()
    path = home / REGISTRY_FILENAME
    path.write_text(
        json.dumps(
            reg.model_dump(exclude_none=True),
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    return path


def _normalize_path(path: str) -> Path:
    """Expand ``~`` and resolve to absolute. Returned Path is what lands
    in the registry — operators can pass relative or ``~/...`` and the
    registry stores absolute, no-symlinks-by-luck."""
    return Path(path).expanduser().resolve()


def add_project(
    name: str,
    path: str,
    *,
    force: bool = False,
    default_implementer: str | None = None,
    default_auditor: str | None = None,
    notes: str | None = None,
) -> ProjectEntry:
    """Register a project. Refuses on collision unless ``force=True``;
    refuses on non-existent path; refuses on bad-shape name (Pydantic
    validator). Returns the persisted entry."""
    abs_path = _normalize_path(path)
    if not abs_path.is_dir():
        raise ProjectsRegistryError(
            f"path does not exist or is not a directory: {abs_path}"
        )

    try:
        # Validate name + build entry shape up front so collisions don't
        # short-circuit name validation — same exit-2 path either way.
        new_entry = ProjectEntry(
            name=name,
            path=str(abs_path),
            created_at=_utcnow_iso(),
            default_implementer=default_implementer,
            default_auditor=default_auditor,
            notes=notes,
        )
    except Exception as exc:
        raise ProjectsRegistryError(str(exc)) from exc

    reg = load_registry()
    existing_idx = next(
        (i for i, p in enumerate(reg.projects) if p.name == name), None
    )
    if existing_idx is not None and not force:
        raise ProjectsRegistryError(
            f"project {name!r} already registered at "
            f"{reg.projects[existing_idx].path!r}; pass --force --yes to overwrite"
        )

    if existing_idx is not None:
        reg.projects[existing_idx] = new_entry
    else:
        reg.projects.append(new_entry)
    save_registry(reg)
    return new_entry


def remove_project(name: str) -> ProjectEntry | None:
    """Remove and return the entry, or None if no such name."""
    reg = load_registry()
    idx = next((i for i, p in enumerate(reg.projects) if p.name == name), None)
    if idx is None:
        return None
    removed = reg.projects.pop(idx)
    save_registry(reg)
    return removed


def find_project(name: str) -> ProjectEntry | None:
    """Look up by name. Returns None when missing — callers decide
    whether that warrants an error."""
    reg = load_registry()
    return next((p for p in reg.projects if p.name == name), None)


def update_last_used(name: str) -> ProjectEntry:
    """Stamp ``last_used_at`` to now (UTC). Raises
    :class:`ProjectsRegistryError` if no such name. Idempotent within the
    same second (timestamp is whole-second precision)."""
    reg = load_registry()
    for p in reg.projects:
        if p.name == name:
            p.last_used_at = _utcnow_iso()
            save_registry(reg)
            return p
    raise ProjectsRegistryError(f"unknown project name: {name!r}")


def to_public_dict(entry: ProjectEntry) -> dict[str, Any]:
    """Serialize one entry for ``--json`` output. Mirrors the on-disk
    shape (no None fields)."""
    return entry.model_dump(exclude_none=True)


__all__ = [
    "PROJECT_NAME_PATTERN",
    "ProjectEntry",
    "ProjectsRegistryError",
    "REGISTRY_FILENAME",
    "Registry",
    "add_project",
    "find_project",
    "load_registry",
    "registry_path",
    "remove_project",
    "save_registry",
    "to_public_dict",
    "update_last_used",
]
