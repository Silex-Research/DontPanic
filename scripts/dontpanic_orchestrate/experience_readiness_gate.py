"""2b (plan 2026-06-14-002) — close-time consumer-outcome enforcement gate (pure).

Deterministic gate that decides whether a plan's active->completed flip is
blocked by an unproven consumer-facing outcome. Consumes the MERGED 2a-core
(check_journey) + 2a-F004 (check_degraded_honesty) verdicts; never redefines
their schema. Pure / no I/O — completion_gate.close_plan calls
evaluate_consumer_outcome_gate(...) BEFORE the flip and independently of the
codex F0 cluster triage (D021).

Rule summary (see features.json F001 acceptance + decisions D021-D053):
  activation (D022): active iff opted_in OR has_consumer_journey OR goal_type in
    PRODUCT_CLASS_GOALS OR product_metadata is product-class.
  product_metadata (D041/D044/D048): parse_product_metadata(delivery_class) —
    recognized product values -> product_class; substrate values -> substrate;
    an UNRECOGNIZED NON-EMPTY value fails closed to product_class (anti-typo);
    ABSENT (None) -> no signal (does not activate via metadata).
  posture (D030/D031/D043/D049): block iff active AND has_consumer_journey AND
    >=1 outcome is UNPROVEN-undeferred-undispositioned; advisory for the two
    no-consumer-journey cases (product-class -> no_consumer_journey_declared;
    substrate+opt_in -> substrate_opt_in_advisory) and for a journey-bearing
    plan whose only outstanding outcomes are pending; else noop. Block NEVER
    keys on goal_type/product_metadata alone.
  outcome tri-state (D034/D035/D051): satisfied / unproven (blocks unless
    structurally deferred or dispositioned) / pending. PENDING is advisory ONLY
    when another required family in the journey is satisfied; a human-only (or
    any no-satisfied-family) journey whose human family is not_yet_typed/unproven
    is UNPROVEN, never silently advisory.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Sequence

# Resolve the merged 2a-core enums (same path strategy as the F004 module).
for _c in (
    Path(__file__).resolve().parents[2] / "claude" / "shared" / "schemas" / "v1.0" / "models",
    Path(__file__).resolve().parents[2] / ".claude" / "shared" / "schemas" / "v1.0" / "models",
):
    if (_c / "experience_readiness.py").is_file():
        sys.path.insert(0, str(_c))
        break

import experience_readiness as er  # noqa: E402

# D022 product-class goal types.
PRODUCT_CLASS_GOALS: frozenset = frozenset({"parity", "new_feature", "migration", "incident"})

# D041 delivery_class closed enum partition.
_PRODUCT_DELIVERY = frozenset({"product", "migration", "readiness", "ux", "consumer_facing"})
_SUBSTRATE_DELIVERY = frozenset({"substrate", "mechanical", "infra", "refactor"})


class ProductClass(Enum):
    product_class = "product_class"
    substrate = "substrate"


class OutcomeClass(Enum):
    satisfied = "satisfied"
    unproven = "unproven"
    pending = "pending"


class Posture(Enum):
    block = "block"
    advisory = "advisory"
    noop = "noop"


# gap_class taxonomy (D039/D044/D052) — all share the output shape below.
GAP_CONSUMER_OUTCOME_UNPROVEN = "consumer_outcome_unproven"   # blocking severity
GAP_CONSUMER_OUTCOME_PENDING = "consumer_outcome_pending"     # advisory, never blocks
GAP_NO_CONSUMER_JOURNEY = "no_consumer_journey_declared"      # advisory, never blocks
GAP_SUBSTRATE_OPT_IN_ADVISORY = "substrate_opt_in_advisory"   # advisory, never blocks

_NON_BLOCKING_GAPS = frozenset({
    GAP_CONSUMER_OUTCOME_PENDING, GAP_NO_CONSUMER_JOURNEY, GAP_SUBSTRATE_OPT_IN_ADVISORY,
})


@dataclass(frozen=True)
class GateFinding:
    gap_class: str
    severity: str           # "blocking" | "advisory"
    journey: str | None
    consumer: str | None
    note: str

    @property
    def blocks(self) -> bool:
        return self.gap_class not in _NON_BLOCKING_GAPS and self.severity == "blocking"


@dataclass(frozen=True)
class JourneyOutcome:
    """A per-(journey, consumer) outcome the caller computed from the merged
    2a checkers (see classify_outcome). deferred = a structured non_goal entry
    names {journey, consumer}; dispositioned = a consumer_outcome_dispositions[]
    record covers it (D016 — prose never satisfies, so callers pass these as
    booleans derived from STRUCTURED records only)."""
    journey: str
    consumer: str             # "human" | "agent" | "both"
    outcome: OutcomeClass
    deferred: bool = False
    dispositioned: bool = False


@dataclass
class GateResult:
    posture: Posture
    blocks: bool
    findings: list = field(default_factory=list)


# --- D041/D044/D048: product_metadata parsing -------------------------------

def parse_product_metadata(delivery_class: str | None) -> ProductClass | None:
    """ABSENT (None) -> None (no signal); recognized -> its class; UNRECOGNIZED
    NON-EMPTY (typo) -> product_class fail-closed (D044)."""
    if delivery_class is None:
        return None
    v = delivery_class.strip().lower()
    if v == "":
        return None
    if v in _PRODUCT_DELIVERY:
        return ProductClass.product_class
    if v in _SUBSTRATE_DELIVERY:
        return ProductClass.substrate
    return ProductClass.product_class  # fail-closed: a typo never weakens activation


# --- D022: activation --------------------------------------------------------

def experience_readiness_active(
    goal_type: str | None,
    opted_in: bool,
    has_consumer_journey: bool,
    product_metadata: ProductClass | None,
) -> bool:
    return bool(
        opted_in
        or has_consumer_journey
        or (goal_type in PRODUCT_CLASS_GOALS)
        or (product_metadata is ProductClass.product_class)
    )


# --- D034/D035/D051: per-journey outcome classification ----------------------

def classify_outcome(
    consumer: str,
    *,
    typing_verdict,            # er-typing JourneyVerdict (.value in {satisfied, agent_satisfied_human_pending, unsatisfied})
    honesty_verdict,           # 2a-F004 HonestyVerdict (.value in {honest, degraded_dishonest, human_not_yet_typed_pending})
    real_execution: bool,      # HonestyResult.satisfied
    other_family_satisfied: bool,
) -> OutcomeClass:
    """Map the merged tri-state verdicts to the gate outcome (D034/D035/D051).

    PENDING is advisory ONLY when another required family is satisfied; otherwise
    a pending/not_yet_typed family is UNPROVEN (closes the human-only auto-pass
    hole). degraded_dishonest or unsatisfied -> unproven. satisfied requires
    typing satisfied AND honesty honest AND a real (non-seeded) execution.
    """
    tv = typing_verdict.value if hasattr(typing_verdict, "value") else str(typing_verdict)
    hv = honesty_verdict.value if hasattr(honesty_verdict, "value") else str(honesty_verdict)

    if tv == "unsatisfied" or hv == "degraded_dishonest":
        return OutcomeClass.unproven
    if tv in ("agent_satisfied_human_pending",) or hv == "human_not_yet_typed_pending":
        return OutcomeClass.pending if other_family_satisfied else OutcomeClass.unproven
    if tv == "satisfied" and hv == "honest" and real_execution:
        return OutcomeClass.satisfied
    # satisfied/honest but no real execution (seeded / substrate-only / typed-skip-only) -> unproven
    return OutcomeClass.unproven


# --- D030/D031/D043/D049: posture + the deterministic gate --------------------

def _effective(o: JourneyOutcome) -> bool:
    """True if this outcome still counts (not structurally deferred/dispositioned)."""
    return not (o.deferred or o.dispositioned)


def evaluate_consumer_outcome_gate(
    goal_type: str | None,
    opted_in: bool,
    product_metadata: ProductClass | None,
    journeys: Sequence[JourneyOutcome],
) -> GateResult:
    """Deterministic pre-flip gate. blocks==True forbids the active->completed flip."""
    has_consumer_journey = len(journeys) > 0
    active = experience_readiness_active(goal_type, opted_in, has_consumer_journey, product_metadata)

    if not active:
        return GateResult(posture=Posture.noop, blocks=False, findings=[])

    if has_consumer_journey:
        findings: list[GateFinding] = []
        unproven = [o for o in journeys if o.outcome is OutcomeClass.unproven and _effective(o)]
        pending = [o for o in journeys if o.outcome is OutcomeClass.pending and _effective(o)]
        for o in unproven:
            findings.append(GateFinding(GAP_CONSUMER_OUTCOME_UNPROVEN, "blocking", o.journey,
                                        o.consumer, "declared consumer outcome unproven, undeferred, undispositioned"))
        for o in pending:
            findings.append(GateFinding(GAP_CONSUMER_OUTCOME_PENDING, "advisory", o.journey,
                                        o.consumer, "human-side typing deferred; agent family satisfied (D035/D051)"))
        if unproven:
            return GateResult(posture=Posture.block, blocks=True, findings=findings)
        if pending:
            return GateResult(posture=Posture.advisory, blocks=False, findings=findings)
        return GateResult(posture=Posture.noop, blocks=False, findings=findings)

    # active, NO consumer journey (D031/D030/D052)
    is_product = (goal_type in PRODUCT_CLASS_GOALS) or (product_metadata is ProductClass.product_class)
    if is_product:
        return GateResult(posture=Posture.advisory, blocks=False, findings=[
            GateFinding(GAP_NO_CONSUMER_JOURNEY, "advisory", None, None,
                        "product-class plan declares no consumer journey (D031)")])
    # substrate activated solely via opt_in
    return GateResult(posture=Posture.advisory, blocks=False, findings=[
        GateFinding(GAP_SUBSTRATE_OPT_IN_ADVISORY, "advisory", None, None,
                    "substrate plan opted in for visibility, no consumer journey (D030/D052)")])
