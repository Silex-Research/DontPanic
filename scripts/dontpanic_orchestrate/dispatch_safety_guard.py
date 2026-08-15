"""Plan 2026-06-14-001 F006 — dispatch-safety guard for the D009 SAFETY INVARIANT.

``operator_roles.*`` (F004) express PREFERENCE/INTENT ONLY and are NEVER dispatch
authority. Assigning a surface/agent an operator role must never make DontPanic
able to spawn it as a worker. Dispatch authority derives SOLELY from
``executors.AGENT_REGISTRY`` via the worker ``roles.*`` namespace
(``agent_surface.is_worker_capable`` / ``worker_executors``).

This module is the dispatch-path chokepoint that pins that boundary, plus an
executable proof (:func:`assert_operator_roles_do_not_widen_dispatch`) that no
``operator_roles`` read path can grant or widen dispatchability. The decision
functions deliberately DO NOT read the operator-role config — the boundary is the
absence of that read, not a filter applied after it.
"""

from __future__ import annotations

from pathlib import Path

from dontpanic_orchestrate import agent_surface, operator_roles


class DispatchRefused(Exception):
    """Raised when a non-dispatchable agent/surface is asked to be dispatched.

    A preference-only operator surface (e.g. ``cursor`` holding
    ``operator_roles.primary_operator``) is refused EXACTLY as if no role were
    set — operator-role preferences are not dispatch authorization (D009)."""


def is_dispatchable(name: str, project_path: Path | None = None) -> bool:
    """True iff ``name`` can be dispatched as a worker. Authority derives SOLELY
    from ``executors.AGENT_REGISTRY``: directly (``agent_surface.is_worker_capable``)
    or through a worker profile (F013) whose harness is a registry key and whose
    role/capability gates pass — a profile binds a registered harness, it never
    widens dispatchability. This never consults ``operator_roles``."""
    norm = str(name).strip().lower()
    if agent_surface.is_worker_capable(norm):
        return True
    # Lazy import mirrors agent_surface.assert_registrable — keeps the edge acyclic.
    from dontpanic_orchestrate import worker_profiles as wp

    return wp.is_dispatchable_name(norm, project_path=project_path)


def dispatchable_agents() -> list[str]:
    """The complete set of dispatchable workers — exactly the worker executor
    registry, independent of any operator-role preferences."""
    return agent_surface.worker_executors()


def assert_dispatch_allowed(name: str) -> None:
    """Dispatch chokepoint. Raise :class:`DispatchRefused` when ``name`` is not a
    worker executor — regardless of any operator-role preference it holds."""
    if not is_dispatchable(name):
        registered = ", ".join(dispatchable_agents()) or "(none)"
        raise DispatchRefused(
            f"{name!r} is not a dispatchable worker. Operator-role preferences are "
            f"intent only and never grant dispatch authority (D009); only these "
            f"agents have an executor and can be dispatched: {registered}."
        )


def preference_only_surfaces(project_path: Path | None = None) -> list[str]:
    """Surfaces/agents that appear as an ``operator_roles`` VALUE but are NOT
    dispatchable — i.e. they hold an operator-role preference only. Reads the
    F004 config purely to enumerate the proof set; the dispatch decision itself
    never depends on it."""
    resolved = operator_roles.list_operator_roles(project_path)
    values = {entry["value"] for entry in resolved.values()}
    return sorted(v for v in values if v not in {"human", "unknown_role"} and not is_dispatchable(v))


def assert_operator_roles_do_not_widen_dispatch(project_path: Path | None = None) -> None:
    """Executable D009 proof: every surface that holds an operator-role preference
    but lacks an executor stays non-dispatchable AND is refused at the dispatch
    chokepoint. Raises :class:`DispatchRefused`'s opposite — an
    ``AssertionError`` — only if the invariant is ever violated."""
    for surface in preference_only_surfaces(project_path):
        assert not is_dispatchable(surface), (
            f"D009 VIOLATION: operator-role preference made {surface!r} dispatchable"
        )
        try:
            assert_dispatch_allowed(surface)
        except DispatchRefused:
            continue
        raise AssertionError(
            f"D009 VIOLATION: dispatch of preference-only surface {surface!r} was not refused"
        )


__all__ = [
    "DispatchRefused",
    "assert_dispatch_allowed",
    "assert_operator_roles_do_not_widen_dispatch",
    "dispatchable_agents",
    "is_dispatchable",
    "preference_only_surfaces",
]
