"""Plan 2026-07-27-001 F013 — worker-profile resolution + gates (Track D2).

A ``roles.<role>`` entry may name either a legacy harness (an
``executors.AGENT_REGISTRY`` key — ``roles.implementer: "claude"``) or a
worker-profile id defined under ``worker_profiles.<id>`` in the global
and/or per-project config. :func:`resolve_worker` maps that configured
string to the concrete dispatch identity ``(profile_id, harness, model)``
that the supervisor keys quota, executor resolution, argv, and audit
evidence on.

Precedence and safety:

  - **Harness membership wins.** A configured name that IS a registry key
    always dispatches as that harness — a profile that shadows a harness
    name is inert (and the ``workers`` CLI refuses to create one). This
    preserves D009: dispatch authority derives solely from
    ``AGENT_REGISTRY``; profiles only *bind* a registered harness to a
    model + role set, they can never widen dispatchability.
  - **Profiles merge global → project**, project winning per id (same
    direction as every other config layer).
  - **Gates refuse clearly.** A profile assigned outside its
    ``allowed_roles``, a profile whose harness lacks the role's required
    capability flags (F011: implementer needs file_edit + tool_use +
    non_interactive), a profile claiming capabilities its harness does
    not provide, and a profile pointing at an unregistered harness all
    raise a :class:`WorkerProfileError` subclass with an operator-fixable
    message instead of KeyError-ing inside the registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dontpanic_orchestrate import global_config as gc
from dontpanic_orchestrate import project_config as pc
from dontpanic_orchestrate.config.worker_profiles import (
    PROFILE_ID_PATTERN,
    ROLE_REQUIRED_CAPABILITIES,
    WorkerProfile,
    missing_capabilities_for_role,
    normalize_harness,
    widened_capabilities,
)
from dontpanic_orchestrate.executors import AGENT_REGISTRY


class WorkerProfileError(ValueError):
    """Base for profile resolution/gate refusals. Message is the operator-
    facing refusal text; CLI surfaces map it to exit 3."""


class UnknownWorkerError(WorkerProfileError):
    """Configured role value is neither a registered harness nor a
    defined worker profile."""


class ProfileRoleRefusedError(WorkerProfileError):
    """Profile's ``allowed_roles`` does not include the requested role."""


class ProfileCapabilityRefusedError(WorkerProfileError):
    """Capability gate failed: the profile's effective capabilities are
    missing flags the role requires, or the profile claims capabilities
    its harness does not provide."""


class ProfileHarnessUnknownError(WorkerProfileError):
    """Profile names a harness with no executor in AGENT_REGISTRY."""


@dataclass(frozen=True)
class ResolvedWorker:
    """Concrete dispatch identity for one configured role value."""

    name: str
    """The configured string (profile id or legacy harness name)."""

    profile_id: str | None
    """Profile id when a profile resolved; None on the legacy path."""

    display_name: str | None

    harness: str
    """AGENT_REGISTRY key to dispatch through."""

    model: str | None
    """Profile-level model override. None falls through to the F012
    role-level model (``config.resolvers.resolve_model``) and then the
    harness CLI default."""


def load_profiles(project_path: Path | None = None) -> dict[str, WorkerProfile]:
    """Merged worker-profile table: global config overlaid by the
    per-project config (project wins per id). Missing blocks are the
    valid zero state — returns {}."""
    profiles: dict[str, WorkerProfile] = {}
    global_cfg = gc.load_config()
    if global_cfg.worker_profiles:
        profiles.update(global_cfg.worker_profiles)
    if project_path is not None:
        project_cfg = pc.load_project_config(project_path)
        if project_cfg is not None and project_cfg.worker_profiles:
            profiles.update(project_cfg.worker_profiles)
    return profiles


def project_root_for(plan_dir_or_project: Path | None) -> Path | None:
    """Best-effort project root for a plan dir or project path — mirrors
    the private resolver in :mod:`config.resolvers` (registry match first,
    then the path itself when it is a directory)."""
    if plan_dir_or_project is None:
        return None
    resolved = plan_dir_or_project.resolve()
    match = pc.find_project_for_plan_dir(resolved)
    if match is not None:
        return match[0]
    if resolved.is_dir():
        return resolved
    return None


