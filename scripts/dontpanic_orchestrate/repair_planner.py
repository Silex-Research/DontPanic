"""Plan 2026-06-04-006 F002 — dependency-ordered fixpoint repair planner.

Builds an ordered repair plan from the 005 render-gate output and drives it to a
fixpoint. The loop is: pick the eligible auto_safe batch -> apply it -> recompute
``live_state`` -> RE-PLAN -> repeat, until only human_required / blocked_external /
info cards remain or no auto_safe action can make progress. A state-changing step
re-derives the next eligible set rather than trusting a static list, so a repair
that unblocks a dependent lets the dependent run on the next pass.

Termination is structural: an applied action is recorded in ``applied`` and never
re-applied, so each non-terminal iteration retires at least one candidate from a
finite set. A hard cap backstops against logic error. Cyclic dependencies are
detected up front (Kahn) and deferred — never looped.

Reuses the sibling primitives, never re-deriving them:
  * :func:`repair_safety.resolve_safety` / ``is_runnable_at`` — WHETHER an action
    may auto-run at the operator's chosen tier (F001).
  * :func:`repair_verify.verify_round_trip` — classify each applied action's
    outcome against the recomputed state (F005).
  * :func:`action_resolvability.evaluate_clears_when` — is a card's predicate now
    resolved (so it drops from the live set)? (001).

The planner is PURE: the side effect of "running" an action is injected as
``apply_fn(action, live_state) -> new_live_state``. Tier 1 (``repair plan``, F003)
never calls ``run_fixpoint``; it emits :func:`order_actions`. Tiers 2/3
(``repair apply``, F004) supply a real ``apply_fn``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import action_resolvability as _ar
from . import render_gate as _rg
from . import repair_safety as _rs
from . import repair_verify as _rv

# ── deferral reasons (logged per deferred action) ─────────────────────────────
DEFER_SAFETY = "safety_tier"  # not auto_safe-runnable at this tier -> human card
DEFER_DEPENDENCY = "dependency"  # a still-live prerequisite blocks it
DEFER_CYCLE = "cycle"  # part of a dependency cycle (unsatisfiable)
DEFER_REASONS: frozenset[str] = frozenset({DEFER_SAFETY, DEFER_DEPENDENCY, DEFER_CYCLE})


@dataclasses.dataclass(frozen=True)
class RepairAction:
    """One candidate repair the planner orders, applies, and verifies.

    Carries the F001 safety assertion (``kind`` / ``safety_class`` / ``apply_tier``
    validated by :func:`repair_safety.resolve_safety`), the 001 resolvability
    contract (``clears_when`` / ``resolution_class``), the dependency edges, and
    the display fields the F003 agent-handoff bundle emits.
    """

    id: str
    kind: str | None
    safety_class: str | None
    apply_tier: str | None
    resolution_class: str = _ar.RESOLUTION_COMMAND_RESOLVABLE
    clears_when: _ar.ClearsWhen | None = None
    depends_on: tuple[str, ...] = ()
    # display passthrough for the F003 bundle (no behavior here):
    command: str | None = None
    plain_consequence: str | None = None
    scope: str | None = None


@dataclasses.dataclass(frozen=True)
class AppliedStep:
    action_id: str
    outcome: str  # one of repair_verify.OUTCOMES


@dataclasses.dataclass(frozen=True)
class DeferredAction:
    action_id: str
    reason: str  # one of DEFER_REASONS


@dataclasses.dataclass(frozen=True)
class RepairRun:
    applied: tuple[AppliedStep, ...]
    deferred: tuple[DeferredAction, ...]
    iterations: int


# ── consuming the 005 render gate ─────────────────────────────────────────────
def select_candidates(
    decisions: "Sequence[tuple[RepairAction, str]]",
) -> list[RepairAction]:
    """Keep render (-> repair) and demote (-> source-refresh) candidates; skip
    suppress. ``decisions`` pairs each candidate action with its 005
    ``render_decision`` outcome."""
    return [a for a, d in decisions if d in (_rg.RENDER, _rg.DEMOTE)]


# ── dependency ordering (Kahn; cycle detection) ───────────────────────────────
def order_actions(
    actions: "Sequence[RepairAction]",
) -> "tuple[list[RepairAction], set[str]]":
    """Topologically order ``actions`` so each prerequisite precedes its
    dependent. Dependencies pointing outside the candidate set are treated as
    already satisfied. Returns ``(ordered, cyclic_ids)``; actions caught in a
    cycle are excluded from ``ordered`` and named in ``cyclic_ids``."""
    by_id = {a.id: a for a in actions}
    ids = set(by_id)
    deps_in = {a.id: [d for d in a.depends_on if d in ids] for a in actions}
    indeg = {aid: len(ds) for aid, ds in deps_in.items()}
    dependents: dict[str, list[str]] = {aid: [] for aid in ids}
    for aid, ds in deps_in.items():
        for d in ds:
            dependents[d].append(aid)

    ready = sorted(aid for aid, deg in indeg.items() if deg == 0)
    ordered: list[RepairAction] = []
    while ready:
        n = ready.pop(0)
        ordered.append(by_id[n])
        for m in sorted(dependents[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
                ready.sort()
    cyclic = ids - {a.id for a in ordered}
    return ordered, cyclic


# ── the fixpoint loop ─────────────────────────────────────────────────────────
def _resolved(action: RepairAction, live_state: Mapping[str, Any]) -> bool:
    return _ar.evaluate_clears_when(action.clears_when, live_state)


def run_fixpoint(
    actions: "Sequence[RepairAction]",
    live_state: Mapping[str, Any],
    *,
    apply_fn: Callable[[RepairAction, Mapping[str, Any]], Mapping[str, Any]],
    run_tier: str,
    max_iterations: int | None = None,
) -> RepairRun:
    """Drive ``actions`` to a fixpoint against ``live_state``.

    Each iteration applies every currently-eligible auto_safe action (in
    dependency order), recomputes the state via ``apply_fn``, and re-plans. An
    action is eligible iff it is auto_safe-runnable at ``run_tier`` (F001) and all
    its still-live prerequisites have cleared. Stops when no eligible action
    remains. Returns the applied steps (each round-trip verified) and the deferred
    actions with their reason.
    """
    cyclic = order_actions(actions)[1]
    applied_ids: set[str] = set()
    applied: list[AppliedStep] = []
    state: Mapping[str, Any] = live_state
    cap = max_iterations if max_iterations is not None else len(list(actions)) + 1

    iterations = 0
    while True:
        iterations += 1
        # Live = not yet applied, not in a cycle, predicate still unresolved.
        live = [
            a
            for a in actions
            if a.id not in applied_ids
            and a.id not in cyclic
            and not _resolved(a, state)
        ]
        live_ids = {a.id for a in live}
        ordered, _ = order_actions(live)

        batch: list[RepairAction] = []
        for a in ordered:
            if not _rs.is_runnable_at(a, run_tier):
                continue  # safety tier — deferred after the loop
            # A prerequisite that is still live (unrun/unresolved) blocks this
            # action; it must run on a later pass once the prereq clears.
            if any(d in live_ids for d in a.depends_on):
                continue
            batch.append(a)

        if not batch:
            break

        for a in batch:
            state = apply_fn(a, state)
            followups = (
                [b for b in live if a.id in b.depends_on]
                if a.resolution_class == _ar.RESOLUTION_CHAINED
                else ()
            )
            outcome = _rv.verify_round_trip(a, state, chained_followups=followups)
            applied_ids.add(a.id)
            applied.append(AppliedStep(a.id, outcome))

        if iterations > cap:  # defensive backstop; structural termination precedes this
            break

    deferred = _classify_deferred(actions, applied_ids, state, cyclic, run_tier)
    return RepairRun(tuple(applied), tuple(deferred), iterations)


def _classify_deferred(
    actions: "Sequence[RepairAction]",
    applied_ids: set[str],
    state: Mapping[str, Any],
    cyclic: set[str],
    run_tier: str,
) -> list[DeferredAction]:
    """Label every still-unresolved, un-applied action with why it was deferred:
    a cycle, a safety tier it can never auto-run under, or an unsatisfiable
    dependency."""
    out: list[DeferredAction] = []
    for a in actions:
        if a.id in applied_ids or _resolved(a, state):
            continue
        if a.id in cyclic:
            out.append(DeferredAction(a.id, DEFER_CYCLE))
        elif not _rs.is_runnable_at(a, run_tier):
            out.append(DeferredAction(a.id, DEFER_SAFETY))
        else:
            # auto_safe-runnable but it never became eligible -> a prerequisite
            # never cleared (itself a human/blocked/cyclic card).
            out.append(DeferredAction(a.id, DEFER_DEPENDENCY))
    return out
