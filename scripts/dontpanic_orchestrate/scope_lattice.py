"""Plan 2026-06-04-005 F002 — explicit producer-asserted scope + applicability lattice.

Every repair/action card asserts an explicit :class:`Scope`; the renderer NEVER
infers scope from ``project_name``. :func:`scope_state` decides, for a given
selected view, whether a card APPLIES, is NOT_APPLICABLE (definitively belongs
elsewhere → the gate suppresses it), or is UNRESOLVED (its plan/feature cannot be
mapped to a project → the gate demotes it, fail-closed).

Lattice:
  * GLOBAL  — applies to every view.
  * aggregate views (GLOBAL / FLEET selected) — show everything.
  * FLEET   — not shown in a single project view.
  * PROJECT — applies only to its own project's view.
  * PLAN / FEATURE — resolve ``plan_id`` → project; failed resolution → UNRESOLVED.
  * unknown scope — fails closed → UNRESOLVED.

Scope-unset legacy cards route through :func:`resolve_card_scope_state`, which
LOGS a deprecation warning and refuses to silently treat them as the selected
project's work: in an aggregate view they are visible (APPLIES); in a specific
project/plan view they are UNRESOLVED (demotion-eligible), never project work.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable

_log = logging.getLogger(__name__)


class Scope(str, Enum):
    GLOBAL = "global"
    FLEET = "fleet"
    PROJECT = "project"
    PLAN = "plan"
    FEATURE = "feature"


# scope-application states (consumed by render_gate step 1)
APPLIES = "applies"
NOT_APPLICABLE = "not_applicable"
UNRESOLVED = "unresolved"
SCOPE_STATES = frozenset({APPLIES, NOT_APPLICABLE, UNRESOLVED})

_AGGREGATE = frozenset({Scope.GLOBAL.value, Scope.FLEET.value})


def _norm(scope: Any) -> str:
    return getattr(scope, "value", scope)


def scope_state(
    card_scope: Any,
    *,
    selected_scope: Any,
    card_project: str | None = None,
    selected_project: str | None = None,
    card_plan_id: str | None = None,
    resolve_plan_to_project: Callable[[str], str | None] | None = None,
) -> str:
    """Return APPLIES / NOT_APPLICABLE / UNRESOLVED for ``card_scope`` in the
    selected view. See module docstring for the lattice."""
    cs = _norm(card_scope)
    sel = _norm(selected_scope)

    # GLOBAL applies everywhere.
    if cs == Scope.GLOBAL.value:
        return APPLIES
    # Aggregate views (all-projects / fleet) show every scope.
    if sel in _AGGREGATE:
        return APPLIES
    # Below: a specific project (or plan/feature) view is selected.
    if cs == Scope.FLEET.value:
        return NOT_APPLICABLE
    if cs == Scope.PROJECT.value:
        return APPLIES if card_project == selected_project else NOT_APPLICABLE
    if cs in (Scope.PLAN.value, Scope.FEATURE.value):
        if resolve_plan_to_project is None or not card_plan_id:
            return UNRESOLVED  # cannot prove which project — fail closed
        proj = resolve_plan_to_project(card_plan_id)
        if not proj:
            return UNRESOLVED
        return APPLIES if proj == selected_project else NOT_APPLICABLE
    return UNRESOLVED  # unknown scope — fail closed


def is_legacy_unscoped(card: Any) -> bool:
    """True iff the card asserts no explicit scope (routes through the adapter)."""
    return not getattr(card, "scope", None)


def resolve_card_scope_state(
    card: Any,
    *,
    selected_scope: Any,
    selected_project: str | None = None,
    resolve_plan_to_project: Callable[[str], str | None] | None = None,
) -> str:
    """Resolve a card's scope state, asserting scope explicitly and routing
    unscoped legacy cards through a LOGGED adapter (no silent project inference)."""
    raw = getattr(card, "scope", None)
    if not raw:
        _log.warning(
            "render-truth: unscoped legacy ActionItem %r routed through legacy_adapter "
            "(no explicit scope; demotion-eligible, never silently project work)",
            getattr(card, "id", "?"),
        )
        # Visible in an aggregate view; UNRESOLVED (demotion-eligible) in a
        # specific project/plan view — we will not infer it is THIS project's work.
        return APPLIES if _norm(selected_scope) in _AGGREGATE else UNRESOLVED
    return scope_state(
        raw,
        selected_scope=selected_scope,
        card_project=getattr(card, "project_name", None),
        selected_project=selected_project,
        card_plan_id=getattr(card, "plan_id", None),
        resolve_plan_to_project=resolve_plan_to_project,
    )