def assert_profile_role_allowed(profile_id: str, profile: WorkerProfile, role: str) -> None:
    """All three profile gates for holding ``role``: registered harness,
    no capability widening, allowed_roles membership, and the role's
    capability requirements. Raises the matching WorkerProfileError."""
    if profile.harness not in AGENT_REGISTRY:
        raise ProfileHarnessUnknownError(
            f"worker profile {profile_id!r} names harness {profile.harness!r}, which has "
            f"no executor in AGENT_REGISTRY; registered harnesses: "
            f"{', '.join(sorted(AGENT_REGISTRY))}. Model ids are never harnesses (D010)."
        )
    widened = widened_capabilities(profile)
    if widened:
        raise ProfileCapabilityRefusedError(
            f"worker profile {profile_id!r} claims capabilities its harness "
            f"{profile.harness!r} does not provide: {widened}. Capability overrides "
            f"can restrict a profile, never widen it (D009)."
        )
    if profile.allowed_roles is not None and role not in profile.allowed_roles:
        raise ProfileRoleRefusedError(
            f"worker profile {profile_id!r} is not allowed to hold role {role!r}; "
            f"allowed_roles: {profile.allowed_roles}."
        )
    missing = missing_capabilities_for_role(profile, role)
    if missing:
        raise ProfileCapabilityRefusedError(
            f"worker profile {profile_id!r} (harness {profile.harness!r}) cannot hold "
            f"role {role!r}: missing capabilities {missing}. The {role} role requires "
            f"{sorted(ROLE_REQUIRED_CAPABILITIES.get(role, frozenset()))}."
        )


def assert_profile_dispatchable(profile_id: str, profile: WorkerProfile) -> None:
    """Role-agnostic subset of the gates (harness registered + no
    capability widening). Used where no role is in scope yet, e.g.
    ``agent register-worker`` without ``--role``."""
    if profile.harness not in AGENT_REGISTRY:
        raise ProfileHarnessUnknownError(
            f"worker profile {profile_id!r} names harness {profile.harness!r}, which has "
            f"no executor in AGENT_REGISTRY; registered harnesses: "
            f"{', '.join(sorted(AGENT_REGISTRY))}."
        )
    widened = widened_capabilities(profile)
    if widened:
        raise ProfileCapabilityRefusedError(
            f"worker profile {profile_id!r} claims capabilities its harness "
            f"{profile.harness!r} does not provide: {widened}."
        )


def profile_dispatchable_for_role(profile_id: str, profile: WorkerProfile, role: str) -> bool:
    """Boolean form of :func:`assert_profile_role_allowed`."""
    try:
        assert_profile_role_allowed(profile_id, profile, role)
    except WorkerProfileError:
        return False
    return True


def holdable_roles(profile_id: str, profile: WorkerProfile) -> list[str]:
    """The canonical roles this profile may hold after all gates."""
    return [
        role
        for role in ROLE_REQUIRED_CAPABILITIES
        if profile_dispatchable_for_role(profile_id, profile, role)
    ]


def is_dispatchable_name(
    name: str, *, project_path: Path | None = None, role: str | None = None
) -> bool:
    """True when ``name`` can be dispatched: a registered harness, or a
    defined profile that passes the gates (for ``role`` when given, for
    at least one canonical role otherwise)."""
    if normalize_harness(name) in AGENT_REGISTRY:
        return True
    profile = load_profiles(project_path).get(name)
    if profile is None:
        return False
    if role is not None:
        return profile_dispatchable_for_role(name, profile, role)
    return bool(holdable_roles(name, profile))


def resolve_worker(
    plan_dir_or_project: Path | None, role: str, name: str
) -> ResolvedWorker:
    """Map a configured role value to its concrete dispatch identity.

    Legacy path: ``name`` (after D015 alias normalization — ``claude_cli``
    → ``claude`` etc.) in AGENT_REGISTRY → dispatch as that harness, no
    profile, no model override (F012 role-level model still applies at
    the call site). Profile path: gates run, then the profile's harness +
    model bind. Anything else raises :class:`UnknownWorkerError`.
    """
    normalized = normalize_harness(name)
    if normalized in AGENT_REGISTRY:
        return ResolvedWorker(
            name=name, profile_id=None, display_name=None, harness=normalized, model=None
        )
    project_path = project_root_for(plan_dir_or_project)
    profile = load_profiles(project_path).get(name)
    if profile is None:
        raise UnknownWorkerError(
            f"{name!r} is neither a registered harness ({', '.join(sorted(AGENT_REGISTRY))}) "
            f"nor a defined worker profile. Define one with "
            f"`dontpanic workers add {name} --harness <harness>` or assign a registered "
            f"harness to the role instead."
        )
    assert_profile_role_allowed(name, profile, role)
    return ResolvedWorker(
        name=name,
        profile_id=name,
        display_name=profile.display_name,
        harness=profile.harness,
        model=profile.model,
    )


