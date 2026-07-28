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
from dontpanic_orchestrate.config.roles import role_model, role_name

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
        # F012 i1 — a roles entry may be a plain string or a RoleSpec
        # object ({"name": ..., "model": ...}); normalize to the name.
        v = role_name(getattr(roles, role, None))
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


def resolve_model(
    plan_dir_or_project: Path,
    role: str,
    *,
    per_call: str | None = None,
    harness: str | None = None,
) -> str | None:
    """F012 (D1/D011/D016 subset) — resolve the vendor model-id override
    for ``role``, or None for the harness CLI default.

    Precedence: ``per_call`` > project layer > global layer > None.
    Within a layer the plan-locked canonical shape
    ``roles.<role>.model`` (RoleSpec object entry) wins over the
    ``models.<role>`` compatibility block. There is no hardcoded
    fallback and no goal_auditor→auditor fall-through — an unset model
    always means "whatever the harness CLI defaults to", which is
    exactly the pre-F012 behavior (goal-audit dispatch sites use
    :func:`resolve_goal_audit_model`, which mirrors the name
    fall-through when it is vendor-safe). Worker profiles (F013) will
    layer above the role-level override when they land.

    ``harness`` (i2, codex audit i1 high finding) is the agent name the
    caller actually dispatches to. When given, harness and model resolve
    atomically: a layer's model applies only if the harness that layer
    was configured against (see :func:`_expected_harness`) matches — a
    model inherited from a layer whose name was overridden by a
    higher-priority layer (project over global, or a plan-level
    ``agents_required`` pick over both) is suppressed instead of being
    forwarded to a different vendor's CLI. Dispatch sites must pass it;
    ``None`` skips the check for display/inventory callers.

    Unlike :func:`resolve_role`, unknown role names return None instead
    of raising: model override is optional metadata, and supervisor
    roles include names (verifier, security, currency, …) that have no
    config surface yet.
    """
    if per_call:
        return per_call
    if role not in ("implementer", "auditor", "goal_auditor"):
        return None

    project_path = _resolve_project_root(plan_dir_or_project)
    project_cfg = pc.load_project_config(project_path) if project_path is not None else None
    layers = (project_cfg, gc.load_config())
    for i, cfg in enumerate(layers):
        v = _model_from_layer_cfg(cfg, role)
        if not v:
            continue
        expected = _dispatch_harness_for(
            _expected_harness(layers[i:], role), _profiles_from_layers(layers[i:])
        )
        if harness is not None and expected != harness:
            # Cross-vendor: this layer paired its model with a different
            # harness than the one being dispatched. Keep scanning — a
            # deeper layer may carry a model for the right vendor.
            continue
        return v
    return None


def _expected_harness(layer_suffix: tuple[Any, ...], role: str) -> str:
    """F012 i2 — the role value a model configured at the FIRST layer of
    ``layer_suffix`` was written against: the name that would resolve if
    that layer were the topmost config layer (its own entry's name, then
    deeper layers, then the goal_auditor→auditor fall-through / hardcoded
    fallback). A model-only entry with no name anywhere is implicitly
    bound to the fallback harness. The value may be a D015 harness alias
    or an F013 worker-profile id — callers must map it through
    :func:`_dispatch_harness_for` before comparing against a dispatched
    harness."""
    for cfg in layer_suffix:
        v = _role_from_layer_cfg(cfg, role)
        if v:
            return v
    if role == "goal_auditor":
        return _expected_harness(layer_suffix, "auditor")
    if role == "implementer":
        return _FALLBACK_IMPLEMENTER
    return _FALLBACK_AUDITOR


def _profiles_from_layers(layer_suffix: tuple[Any, ...]) -> dict[str, Any]:
    """F013 i2 (codex audit i1 high finding) — the worker-profile table as
    visible FROM the first layer of ``layer_suffix``: deeper layers merged
    first, nearer layers winning per id. A model found at the global layer
    must resolve profile identity against the global profile table only —
    a project profile that shadows the same id belongs to a layer the
    global operator never saw, and routing the global model through it can
    hand one vendor's model id to another vendor's CLI."""
    profiles: dict[str, Any] = {}
    for cfg in reversed(layer_suffix):
        layer_profiles = getattr(cfg, "worker_profiles", None) if cfg is not None else None
        if layer_profiles:
            profiles.update(layer_profiles)
    return profiles


