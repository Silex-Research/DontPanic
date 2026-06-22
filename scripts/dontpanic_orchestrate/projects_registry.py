"""Project registry at ``~/.dontpanic/projects.json``.

The registry is the single source of truth for "which projects can
DontPanic operate against". Operators (or agents shelling out via
``--json``) call ``dontpanic projects add | list | show | remove`` and
the registry's on-disk shape is what the lookup chain consults at
dispatch time.

Storage path obeys ``$DONTPANIC_HOME`` first, then legacy
``$JARVIS_HOME`` / ``~/.jarvis`` fallback via
:mod:`dontpanic_orchestrate.global_config`. Schema is Pydantic v2 with
``extra='forbid'`` so a stale config from an older DontPanic cannot
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

from dontpanic_orchestrate import global_config as gc

_LOG = logging.getLogger(__name__)

REGISTRY_FILENAME = "projects.json"

# D003: lowercase, hyphen-separated, no underscores, no leading hyphen,
# max 64 chars. Same shape as DNS labels and most package conventions.
PROJECT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class ProjectsRegistryError(ValueError):
    """Raised by registry helpers for caller-visible failures (collision,
    invalid name, non-existent path, unknown name on update). The CLI maps
    this to exit 2 with the message printed to stderr."""


class RegistryUnreadableError(Exception):
    """Raised by :func:`load_registry_strict` when the registry file is PRESENT
    but UNDETERMINABLE — unreadable, invalid JSON, or schema-violating. A
    *missing* file is NOT undeterminable (it is the clean zero state) and never
    raises. Deliberately NOT a :class:`ProjectsRegistryError` so it does not
    inherit the CLI's exit-2 semantics: it is a degradation signal for read-only
    consumers (e.g. the F003 upgrade predicates) that must distinguish a
    genuinely empty registry from one they could not parse."""


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
    # 2026-05-23-005 F001 — additive dashboard-selector fields. All
    # optional so legacy registry files (no dashboard fields) keep loading
    # unchanged; missing values default to None / True (for ``active``).
    display_name: str | None = None
    """Human-friendly label for the dashboard project selector. Defaults
    to ``name`` at projection time when unset (see
    :func:`projects_dashboard.project_context_from_entry`)."""

    profile: str | None = None
    """Free-form operator label (``mobile``, ``backend``, ``schema``, …).
    Surfaced in the fleet summary so the selector can group / filter; not
    interpreted by the supervisor."""

    active: bool | None = None
    """Whether this project participates in fleet builds. ``None`` means
    "field absent" (legacy) and projects without the flag are treated as
    active. The selector hides inactive projects from "All Projects"
    rollups but they remain registered so the operator can re-enable
    them without re-adding."""

    dontpanic_version: str | None = None
    """The DontPanic install version that last operated this project.
    V0 assumes one install operates every registered project (see plan
    §Schema Assumptions); the field is recorded for forward-compat with
    a future cross-version selector but the V0 dashboard treats every
    registered project as same-version."""

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
    """Path to ``projects.json`` under :func:`gc.dontpanic_home`."""
    return gc.dontpanic_home() / REGISTRY_FILENAME


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp at second precision. Whole seconds keep the
    on-disk file diff-friendly when operators inspect it."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_registry_strict() -> Registry:
    """Load the registry, distinguishing zero-state from undeterminable.

    A *missing* file is the clean zero state and returns an empty
    :class:`Registry`. A file that is PRESENT but unreadable / invalid JSON /
    schema-violating raises :class:`RegistryUnreadableError` rather than silently
    degrading to empty — so a read-only consumer can fail OPEN on an
    undeterminable registry instead of mistaking it for "no tracked projects"."""
    path = registry_path()
    if not path.is_file():
        return Registry()
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryUnreadableError(
            f"projects registry at {path} is unreadable or invalid JSON: {exc}"
        ) from exc
    try:
        return Registry.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError or similar
        raise RegistryUnreadableError(
            f"projects registry at {path} failed schema validation: {exc}"
        ) from exc


def load_registry() -> Registry:
    """Load the registry. Total: missing file → empty (zero state); invalid
    JSON / unreadable / schema-violating → WARN + empty. Never raises.

    Lenient wrapper over :func:`load_registry_strict` for callers that want the
    historic warn-and-empty contract; read-only consumers that must tell zero
    state apart from an undeterminable file should call the strict variant."""
    try:
        return load_registry_strict()
    except RegistryUnreadableError as exc:
        _LOG.warning("%s; using empty registry", exc)
        return Registry()


def save_registry(reg: Registry) -> Path:
    """Persist the registry to ``projects.json``. Creates the resolved
    DontPanic home if missing. Returns the written path."""
    home = gc.ensure_dontpanic_home()
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
    display_name: str | None = None,
    profile: str | None = None,
    active: bool | None = None,
    dontpanic_version: str | None = None,
) -> ProjectEntry:
    """Register a project. Refuses on collision unless ``force=True``;
    refuses on non-existent path; refuses on bad-shape name (Pydantic
    validator). Returns the persisted entry."""
    abs_path = _normalize_path(path)
    if not abs_path.is_dir():
        raise ProjectsRegistryError(f"path does not exist or is not a directory: {abs_path}")

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
            display_name=display_name,
            profile=profile,
            active=active,
            dontpanic_version=dontpanic_version,
        )
    except Exception as exc:
        raise ProjectsRegistryError(str(exc)) from exc

    reg = load_registry()
    existing_idx = next((i for i, p in enumerate(reg.projects) if p.name == name), None)
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
    "RegistryUnreadableError",
    "add_project",
    "find_project",
    "load_registry",
    "load_registry_strict",
    "registry_path",
    "remove_project",
    "save_registry",
    "to_public_dict",
    "update_last_used",
]
