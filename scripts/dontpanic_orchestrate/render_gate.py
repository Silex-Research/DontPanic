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

    # NEEDS_ACTION: must affirmatively prove all four obligations.
    # 2. source fresh + evaluable
    if not (source_fresh and source_evaluable):
        return DEMOTE
    # 4. resolution_class set (checked before 3 so an evidence-class card is
    #    recognised before the recompute-predicate requirement is applied).
    rclass = getattr(card, "resolution_class", None)
    if not rclass:
        return DEMOTE
    # 3. A verification path must exist. Per 001's taxonomy there are two ways a
    #    NEEDS_ACTION card proves it is still live: RECOMPUTE (a clears_when
    #    predicate) OR EVIDENCE (operator_attested / blocked_external resolve via
    #    human/external attestation, not recompute — they legitimately carry no
    #    clears_when and must NOT be demoted). Only a command-resolvable / chained
    #    card with NO predicate is unverifiable → demote.
    cw = getattr(card, "clears_when", None)
    if cw is None:
        if rclass in _ar.NON_COMMAND_RESOLUTION_CLASSES:
            return RENDER  # awaiting human evidence — a true, live Needs Action
        return DEMOTE  # command-resolvable but unverifiable → uncertainty
    # 5. predicate resolved → suppress (issue genuinely gone)
    if _ar.evaluate_clears_when(cw, live_state):
        return SUPPRESS
    # 6. unresolved → render as Needs Action
    return RENDER
