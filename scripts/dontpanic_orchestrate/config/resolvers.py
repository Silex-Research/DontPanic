"""Plan G F006 — layered config resolvers.

Two public helpers:

- :func:`resolve_role` — per-call > project (roles + legacy) > global
  (roles + legacy) > hardcoded fallback. Roles: ``implementer``,
  ``auditor``, ``goal_auditor``.
- :func:`resolve_runtime_evidence` — per-call > project > empty. **No
  global tier per D015.**

Both helpers walk the same precedence model (D004): per-call always
wins; deeper layers fall through when their value is ``None`` / absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from dontpanic_orchestrate import global_config as gc
from dontpanic_orchestrate import project_config as pc

Role = Literal["implementer", "auditor", "goal_auditor"]
RuntimeSource = Literal["web", "ios", "android", "backend"]

_FALLBACK_IMPLEMENTER = "claude"
_FALLBACK_AUDITOR = "codex"


def _role_from_layer_cfg(cfg: Any, role: Role) -> str | None:
    """Pull the role name from a single config layer.

    Order within a layer: ``roles.<role>`` (canonical) wins over the
    legacy top-level field (``implementer`` / ``auditor`` for project,
    ``default_implementer`` / ``default_auditor`` for global).
    ``goal_auditor`` has no legacy field — only the ``roles`` block can
    name it explicitly.
    """
    if cfg is None:
        return None

    roles = getattr(cfg, "roles", None)
    if roles is not None:
        v = getattr(roles, role, None)
        if v:
            return v

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
            return v
    return None


def resolve_role(
    plan_dir_or_project: Path,
    role: Role,
    *,
    per_call: str | None = None,
) -> str:
    """Resolve a role name through the layered precedence chain.

    Args:
        plan_dir_or_project: a path inside (or equal to) a project root.
            Pass either ``plan_dir`` (resolver will walk up to find the
            project root) or the project root directly.
        role: ``implementer``, ``auditor``, or ``goal_auditor``.
        per_call: caller-supplied override. Wins over every layer.

    Returns:
        Resolved role name. Always non-empty — falls through to the
        hardcoded fallback (``claude`` / ``codex``) if every layer is
        unset. ``goal_auditor`` falls through to the resolved
        ``auditor`` so callers that don't set it explicitly inherit the
        cross-vendor invariant from the auditor role.

    Raises:
        ValueError: when ``role`` is not a known role name.
    """
    if role not in ("implementer", "auditor", "goal_auditor"):
        raise ValueError(f"unknown role {role!r}; expected implementer / auditor / goal_auditor")

    if per_call:
        return per_call

    project_path = _resolve_project_root(plan_dir_or_project)
    project_cfg = pc.load_project_config(project_path) if project_path is not None else None
    project_v = _role_from_layer_cfg(project_cfg, role)
    if project_v:
        return project_v

    global_cfg = gc.load_config()
    global_v = _role_from_layer_cfg(global_cfg, role)
    if global_v:
        return global_v

    if role == "goal_auditor":
        # No legacy goal_auditor field anywhere — fall through to the
        # resolved auditor so the cross-vendor invariant still holds by
        # default.
        return resolve_role(plan_dir_or_project, "auditor")

    if role == "implementer":
        return _FALLBACK_IMPLEMENTER
    return _FALLBACK_AUDITOR


def resolve_runtime_evidence(
    plan_dir_or_project: Path,
    source: RuntimeSource,
    *,
    per_call: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve runtime-evidence defaults for ``source`` (web / ios /
    android / backend).

    Precedence (D015 — no global tier):
      1. ``per_call`` — caller-supplied dict, merged atop project layer.
      2. ``project.runtime_evidence.<source>`` — typed sub-model dumped
         to dict.
      3. empty dict.

    The merge is shallow (``{**project, **per_call}``) — callers that
    need a per-key shape negotiation should do it themselves on the
    returned dict.

    Returns:
        A dict (possibly empty) the adapter can consume. Callers pick
        the keys they understand; unknown keys are silently ignored at
        the adapter call site.

    Raises:
        ValueError: when ``source`` is not a known runtime source.
    """
    if source not in ("web", "ios", "android", "backend"):
        raise ValueError(f"unknown source {source!r}; expected web / ios / android / backend")

    project_path = _resolve_project_root(plan_dir_or_project)
    project_layer: dict[str, Any] = {}
    if project_path is not None:
        project_cfg = pc.load_project_config(project_path)
        if project_cfg is not None and project_cfg.runtime_evidence is not None:
            sub = getattr(project_cfg.runtime_evidence, source, None)
            if sub is not None:
                project_layer = sub.model_dump(exclude_none=True)

    if per_call:
        return {**project_layer, **per_call}
    return project_layer


def _resolve_project_root(plan_dir_or_project: Path) -> Path | None:
    """Best-effort resolution of the project root containing
    ``plan_dir_or_project``.

    Walks the registry looking for an ancestor match (uses
    :func:`project_config.find_project_for_plan_dir` when the input
    appears to be a plan_dir under ``docs/plans/``); falls back to
    treating the input as the project root itself when no registry
    match is found.
    """
    plan_dir_or_project = plan_dir_or_project.resolve()
    match = pc.find_project_for_plan_dir(plan_dir_or_project)
    if match is not None:
        return match[0]
    if plan_dir_or_project.is_dir():
        return plan_dir_or_project
    return None


__all__ = [
    "Role",
    "RuntimeSource",
    "resolve_role",
    "resolve_runtime_evidence",
]
