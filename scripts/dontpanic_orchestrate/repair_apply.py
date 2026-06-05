"""Plan 2026-06-04-006 F004 — tiered opt-in local apply.

`apply_repairs` is the executor behind ``dontpanic repair apply``. It runs the
F002 fixpoint with a REAL side effect injected as ``effect_fn``: for each eligible
auto_safe action (per the operator's run tier) it executes the effect, recomputes
``live_state`` via ``recompute_fn``, and round-trip verifies the targeted card
with F005. The runner never infers safety and never crosses the mutation boundary
silently:

  * Tier gating (F001 ``is_runnable_at``) — ``--safe-derived-state`` runs ONLY
    apply_tier=derived_state actions; ``--safe --confirm`` additionally runs the
    confirmed_local allowlist. A confirmed_local action is deferred under the
    derived tier, never executed.
  * Forbidden-kind guard (defense in depth) — an action whose kind is in
    :data:`repair_safety.FORBIDDEN_KINDS` is REFUSED at execution regardless of
    flag. A producer that mis-asserted auto_safe over a forbidden kind is surfaced
    in ``refused`` (not silently dropped).
  * Execution failure — if ``effect_fn`` raises, the action is refused + logged
    and the run CONTINUES; one broken effect never aborts the batch.
  * Round-trip verification — every executed action is classified cleared /
    chained / human_required / unchanged (F005); an unchanged card is the defect
    signal. An applied action is recorded and never retried, so the loop
    terminates structurally.

Side effect (``effect_fn``) and state recompute (``recompute_fn``) are injected,
so this module is pure and unit-testable; the CLI supplies the real ones.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import action_resolvability as _ar
from . import repair_planner as _rp
from . import repair_safety as _rs
from . import repair_verify as _rv

# ── refusal reasons (an action the runner declined to apply / could not apply) ──
REFUSED_FORBIDDEN_KIND = "forbidden_kind"  # forbidden kind, refused regardless of flag
REFUSED_EXECUTION_FAILED = "execution_failed"  # effect_fn raised; skipped + logged
REFUSAL_REASONS: frozenset[str] = frozenset(
    {REFUSED_FORBIDDEN_KIND, REFUSED_EXECUTION_FAILED}
)


@dataclasses.dataclass(frozen=True)
class ApplyStep:
    action_id: str
    outcome: str  # one of repair_verify.OUTCOMES


@dataclasses.dataclass(frozen=True)
class ApplyRefusal:
    action_id: str
    reason: str  # one of REFUSAL_REASONS
    detail: str | None = None


@dataclasses.dataclass(frozen=True)
class ApplyReport:
    applied: tuple[ApplyStep, ...]
    refused: tuple[ApplyRefusal, ...]
    deferred: tuple[_rp.DeferredAction, ...]
    iterations: int


def _resolved(action: Any, live_state: Mapping[str, Any]) -> bool:
    return _ar.evaluate_clears_when(getattr(action, "clears_when", None), live_state)


def apply_repairs(
    actions: "Sequence[_rp.RepairAction]",
    live_state: Mapping[str, Any],
    *,
    run_tier: str,
    effect_fn: Callable[[_rp.RepairAction], None],
    recompute_fn: Callable[[], Mapping[str, Any]],
    max_iterations: int | None = None,
) -> ApplyReport:
    """Execute the eligible auto_safe batch for ``run_tier`` to a fixpoint.

    ``effect_fn(action)`` performs the action's real side effect; ``recompute_fn()``
    returns the fresh ``live_state`` after it. Returns the applied steps (each
    round-trip verified), the refused actions (forbidden / execution-failed), and
    the deferred actions (safety / dependency / cycle)."""
    cyclic = _rp.order_actions(actions)[1]
    applied_ids: set[str] = set()
    refused_ids: set[str] = set()
    applied: list[ApplyStep] = []
    refused: list[ApplyRefusal] = []
    state: Mapping[str, Any] = live_state
    cap = max_iterations if max_iterations is not None else len(list(actions)) + 1

    iterations = 0
    while True:
        iterations += 1
        live = [
            a
            for a in actions
            if a.id not in applied_ids
            and a.id not in refused_ids
            and a.id not in cyclic
            and not _resolved(a, state)
        ]
        live_ids = {a.id for a in live}
        ordered, _ = _rp.order_actions(live)

        batch: list[_rp.RepairAction] = []
        for a in ordered:
            # Execution-time forbidden guard (defense in depth over is_runnable_at).
            # Only surface a refusal when the producer ASSERTED auto_safe over a
            # forbidden kind — a plain human card just defers (safety) below.
            if _rs.is_forbidden_kind(a):
                if getattr(a, "safety_class", None) == _rs.AUTO_SAFE:
                    refused.append(ApplyRefusal(a.id, REFUSED_FORBIDDEN_KIND))
                    refused_ids.add(a.id)
                continue
            if not _rs.is_runnable_at(a, run_tier):
                continue  # safety tier — deferred after the loop
            if any(d in live_ids for d in a.depends_on):
                continue  # a still-live prerequisite blocks it
            batch.append(a)

        if not batch:
            break

        for a in batch:
            try:
                effect_fn(a)
            except Exception as exc:  # noqa: BLE001 — one bad effect must not abort the run
                refused.append(ApplyRefusal(a.id, REFUSED_EXECUTION_FAILED, detail=str(exc)))
                refused_ids.add(a.id)
                continue
            state = recompute_fn()
            followups = (
                [b for b in live if a.id in b.depends_on]
                if a.resolution_class == _ar.RESOLUTION_CHAINED
                else ()
            )
            outcome = _rv.verify_round_trip(a, state, chained_followups=followups)
            applied_ids.add(a.id)
            applied.append(ApplyStep(a.id, outcome))

        if iterations > cap:  # defensive backstop; structural termination precedes this
            break

    deferred = _classify_deferred(
        actions, applied_ids | refused_ids, state, cyclic, run_tier
    )
    return ApplyReport(tuple(applied), tuple(refused), tuple(deferred), iterations)


def _classify_deferred(
    actions: "Sequence[_rp.RepairAction]",
    done_ids: set[str],
    state: Mapping[str, Any],
    cyclic: set[str],
    run_tier: str,
) -> list[_rp.DeferredAction]:
    """Label every still-unresolved action that was neither applied nor refused."""
    out: list[_rp.DeferredAction] = []
    for a in actions:
        if a.id in done_ids or _resolved(a, state):
            continue
        if a.id in cyclic:
            out.append(_rp.DeferredAction(a.id, _rp.DEFER_CYCLE))
        elif not _rs.is_runnable_at(a, run_tier):
            out.append(_rp.DeferredAction(a.id, _rp.DEFER_SAFETY))
        else:
            out.append(_rp.DeferredAction(a.id, _rp.DEFER_DEPENDENCY))
    return out
