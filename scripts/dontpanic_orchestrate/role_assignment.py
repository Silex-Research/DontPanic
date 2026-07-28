"""Plan 2026-05-30-001 F004 — worker role assignment surface.

Low-friction path for "use Codex as auditor for this project" without
hand-editing JSON. Two responsibilities, both pure / testable:

  - **Resolve** the effective agent for each role (``implementer`` /
    ``auditor`` / ``goal_auditor``) *together with the source layer* it
    came from — project roles block, project legacy field, global roles
    block, global legacy field, the ``goal_auditor`` → resolved-auditor
    fallthrough, or the hardcoded fallback. The layered walk mirrors
    :func:`config.resolvers.resolve_role` exactly (same precedence) but
    also reports *where* each value was found so ``roles show`` and the
    dashboard can explain the resolution rather than just print a name.
  - **Project** the resolution + the available worker executors + safe
    mutation commands into a dashboard-friendly dict so a UI can render
    role pickers and the exact CLI a human/agent would run, without a
    browser mutation backend (F004 acceptance #7).

The CLI layer in :mod:`cli` parses argv, resolves the project path, and
performs config writes through the shared dotted-key writers; the
resolution + rendering + the executor guard live here so they are
unit-testable without a process. The executor guard reuses
:func:`agent_surface.assert_registrable` so the operator-vs-worker
wording is identical to ``agent register-worker`` (F004 acceptance #6).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dontpanic_orchestrate import agent_surface
from dontpanic_orchestrate import global_config as gc
from dontpanic_orchestrate import project_config as pc

# The three role slots, fixed order so rendering is byte-stable.
ROLES: tuple[str, ...] = agent_surface.ROLES

# Hardcoded fallbacks — mirror config.resolvers._FALLBACK_* / project_config.
_FALLBACK = {"implementer": pc.FALLBACK_IMPLEMENTER, "auditor": pc.FALLBACK_AUDITOR}

SourceLayer = Literal[
    "project_roles",
    "project_legacy",
    "global_roles",
    "global_legacy",
    "goal_auditor_inherits_auditor",
    "fallback",
]

# Human-readable label per source layer for ``roles show`` text output.
_SOURCE_LABELS: dict[str, str] = {
    "project_roles": "project roles block (.dontpanic/dontpanic.json roles.*)",
    "project_legacy": "project legacy field (.dontpanic/dontpanic.json)",
    "global_roles": "global roles block (~/.dontpanic/config.json roles.*)",
    "global_legacy": "global legacy field (~/.dontpanic/config.json)",
    "goal_auditor_inherits_auditor": "inherited from resolved auditor (no goal_auditor set)",
    "fallback": "hardcoded fallback",
}


@dataclass(frozen=True)
class RoleResolution:
    """The effective agent for one role plus where it was resolved from."""

    role: str
    value: str
    source_layer: SourceLayer
    worker_capable: bool

    @property
    def source_label(self) -> str:
        return _SOURCE_LABELS[self.source_layer]


@dataclass(frozen=True)
class ProjectScope:
    """Resolved project context for a ``roles show``/``set`` invocation.

    ``path`` is the project root the per-project config is read from /
    written to. ``name`` is the registered project name when the path
    came from the registry, else ``None`` (a bare path, or cwd).
    """

    path: Path
    name: str | None


def available_worker_executors() -> list[str]:
    """Worker executor names assignable to a role, sorted. Exactly the
    agents in AGENT_REGISTRY — everyone else is operator-only and refused
    by :func:`assert_assignable`."""
    return agent_surface.worker_executors()


def assert_assignable(
    name: str, *, role: str | None = None, project_path: Path | None = None
) -> None:
    """Guard for ``roles set``: raise :class:`agent_surface.RegisterWorkerError`
    when ``name`` has no executor, so the CLI refuses before any write
    (F004 acceptance #5/#6). The message distinguishes operator-only from
    worker-capable, identical to ``agent register-worker``.

    F013: ``name`` may be a worker-profile id; ``role`` scopes the profile's
    allowed_roles + capability gates to the slot being assigned, and
    ``project_path`` includes that project's profile layer."""
    agent_surface.assert_registrable(name, role=role, project_path=project_path)


def _layer_role_value(cfg: object | None, role: str) -> tuple[str, str] | None:
    """Pull ``(value, kind)`` for ``role`` from a single config layer, where
    ``kind`` is ``"roles"`` (canonical block) or ``"legacy"`` (top-level
    field). Returns ``None`` when the layer does not name the role.

    Mirrors :func:`config.resolvers._role_from_layer_cfg` — roles block wins
    over the legacy field; ``goal_auditor`` has no legacy field anywhere.
    """
    if cfg is None:
        return None

    roles = getattr(cfg, "roles", None)
    if roles is not None:
        # F012 i1 — roles entries may be strings or RoleSpec objects.
        from dontpanic_orchestrate.config.roles import role_name

        v = role_name(getattr(roles, role, None))
        if v:
            return v, "roles"

    if role == "goal_auditor":
        return None  # no legacy field

    # Legacy field names differ between global (default_*) and project (bare).
    legacy_attr_map = {
        "implementer": ("implementer", "default_implementer"),
        "auditor": ("auditor", "default_auditor"),
    }
    for attr in legacy_attr_map[role]:
        v = getattr(cfg, attr, None)
        if v:
            return v, "legacy"
    return None


def _worker_capable_value(role: str, value: str, profiles: dict | None) -> bool:
    """F013 — a role value is worker-capable when it is a registered harness
    OR a defined worker profile that passes the role/capability gates for
    this slot. ``profiles`` is the merged table from
    :func:`worker_profiles.load_profiles` (None → legacy harness-only)."""
    if agent_surface.is_worker_capable(value):
        return True
    if not profiles or value not in profiles:
        return False
    from dontpanic_orchestrate import worker_profiles as wp

    return wp.profile_dispatchable_for_role(value, profiles[value], role)


def resolve_role_with_source(
    role: str,
    *,
    project_cfg: pc.ProjectConfig | None,
    global_cfg: gc.GlobalConfig,
    profiles: dict | None = None,
) -> RoleResolution:
    """Resolve ``role`` through the layered chain, reporting the source layer.

    Precedence (identical to :func:`config.resolvers.resolve_role`):
    project roles → project legacy → global roles → global legacy →
    (``goal_auditor``: resolved auditor) → hardcoded fallback.

    ``profiles`` (F013) widens the ``worker_capable`` tag to include valid
    worker-profile ids; omit for the legacy harness-only classification.
    """
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")

    project_hit = _layer_role_value(project_cfg, role)
    if project_hit is not None:
        value, kind = project_hit
        layer: SourceLayer = "project_roles" if kind == "roles" else "project_legacy"
        return RoleResolution(role, value, layer, _worker_capable_value(role, value, profiles))

    global_hit = _layer_role_value(global_cfg, role)
    if global_hit is not None:
        value, kind = global_hit
        layer = "global_roles" if kind == "roles" else "global_legacy"
        return RoleResolution(role, value, layer, _worker_capable_value(role, value, profiles))

    if role == "goal_auditor":
        # No goal_auditor anywhere — inherit the resolved auditor so the
        # cross-vendor invariant still holds by default (D013).
        auditor = resolve_role_with_source(
            "auditor", project_cfg=project_cfg, global_cfg=global_cfg, profiles=profiles
        )
        return RoleResolution(
            role,
            auditor.value,
            "goal_auditor_inherits_auditor",
            auditor.worker_capable,
        )

    value = _FALLBACK[role]
    return RoleResolution(role, value, "fallback", _worker_capable_value(role, value, profiles))


def resolve_all(scope: ProjectScope) -> list[RoleResolution]:
    """Resolve every role for ``scope`` in fixed order. Loads the project +
    global config once and walks each role through the shared resolver."""
    from dontpanic_orchestrate import worker_profiles as wp

    project_cfg = pc.load_project_config(scope.path)
    global_cfg = gc.load_config()
    profiles = wp.load_profiles(scope.path)
    return [
        resolve_role_with_source(
            role, project_cfg=project_cfg, global_cfg=global_cfg, profiles=profiles
        )
        for role in ROLES
    ]


# ──────────────────────────────  rendering  ──────────────────────────────


def render_show(scope: ProjectScope) -> str:
    """Render ``dontpanic roles show``: available worker executors, the
    effective role assignments with their source layer, and the explicit
    global/project write targets (F004 acceptance #1)."""
    resolutions = resolve_all(scope)
    workers = available_worker_executors()

    scope_desc = scope.name if scope.name is not None else str(scope.path)
    lines: list[str] = ["DontPanic role assignments", ""]

    lines.append(f"PROJECT SCOPE: {scope_desc}")
    lines.append(f"  project config: {pc.project_config_read_path(scope.path)}")
    lines.append(f"  global config:  {gc.config_path()}")
    lines.append("")

    lines.append("AVAILABLE WORKER EXECUTORS (assignable to a role):")
    if workers:
        lines.extend(f"  - {w}" for w in workers)
    else:
        lines.append("  (none registered)")
    lines.append("")

    lines.append("EFFECTIVE ROLES:")
    for r in resolutions:
        tag = "worker-capable" if r.worker_capable else "operator-only — NOT dispatchable"
        lines.append(f"  - {r.role}: {r.value} ({tag})")
        lines.append(f"      source: {r.source_label}")
    lines.append("")

    lines.append("ASSIGN A ROLE:")
    lines.append("  dontpanic roles set <role> <executor> --global")
    lines.append("  dontpanic roles set <role> <executor> --project <name-or-path>")
    lines.append(
        f"  Only the worker executors above are assignable; "
        f"valid roles: {', '.join(ROLES)}."
    )
    return "\n".join(lines) + "\n"


def render_set_preview(
    role: str,
    executor: str,
    *,
    is_global: bool,
    scope: ProjectScope | None,
) -> str:
    """One-line preview of the file + value change a ``roles set`` would make
    (F004 acceptance #4). ``scope`` is required for project writes."""
    key = f"roles.{role}"
    if is_global:
        target = str(gc.config_path())
        scope_label = "global"
    else:
        assert scope is not None, "project scope required for non-global preview"
        target = str(pc.project_config_path(scope.path))
        scope_label = "project"
    return f"set {key} → {executor} in {scope_label} config ({target})"


# ──────────────────────────────  dashboard projection  ──────────────────────────────


def dashboard_projection(scope: ProjectScope) -> dict[str, object]:
    """Project the role-assignment surface for a dashboard (F004 acceptance #7).

    Includes everything a UI needs to render role pickers and the exact,
    safe mutation command for each scope: the available worker executors,
    the current effective role per slot with source layer + dispatchability,
    the project/global scope descriptors, and per-role mutation command
    templates (``<executor>`` placeholder) for both scopes. No secrets are
    emitted — only agent names, role names, and config paths.

    The project mutation command embeds the ``--project`` argument, which can
    be an arbitrary filesystem path containing spaces or shell metacharacters.
    The display string therefore shell-quotes that argument (so a copy/paste
    parses as a single argv token), and a parallel ``mutation_argv`` array is
    emitted so a UI can dispatch the command without re-parsing the string.
    """
    resolutions = resolve_all(scope)
    workers = available_worker_executors()
    project_arg = scope.name if scope.name is not None else str(scope.path)
    # shlex.quote so a path like ``/tmp/my repo`` survives copy/paste as one
    # token; the argv form below carries the raw value for programmatic use.
    project_arg_quoted = shlex.quote(project_arg)

    roles_payload: list[dict[str, object]] = []
    for r in resolutions:
        global_argv = ["dontpanic", "roles", "set", r.role, "<executor>", "--global"]
        project_argv = [
            "dontpanic",
            "roles",
            "set",
            r.role,
            "<executor>",
            "--project",
            project_arg,
        ]
        roles_payload.append(
            {
                "role": r.role,
                "effective": r.value,
                "source_layer": r.source_layer,
                "source_label": r.source_label,
                "worker_capable": r.worker_capable,
                "mutation_commands": {
                    "global": f"dontpanic roles set {r.role} <executor> --global",
                    "project": (
                        f"dontpanic roles set {r.role} <executor> "
                        f"--project {project_arg_quoted}"
                    ),
                },
                "mutation_argv": {
                    "global": global_argv,
                    "project": project_argv,
                },
            }
        )

    return {
        "scope": {
            "project_name": scope.name,
            "project_path": str(scope.path),
            "project_config_path": str(pc.project_config_path(scope.path)),
            "global_config_path": str(gc.config_path()),
        },
        "available_executors": workers,
        "roles": roles_payload,
    }


__all__ = [
    "ROLES",
    "ProjectScope",
    "RoleResolution",
    "SourceLayer",
    "assert_assignable",
    "available_worker_executors",
    "dashboard_projection",
    "render_set_preview",
    "render_show",
    "resolve_all",
    "resolve_role_with_source",
]
