"""Plan 2026-06-14-001 F004 — operator-role PREFERENCES config layer.

SAFETY INVARIANT (D009): operator_roles.* are PREFERENCE / INTENT ONLY — they
carry NO worker-dispatch authority. This module NEVER calls
:func:`agent_surface.assert_registrable` and NEVER refuses a non-executor
surface value. A surface like ``cursor`` (no executor) is a perfectly valid
operator-role value.

Operator roles are DISTINCT from worker roles (``implementer`` / ``auditor`` /
``goal_auditor`` in :mod:`agent_surface`). The namespaces are separate:

  - Worker roles  → written under ``roles.*`` in ``config.json`` / ``dontpanic.json``
  - Operator roles → written under ``operator_roles.*`` in **separate** files
                     ``operator_roles.json`` (global and project-scoped).

Value domain (D015): an operator-role VALUE is the union of:
  - any ``agent_runtime`` canonical id (claude, codex, gemini, grok, ...)
  - any ``operator_surface`` canonical id (cursor, antigravity, codex_app, ...)
  - the literal ``"human"``
  - ``"unknown_role"`` (the fallback for unrecognized values)

Resolution precedence (D013): project scope > global scope. A resolved entry
carries a ``scope`` provenance field ("global" | "project").

Storage:
  - Global: ``<dontpanic_home()>/operator_roles.json``
  - Project: ``<project>/.dontpanic/operator_roles.json``

Both paths are redirectable by ``$DONTPANIC_HOME`` (global) and the project path
(project), so tests never touch the user's real home directory.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Literal

from dontpanic_orchestrate import global_config as gc
from dontpanic_orchestrate.invocation_context import (
    UNKNOWN_ROLE,
    normalize_identifier,
)

_LOG = logging.getLogger(__name__)

# ──────────────────────────────  constants  ──────────────────────────────

OPERATOR_ROLES_FILENAME = "operator_roles.json"
"""Filename for the operator-role preferences file at both global and project scope."""

PROJECT_CONFIG_DIRNAME = ".dontpanic"
"""Preferred directory under a project root for per-project config files."""

#: Canonical operator-role KEY set (F004 acceptance #2).
#: These are the role names an operator can assign preferences to.
#: They are DISTINCT from the worker :data:`agent_surface.ROLES`
#: (implementer / auditor / goal_auditor).
#: ``auditor`` is included intentionally (intent: "Codex reviews my work");
#: it carries NO dispatch authority — D009 safety invariant.
OPERATOR_ROLES: tuple[str, ...] = (
    "primary_operator",
    "auditor",
    "researcher",
    "reviewer",
    "designer",
    "tester",
    "release_operator",
)

Scope = Literal["global", "project"]

# ──────────────────────────────  value normalisation (pure)  ──────────────────────────────

_HUMAN_ALIASES: frozenset[str] = frozenset({"human", "Human", "HUMAN"})


def normalize_operator_role_value(value: str) -> str:
    """Map ``value`` to a canonical operator-role VALUE id (D015).

    Resolution order:
      1. ``human`` / aliases → ``"human"``
      2. ``agent_runtime`` normalisation via :func:`invocation_context.normalize_identifier` —
         if the result is not ``unknown_runtime``, use it.
      3. ``operator_surface`` normalisation — if the result is not ``unknown_surface``,
         use it.
      4. ``"unknown_role"`` (the fallback; NEVER an invented id).

    Pure: no I/O, no mutation. Empty / whitespace-only → ``"unknown_role"``.
    """
    if not value or not value.strip():
        return UNKNOWN_ROLE

    stripped = value.strip()

    # 1. human aliases
    if stripped in _HUMAN_ALIASES or stripped.lower() == "human":
        return "human"

    # 2. try agent_runtime
    runtime_id = normalize_identifier(stripped, "agent_runtime")
    if runtime_id != "unknown_runtime":
        return runtime_id

    # 3. try operator_surface
    surface_id = normalize_identifier(stripped, "operator_surface")
    if surface_id != "unknown_surface":
        return surface_id

    # 4. fallback
    return UNKNOWN_ROLE


# ──────────────────────────────  storage paths  ──────────────────────────────


def _global_operator_roles_path() -> Path:
    """Path to the global operator-roles file: ``<dontpanic_home>/operator_roles.json``."""
    return gc.dontpanic_home() / OPERATOR_ROLES_FILENAME


def _project_operator_roles_path(project_path: Path) -> Path:
    """Path to the per-project operator-roles file:
    ``<project>/.dontpanic/operator_roles.json``."""
    return project_path / PROJECT_CONFIG_DIRNAME / OPERATOR_ROLES_FILENAME


# ──────────────────────────────  raw config I/O  ──────────────────────────────


def _read_raw(path: Path) -> dict[str, str]:
    """Read operator-roles JSON from ``path``.

    Returns an empty dict when:
      - the file is absent (valid zero state), or
      - the file is unreadable / invalid JSON (LOG WARN; degrade gracefully).
    Never raises.
    """
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            _LOG.warning(
                "operator_roles file at %s is not a JSON object; treating as empty",
                path,
            )
            return {}
        return {k: str(v) for k, v in raw.items()}
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning(
            "operator_roles file at %s is unreadable or invalid JSON (%s); treating as empty",
            path,
            exc,
        )
        return {}


def _write_raw(path: Path, data: dict[str, str]) -> None:
    """Write ``data`` to ``path`` as JSON. Creates parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ──────────────────────────────  public API  ──────────────────────────────


class OperatorRoleError(ValueError):
    """Base class for operator-role domain errors."""


class UnknownOperatorRole(OperatorRoleError):
    """Raised when a caller sets an unrecognised role KEY."""


