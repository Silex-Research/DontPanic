"""Plan 2026-06-04-005 F001 — the unified render gate.

The single, deterministic decision point that every ActionItem passes through
before it can render as Needs Action. ``render_decision`` returns exactly one of
three total, mutually-exclusive outcomes — :data:`RENDER` / :data:`SUPPRESS` /
:data:`DEMOTE` — via a normative 6-step order (operator-confirmed, D004):

  1. scope applies to the selected scope?   else SUPPRESS  (not relevant here)
  2. source fresh AND evaluable?             else DEMOTE
  3. clears_when present?                     else DEMOTE
  4. resolution_class set?                    else DEMOTE
  5. predicate resolved?                      -> SUPPRESS
  6. else (unresolved)                        -> RENDER

This INVERTS :func:`action_resolvability.suppress_resolved` from the old
render-unless-proven-resolved default to **suppress-unless-proven-live**: a
Needs Action card must affirmatively prove all four obligations to earn its slot.

It is the ONLY place a ``DEMOTE`` decision is made — F004 builds the demotion
("could not refresh") card, but never decides demotion. Scope-application (F002)
and per-source freshness (F003) are computed upstream and injected here as
already-resolved inputs, keeping the gate pure and unit-testable in isolation.

Lower-band cards (advisory/info/ready) make no Needs Action claim, so the
fail-closed proof obligations (steps 2–4) do not apply to them: scope still
suppresses an inapplicable card, a resolved predicate still suppresses, and
otherwise they render in their own band. Per D005, step 3's "evaluable" nuance
(the predicate's own inputs being present) is covered by step 2's
source-evaluability — the closed predicate registry guarantees the predicate
name itself is known at ``ClearsWhen`` construction time.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import action_resolvability as _ar
from . import scope_lattice as _sl
from .operator_console import Band

RENDER = "render"
SUPPRESS = "suppress"
DEMOTE = "demote"
OUTCOMES: frozenset[str] = frozenset({RENDER, SUPPRESS, DEMOTE})


def _is_needs_action(card: Any) -> bool:
    band = getattr(card, "band", None)
    return getattr(band, "value", band) == Band.NEEDS_ACTION.value


def render_decision(
    card: Any,
    *,
    scope_applies: bool | None = None,
    scope_state: str | None = None,
    source_fresh: bool,
    source_evaluable: bool = True,
    live_state: Mapping[str, Any],
) -> str:
    """Classify ``card`` into RENDER / SUPPRESS / DEMOTE for the selected scope.

    Scope (F002) and ``source_fresh`` / ``source_evaluable`` (F003) are resolved
    upstream and passed in. Pass the F002 tri-state via ``scope_state`` (APPLIES /
    NOT_APPLICABLE / UNRESOLVED); the legacy ``scope_applies`` bool is still
    accepted (True→APPLIES, False→NOT_APPLICABLE). ``live_state`` is the fleet
    live-state map the closed clears_when predicates evaluate against.
    """
    # Resolve the scope decision (tri-state preferred; bool kept for F001 compat).
    st = scope_state
    if st is None:
        if scope_applies is None:
            st = _sl.APPLIES
        else:
            st = _sl.APPLIES if scope_applies else _sl.NOT_APPLICABLE

    # 1. scope. NOT_APPLICABLE → suppress (belongs elsewhere, it is absent here).
    #    UNRESOLVED → demote (cannot prove which project; fail closed, not silent).
    if st == _sl.NOT_APPLICABLE:
        return SUPPRESS
    if st == _sl.UNRESOLVED:
        return DEMOTE

    if not _is_needs_action(card):
        # Lower-band cards make no Needs Action claim and are not fail-closed
        # gated. They still vanish when their predicate is resolved; otherwise
        # they render in their own band.
        cw = getattr(card, "clears_when", None)
        if cw is not None and _ar.evaluate_clears_when(cw, live_state):
            return SUPPRESS
        return RENDER

    # NEEDS_ACTION: must affirmatively prove liveness. Demotion is the
    # UNCERTAINTY axis only — staleness / un-evaluability / malformed — NOT the
    # absence of a recompute predicate (per 001's THREE mechanisms, below).
    # 2. source fresh + evaluable (the real uncertainty axis)
    if not (source_fresh and source_evaluable):
        return DEMOTE
    # 4. resolution_class must be set — a NEEDS_ACTION card that declares no
    #    resolution class at all is malformed → uncertainty.
    if not getattr(card, "resolution_class", None):
        return DEMOTE
    # 3 / 5 / 6 — verification path (001's three mechanisms):
    #   RECOMPUTE      — a clears_when predicate; resolved → suppress.
    #   EVIDENCE       — operator_attested / blocked_external; no predicate,
    #                    resolves via human/external attestation → render.
    #   RECONSTRUCTION — re-emitted fresh each build (projected sources); its
    #                    liveness is PROVEN by the fresh source at step 2, so a
    #                    clears_when=None card on a fresh source is current → render.
    # A missing predicate is therefore NOT uncertainty; only step 2 (stale) is.
    cw = getattr(card, "clears_when", None)
    if cw is not None and _ar.evaluate_clears_when(cw, live_state):
        return SUPPRESS  # recompute proves the issue is gone
    return RENDER


# ── F005: global/project separation + render-truth invariant ──────────────────
def global_badge_for(card: Any, *, selected_scope: str) -> bool:
    """Plan 2026-06-04-005 F005 — a scope=global card shown in a SPECIFIC project
    view carries a GLOBAL badge (so a global issue is never mistaken for project
    work). Aggregate views (global/fleet) show everything ungrouped and need no
    per-card badge."""
    return (
        getattr(card, "scope", None) == _sl.Scope.GLOBAL.value
        and selected_scope not in (_sl.Scope.GLOBAL.value, _sl.Scope.FLEET.value)
    )


def render_truth_invariant(
    rendered: "list[Any] | tuple[Any, ...]",
    *,
    scope_state_of: "Any",
    source_fresh_of: "Any",
    live_state: Mapping[str, Any],
) -> list[tuple[str, str]]:
    """Plan 2026-06-04-005 F005 — assert the four-part contract over the rendered
    Needs Action set. For every visible NEEDS_ACTION card, ALL must hold:
    scope applies, source fresh+evaluable, resolution_class set, and the
    clears_when predicate is NOT resolved. Returns a list of ``(card_id, reason)``
    violations — empty iff the invariant holds. ``scope_state_of(card)`` returns a
    scope_lattice state; ``source_fresh_of(card)`` returns ``(fresh, evaluable)``.
    """
    violations: list[tuple[str, str]] = []
    for card in rendered:
        if not _is_needs_action(card):
            continue
        cid = getattr(card, "id", "?")
        if scope_state_of(card) != _sl.APPLIES:
            violations.append((cid, "scope"))
            continue
        fresh, evaluable = source_fresh_of(card)
        if not (fresh and evaluable):
            violations.append((cid, "stale"))
            continue
        if not getattr(card, "resolution_class", None):
            violations.append((cid, "resolution_class"))
            continue
        cw = getattr(card, "clears_when", None)
        if cw is not None and _ar.evaluate_clears_when(cw, live_state):
            violations.append((cid, "resolved"))
    return violations
