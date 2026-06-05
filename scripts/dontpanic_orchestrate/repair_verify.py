"""Plan 2026-06-04-006 F005 — round-trip verification at apply time.

After the runner applies a repair action it recomputes ``live_state`` and calls
:func:`verify_round_trip` to classify what happened to the targeted card. This is
001's ``clears_when`` invariant evaluated at RUNTIME: ``action -> recompute -> did
the predicate clear?`` The four outcomes are total and closed:

  * :data:`CLEARED`        — the predicate now resolves; the issue is gone.
  * :data:`CHAINED`        — a chained step ran and surfaced its next follow-up.
  * :data:`HUMAN_REQUIRED` — the card cannot be cleared by a command (it is
    operator_attested / blocked_external) and did not resolve; a human / external
    change is now required.
  * :data:`UNCHANGED`      — a command action ran but its predicate did not move
    and nothing chained. This is a DEFECT signal (the card or its action is
    incomplete), surfaced via :func:`is_defective`.

The function is pure: it reads the recomputed ``live_state`` and the optional set
of follow-ups a re-plan surfaced; it performs no I/O and applies no action.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from . import action_resolvability as _ar

CLEARED = "cleared"
CHAINED = "chained"
HUMAN_REQUIRED = "human_required"
UNCHANGED = "unchanged"
OUTCOMES: frozenset[str] = frozenset({CLEARED, CHAINED, HUMAN_REQUIRED, UNCHANGED})


def verify_round_trip(
    card: Any,
    new_live_state: Mapping[str, Any],
    *,
    chained_followups: Sequence[Any] = (),
) -> str:
    """Classify the targeted ``card`` after its action ran, against the recomputed
    ``new_live_state``.

    ``chained_followups`` is the set of new actions a re-plan surfaced for this
    card's chain (empty when none did). Returns one of :data:`OUTCOMES`.
    """
    resolution_class = getattr(card, "resolution_class", None)
    clears_when = getattr(card, "clears_when", None)
    resolved = _ar.evaluate_clears_when(clears_when, new_live_state)

    # A chained step is judged by whether its sequence advanced: a surfaced
    # follow-up means CHAINED even if this step's own predicate also cleared.
    if resolution_class == _ar.RESOLUTION_CHAINED:
        if chained_followups:
            return CHAINED
        if resolved:
            return CLEARED
        return UNCHANGED  # chained step that neither cleared nor surfaced next

    if resolved:
        return CLEARED

    # Not resolved by recompute. A class that no command can clear
    # (operator_attested / blocked_external) escalates to a human; a
    # command_resolvable action that didn't move its predicate is defective.
    if resolution_class in _ar.NON_COMMAND_RESOLUTION_CLASSES:
        return HUMAN_REQUIRED
    return UNCHANGED


def is_defective(outcome: str) -> bool:
    """True iff ``outcome`` indicates the card/action is incomplete (UNCHANGED)."""
    return outcome == UNCHANGED