def set_operator_role(
    role: str,
    value: str,
    *,
    scope: Scope,
    project_path: Path | None = None,
) -> None:
    """Set the operator preference for ``role`` to ``value`` at ``scope``.

    Args:
        role:         An operator-role KEY (e.g. ``"primary_operator"``).
                      Does NOT have to be in :data:`OPERATOR_ROLES`; unknown
                      keys are accepted with a WARN so future role additions
                      don't hard-break older configs.
        value:        Any string; normalised via
                      :func:`normalize_operator_role_value` before storage.
        scope:        ``"global"`` or ``"project"``.
        project_path: Required when ``scope="project"``; the project root.

    Raises:
        ValueError: when ``scope="project"`` and ``project_path`` is ``None``.

    SAFETY INVARIANT (D009): this function NEVER calls
    ``agent_surface.assert_registrable`` and NEVER refuses a non-executor
    surface. ``cursor``, ``antigravity``, ``claude_desktop`` are all valid.
    """
    if scope not in ("global", "project"):
        raise OperatorRoleError(f"scope must be 'global' or 'project', got {scope!r}")
    if scope == "project" and project_path is None:
        raise OperatorRoleError("project_path is required when scope='project'")

    if role not in OPERATOR_ROLES:
        _LOG.warning(
            "operator role key %r is not in OPERATOR_ROLES; writing anyway", role
        )

    canonical_value = normalize_operator_role_value(value)

    if scope == "global":
        path = _global_operator_roles_path()
        # Ensure the home dir exists before writing
        gc.ensure_dontpanic_home()
    else:
        if project_path is None:  # pragma: no cover — guard raised above
            raise OperatorRoleError("project_path is required when scope='project'")
        path = _project_operator_roles_path(project_path)

    data = _read_raw(path)
    data[role] = canonical_value
    _write_raw(path, data)


def list_operator_roles(
    project_path: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Return the resolved operator-role map with per-entry scope provenance.

    Resolution: project scope overrides global scope (D013). Each entry is:
      ``{"value": <canonical_id>, "scope": "global" | "project"}``

    Args:
        project_path: When provided, per-project values override global ones.

    Returns:
        A dict keyed by role name; values are ``{"value": ..., "scope": ...}``.
        Roles not set in either scope are absent from the result.
    """
    global_data = _read_raw(_global_operator_roles_path())

    project_data: dict[str, str] = {}
    if project_path is not None:
        project_data = _read_raw(_project_operator_roles_path(project_path))

    resolved: dict[str, dict[str, str]] = {}

    # Collect all role keys from both scopes
    all_roles = set(global_data.keys()) | set(project_data.keys())
    for role_key in all_roles:
        if role_key in project_data:
            resolved[role_key] = {
                "value": project_data[role_key],
                "scope": "project",
            }
        else:
            resolved[role_key] = {
                "value": global_data[role_key],
                "scope": "global",
            }

    return resolved


# ──────────────────────────────  CLI surface (for future cli.py wiring)  ──────────────────────────────


def add_operator_roles_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``operator-roles`` subparser on the parent ``subparsers``
    object. The parent CLI (``cli.py``) can call this to wire the command;
    this module does NOT import or modify ``cli.py``.

    Subcommands:
      - ``operator-roles set <role> <value> [--scope global|project] [--project PATH]``
      - ``operator-roles list [--project PATH]``
    """
    op_roles_parser = subparsers.add_parser(
        "operator-roles",
        help="Manage operator-role preference assignments (intent only; not dispatch authority).",
    )
    op_subparsers = op_roles_parser.add_subparsers(dest="or_action")

    # set subcommand
    set_parser = op_subparsers.add_parser("set", help="Set an operator-role preference.")
    set_parser.add_argument("role", help="Operator-role key (e.g. primary_operator).")
    set_parser.add_argument("value", help="Agent / surface / human value.")
    set_parser.add_argument(
        "--scope",
        choices=["global", "project"],
        default="global",
        help="Config scope (default: global).",
    )
    set_parser.add_argument(
        "--project",
        dest="project_path",
        default=None,
        help="Project root path (required when --scope=project).",
    )

    # list subcommand
    list_parser = op_subparsers.add_parser(
        "list", help="List resolved operator-role preferences with provenance."
    )
    list_parser.add_argument(
        "--project",
        dest="project_path",
        default=None,
        help="Project root path (adds project-scope overrides).",
    )


def run_operator_roles_command(
    args: argparse.Namespace,
) -> dict[str, dict[str, str]] | None:
    """Dispatch an :class:`argparse.Namespace` parsed by the ``operator-roles``
    subcommand to the appropriate implementation.

    Returns the resolved map from :func:`list_operator_roles` when the action
    is ``list``; returns ``None`` for ``set`` (side-effect only). The parent
    CLI can print/format the returned dict however it prefers.
    """
    action = getattr(args, "or_action", None)

    if action == "set":
        project_path = (
            Path(args.project_path) if getattr(args, "project_path", None) else None
        )
        scope: Scope = getattr(args, "scope", "global")
        set_operator_role(
            args.role,
            args.value,
            scope=scope,
            project_path=project_path,
        )
        return None

    if action == "list":
        project_path = (
            Path(args.project_path) if getattr(args, "project_path", None) else None
        )
        return list_operator_roles(project_path=project_path)

    return None


# ──────────────────────────────  __all__  ──────────────────────────────

__all__ = [
    "OPERATOR_ROLES",
    "OPERATOR_ROLES_FILENAME",
    "PROJECT_CONFIG_DIRNAME",
    "OperatorRoleError",
    "Scope",
    "UnknownOperatorRole",
    "add_operator_roles_subparser",
    "list_operator_roles",
    "normalize_operator_role_value",
    "run_operator_roles_command",
    "set_operator_role",
]
