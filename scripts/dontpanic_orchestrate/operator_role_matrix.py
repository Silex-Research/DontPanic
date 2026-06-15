"""Plan 2026-06-14-001 F005 — read-only dashboard operator-role matrix projection.

A PURE projection that renders the ``operator_roles.*`` preferences (F004) as a
role matrix for the dashboard, kept SEPARATE from the worker-dispatch ``roles.*``
namespace so the two never conflate in the rendered view. Projection only — no
mutation, no dispatch semantics. Operator-role preferences are surfaced as INTENT
ONLY and carry no dispatchability claim (D009).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

OPERATOR_NAMESPACE = "operator_roles"
WORKER_NAMESPACE = "worker_roles"


def project_role_matrix(
    operator_roles_map: Mapping[str, Mapping[str, str]],
    *,
    worker_role_assignments: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Project the resolved operator-role map (from
    :func:`operator_roles.list_operator_roles`) into a dashboard matrix.

    PURE: derives only from the passed-in arguments — no I/O, no mutation of the
    inputs. Each operator entry preserves its scope provenance (global vs
    project). The operator section is explicitly flagged ``intent_only`` /
    ``dispatch_authority: False`` and rendered under a DISTINCT namespace from the
    worker section, so the rendered matrix never conflates preference with
    dispatch authority.
    """
    operator_entries = [
        {
            "role": role,
            "value": str(entry.get("value", "")),
            "scope": str(entry.get("scope", "")),
        }
        for role, entry in sorted(operator_roles_map.items())
    ]
    worker_entries = [
        {"role": role, "agent": str(agent)}
        for role, agent in sorted((worker_role_assignments or {}).items())
    ]
    return {
        OPERATOR_NAMESPACE: {
            # preference/intent ONLY — never dispatch authority (D009/F006)
            "intent_only": True,
            "dispatch_authority": False,
            "entries": operator_entries,
        },
        WORKER_NAMESPACE: {
            # the dispatch-authority namespace, rendered separately
            "dispatch_authority": True,
            "entries": worker_entries,
        },
    }


__all__ = [
    "OPERATOR_NAMESPACE",
    "WORKER_NAMESPACE",
    "project_role_matrix",
]
