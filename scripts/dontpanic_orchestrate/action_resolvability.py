"""Plan 2026-06-04-001 F001 — ActionItem resolvability contract.

An operator action is only honest if ``condition -> action/evidence -> recompute
-> item clears`` round-trips. This module is the contract that makes that
checkable:

* :class:`ClearsWhen` — a reference into a CLOSED registry of named, pure
  predicates (+ bound params). NO expression DSL: every clears_when names a
  predicate the registry knows, so the set of resolvable conditions is
  enumerable and the F005 invariant test can iterate it (operator decision
  D002.1).
* :data:`RESOLUTION_CLASSES` — the four-value resolution taxonomy (D002.3):
    - ``command_resolvable`` — running ``exact_command`` flips clears_when.
    - ``chained``            — a step in a sequence; running it may surface the
                               next action.
    - ``operator_attested``  — no command can clear it; it clears when matching
                               EVIDENCE appears (e.g. a credential pasted).
    - ``blocked_external``   — nothing the operator can do right now; clears only
                               when an external precondition changes.
* :func:`evaluate_clears_when` — pure: returns True iff the justifying condition
  is GONE (so the item should be suppressed). Unknown predicate names RAISE,
  rather than silently evaluating false — a typo'd predicate must never let a
  non-resolving item slip through.

Predicates take ``(params, live_state)`` and return the RESOLVED boolean (True =
condition gone = drop the item). ``live_state`` is a plain Mapping here; plan
F002 formalizes how it is assembled at fleet scope.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any

# ── resolution classes (D002.3 — keep four) ──────────────────────────────────
RESOLUTION_COMMAND_RESOLVABLE = "command_resolvable"
RESOLUTION_CHAINED = "chained"
RESOLUTION_OPERATOR_ATTESTED = "operator_attested"
RESOLUTION_BLOCKED_EXTERNAL = "blocked_external"

RESOLUTION_CLASSES: frozenset[str] = frozenset(
    {
        RESOLUTION_COMMAND_RESOLVABLE,
        RESOLUTION_CHAINED,
        RESOLUTION_OPERATOR_ATTESTED,
        RESOLUTION_BLOCKED_EXTERNAL,
    }
)

# Resolution classes that CANNOT be cleared by running a command — they clear on
# evidence (operator_attested) or an external change (blocked_external). The F005
# invariant test uses this to allow such items to opt out of command-clears.
NON_COMMAND_RESOLUTION_CLASSES: frozenset[str] = frozenset(
    {RESOLUTION_OPERATOR_ATTESTED, RESOLUTION_BLOCKED_EXTERNAL}
)

# Plan-status set whose gates are still actionable (D002.4). Gate/approve cards
# emit only for these; draft is pre-lock (gates not active yet), completed and
# abandoned are terminal.
LIVE_BUT_UNFINISHED_STATUSES: frozenset[str] = frozenset(
    {"active", "ready_for_audit", "in_audit", "blocked"}
)


def validate_resolution_class(value: str) -> None:
    """Raise ValueError unless *value* is one of the four resolution classes."""
    if value not in RESOLUTION_CLASSES:
        raise ValueError(
            f"resolution_class={value!r} not in {sorted(RESOLUTION_CLASSES)}"
        )


@dataclasses.dataclass(frozen=True)
class ClearsWhen:
    """Reference into the closed predicate registry + bound params.

    ``predicate`` MUST be a registered name (see :func:`register_predicate`);
    ``params`` are the per-item bindings the predicate needs (e.g. ``plan_id``).
    """

    predicate: str
    params: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.predicate not in _PREDICATE_REGISTRY:
            raise ValueError(
                f"ClearsWhen.predicate={self.predicate!r} is not registered; "
                f"known: {sorted(_PREDICATE_REGISTRY)}"
            )
        if not isinstance(self.params, Mapping):
            raise TypeError("ClearsWhen.params must be a Mapping")

    def to_dict(self) -> dict[str, Any]:
        return {"predicate": self.predicate, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ClearsWhen":
        return cls(predicate=d["predicate"], params=dict(d.get("params") or {}))


# ── closed predicate registry ─────────────────────────────────────────────────
_Predicate = Callable[[Mapping[str, Any], Mapping[str, Any]], bool]
_PREDICATE_REGISTRY: dict[str, _Predicate] = {}


def register_predicate(name: str) -> Callable[[_Predicate], _Predicate]:
    """Register a named clears_when predicate. Duplicate names raise."""

    def _wrap(fn: _Predicate) -> _Predicate:
        if name in _PREDICATE_REGISTRY:
            raise ValueError(f"clears_when predicate {name!r} already registered")
        _PREDICATE_REGISTRY[name] = fn
        return fn

    return _wrap


def registered_predicates() -> frozenset[str]:
    """The closed set of predicate names — F005 iterates this."""
    return frozenset(_PREDICATE_REGISTRY)


def evaluate_clears_when(
    clears_when: ClearsWhen | None, live_state: Mapping[str, Any]
) -> bool:
    """Return True iff the justifying condition is GONE (item should be dropped).

    A ``None`` clears_when is treated as "never auto-clears" (False) — the item
    has not declared a resolution predicate, so recompute cannot suppress it.
    An unknown predicate RAISES (a typo must not silently pass).
    """
    if clears_when is None:
        return False
    fn = _PREDICATE_REGISTRY.get(clears_when.predicate)
    if fn is None:  # defensive: ClearsWhen.__post_init__ already guards this
        raise KeyError(f"unknown clears_when predicate {clears_when.predicate!r}")
    return bool(fn(clears_when.params, live_state))


# ── seed predicates (mechanism proof; F002/F003/F004 wire live assembly) ──────
@register_predicate("gate_no_longer_actionable")
def _gate_no_longer_actionable(
    params: Mapping[str, Any], live_state: Mapping[str, Any]
) -> bool:
    """Gate/approve card is resolved (drop it) when the plan is NOT in the
    live-but-unfinished status set, OR the gate is already cleared.

    live_state expects:
      ``plan_status``  : {plan_id -> status}
      ``cleared_gates``: {plan_id -> set/list of cleared gate names}
    """
    plan_id = params["plan_id"]
    gate = params["gate"]
    status = (live_state.get("plan_status") or {}).get(plan_id)
    if status not in LIVE_BUT_UNFINISHED_STATUSES:
        return True  # plan terminal / pre-lock → no gate card
    cleared = (live_state.get("cleared_gates") or {}).get(plan_id) or ()
    return gate in cleared


@register_predicate("install_snapshot_fresh")
def _install_snapshot_fresh(
    params: Mapping[str, Any], live_state: Mapping[str, Any]
) -> bool:
    """Global reconcile readiness is resolved when the install snapshot is
    present AND the capabilities status cache is fresh.

    live_state expects ``reconcile``: {snapshot_present: bool, cache_fresh: bool}.
    """
    rec = live_state.get("reconcile") or {}
    return bool(rec.get("snapshot_present")) and bool(rec.get("cache_fresh"))