def _dispatch_harness_for(name: str, profiles: dict[str, Any]) -> str:
    """F013 i1 (codex audit i0 medium finding) — the AGENT_REGISTRY key
    ``name`` dispatches as: aliases normalize to their registry key, a
    worker-profile id resolves to its harness via ``profiles`` (the table
    visible from the model's own layer — see :func:`_profiles_from_layers`;
    no role/capability gates — this is a vendor comparison, not a dispatch
    authorization). An unknown name is returned as-is so the harness check
    fails closed (model suppressed)."""
    # Lazy import — worker_profiles imports this module inside function
    # bodies; keep the dependency one-way at import time.
    from dontpanic_orchestrate.config.worker_profiles import normalize_harness
    from dontpanic_orchestrate.executors import AGENT_REGISTRY

    normalized = normalize_harness(name)
    if normalized in AGENT_REGISTRY:
        return normalized
    profile = profiles.get(name)
    if profile is not None:
        return profile.harness
    return name


def _model_from_layer_cfg(cfg: Any, role: str) -> str | None:
    """Pull the model override for ``role`` from a single config layer:
    canonical ``roles.<role>.model`` wins over the ``models.<role>``
    compatibility block."""
    if cfg is None:
        return None
    roles = getattr(cfg, "roles", None)
    if roles is not None:
        v = role_model(getattr(roles, role, None))
        if v:
            return v
    models = getattr(cfg, "models", None)
    if models is not None:
        v = getattr(models, role, None)
        if v:
            return v
    return None


def resolve_goal_audit_model(
    plan_dir_or_project: Path, *, harness: str | None = None
) -> str | None:
    """F012 i1 — model override for the goal-audit dispatch paths
    (pre-impl sufficiency + post-impl completion audits).

    Mirrors :func:`resolve_role`'s goal_auditor→auditor name
    fall-through, but only when it is vendor-safe: an explicit
    goal_auditor model wins outright; otherwise the auditor-role model
    applies ONLY when no layer names an explicit ``roles.goal_auditor``
    — in that case the goal audit is dispatched to the resolved auditor
    agent, so the auditor's model targets the same harness. When an
    explicit goal_auditor agent IS configured, falling through would
    hand one vendor's model id to a different vendor's CLI, so the
    result is None (harness default) instead.

    ``harness`` (i2) is the agent name the goal audit actually
    dispatches to; it threads through to :func:`resolve_model`'s
    atomic harness/model check.
    """
    v = resolve_model(plan_dir_or_project, "goal_auditor", harness=harness)
    if v:
        return v

    project_path = _resolve_project_root(plan_dir_or_project)
    project_cfg = pc.load_project_config(project_path) if project_path is not None else None
    for cfg in (project_cfg, gc.load_config()):
        if _role_from_layer_cfg(cfg, "goal_auditor"):
            return None  # explicit goal-auditor agent → no cross-vendor model reuse
    return resolve_model(plan_dir_or_project, "auditor", harness=harness)


def goal_auditor_configured_explicitly(plan_dir_or_project: Path) -> bool:
    """F013 i1 — True when some config layer names an explicit
    ``roles.goal_auditor``. When False, the goal-audit role value came from
    the goal_auditor→auditor name fall-through, so worker-profile gates
    (allowed_roles) must be evaluated against ``auditor`` — the role the
    operator actually bound the worker to."""
    project_path = _resolve_project_root(plan_dir_or_project)
    project_cfg = pc.load_project_config(project_path) if project_path is not None else None
    for cfg in (project_cfg, gc.load_config()):
        if _role_from_layer_cfg(cfg, "goal_auditor"):
            return True
    return False


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
    "goal_auditor_configured_explicitly",
    "resolve_goal_audit_model",
    "resolve_model",
    "resolve_role",
    "resolve_runtime_evidence",
]