def resolve_goal_audit_worker(plan_dir: Path, name: str) -> ResolvedWorker:
    """Resolve the goal-audit dispatch identity for ``name``.

    The gate role tracks provenance: an explicit ``roles.goal_auditor``
    gates on ``goal_auditor``; a value inherited through the
    goal_auditor→auditor name fall-through gates on ``auditor`` — the role
    the operator actually assigned the worker to (an auditor-only profile
    must stay dispatchable for the inherited goal audit)."""
    from dontpanic_orchestrate.config.resolvers import goal_auditor_configured_explicitly

    role = "goal_auditor" if goal_auditor_configured_explicitly(plan_dir) else "auditor"
    return resolve_worker(plan_dir, role, name)


def peek_worker(
    plan_dir_or_project: Path | None, name: str
) -> ResolvedWorker | None:
    """Identity-only resolution: map ``name`` to (profile_id, harness,
    model) WITHOUT role/capability gates. Returns None when the name is
    neither a registered harness (after alias normalization) nor a defined
    profile. Used for vendor comparisons (same-vendor invariant) and
    display, where the harness identity matters but a role gate would be
    wrong — never for dispatch authorization."""
    normalized = normalize_harness(name)
    if normalized in AGENT_REGISTRY:
        return ResolvedWorker(
            name=name, profile_id=None, display_name=None, harness=normalized, model=None
        )
    profile = load_profiles(project_root_for(plan_dir_or_project)).get(name)
    if profile is None:
        return None
    return ResolvedWorker(
        name=name,
        profile_id=name,
        display_name=profile.display_name,
        harness=profile.harness,
        model=profile.model,
    )


def validate_profile(profile_id: str, profile: WorkerProfile) -> list[str]:
    """Operator-facing validation for the ``workers`` CLI writer. Returns
    a list of problems (empty = valid). Only EXPLICIT allowed_roles are
    checked against capability gates — ``allowed_roles: null`` (all
    roles) narrows naturally at dispatch time instead."""
    problems: list[str] = []
    if not PROFILE_ID_PATTERN.fullmatch(profile_id):
        problems.append(
            f"profile id {profile_id!r} must match {PROFILE_ID_PATTERN.pattern} "
            "(lowercase slug)"
        )
    if normalize_harness(profile_id) in AGENT_REGISTRY:
        problems.append(
            f"profile id {profile_id!r} shadows a registered harness name (or a D015 "
            "alias of one); harness names always resolve as harnesses, so this profile "
            "could never be dispatched"
        )
    if profile.harness not in AGENT_REGISTRY:
        problems.append(
            f"harness {profile.harness!r} has no executor in AGENT_REGISTRY; registered: "
            f"{', '.join(sorted(AGENT_REGISTRY))}"
        )
    else:
        widened = widened_capabilities(profile)
        if widened:
            problems.append(
                f"capabilities {widened} are claimed but harness {profile.harness!r} does "
                "not provide them (overrides restrict, never widen)"
            )
        for role in profile.allowed_roles or []:
            missing = missing_capabilities_for_role(profile, role)
            if missing:
                problems.append(
                    f"allowed role {role!r} can never be held: harness "
                    f"{profile.harness!r} with these overrides is missing "
                    f"capabilities {missing}"
                )
    return problems


__all__ = [
    "ProfileCapabilityRefusedError",
    "ProfileHarnessUnknownError",
    "ProfileRoleRefusedError",
    "ResolvedWorker",
    "UnknownWorkerError",
    "WorkerProfileError",
    "assert_profile_dispatchable",
    "assert_profile_role_allowed",
    "holdable_roles",
    "is_dispatchable_name",
    "load_profiles",
    "peek_worker",
    "profile_dispatchable_for_role",
    "project_root_for",
    "resolve_goal_audit_worker",
    "resolve_worker",
    "validate_profile",
]
