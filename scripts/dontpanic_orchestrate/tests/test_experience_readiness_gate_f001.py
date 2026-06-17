"""2b F001 — close-time consumer_outcome_gate (pure). Pins the acceptance's
deterministic test matrix incl. the D051 human-only constraint, D052 named
substrate advisory, and the D053 obligation cells.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
for _c in (HERE.parents[3] / "claude" / "shared" / "schemas" / "v1.0" / "models",
           HERE.parents[3] / ".claude" / "shared" / "schemas" / "v1.0" / "models"):
    if (_c / "experience_readiness.py").is_file():
        sys.path.insert(0, str(_c)); break

import experience_readiness_gate as g  # noqa: E402

PC = g.ProductClass
OC = g.OutcomeClass
P = g.Posture
JO = g.JourneyOutcome


def gate(goal_type=None, opted_in=False, product_metadata=None, journeys=()):
    return g.evaluate_consumer_outcome_gate(goal_type, opted_in, product_metadata, list(journeys))


def human(outcome, **kw): return JO("checkout", "human", outcome, **kw)
def agent(outcome, **kw): return JO("agent-flow", "agent", outcome, **kw)
def both(outcome, **kw): return JO("checkout", "both", outcome, **kw)


# --- parse_product_metadata: D041/D044/D048 absent vs invalid ----------------

@pytest.mark.parametrize("dc,exp", [
    ("product", PC.product_class), ("migration", PC.product_class), ("ux", PC.product_class),
    ("consumer_facing", PC.product_class), ("readiness", PC.product_class),
    ("substrate", PC.substrate), ("mechanical", PC.substrate), ("infra", PC.substrate),
    ("refactor", PC.substrate),
    (None, None), ("", None),                  # D048 absent -> no signal
    ("prodct", PC.product_class), ("nonsense", PC.product_class),  # D044 typo fail-closed
])
def test_parse_product_metadata_absent_recognized_invalid(dc, exp):
    assert g.parse_product_metadata(dc) is exp


# --- activation: D022 disjunction + absent-metadata noop (D048) --------------

def test_active_via_each_path_and_absent_metadata_is_inactive():
    assert g.experience_readiness_active(None, True, False, None) is True          # opt_in
    assert g.experience_readiness_active(None, False, True, None) is True          # journey
    assert g.experience_readiness_active("parity", False, False, None) is True     # goal
    assert g.experience_readiness_active("chore", False, False, PC.product_class) is True
    # absent metadata + non-product goal + no opt_in + no journey -> NOT active (D048)
    assert g.experience_readiness_active("chore", False, False, None) is False
    assert g.experience_readiness_active("chore", False, False, PC.substrate) is False


# --- classify_outcome tri-state incl D051 human-only constraint --------------

class _V:
    def __init__(self, v): self.value = v

def test_classify_satisfied_requires_typing_honest_and_real_execution():
    o = g.classify_outcome("agent", typing_verdict=_V("satisfied"), honesty_verdict=_V("honest"),
                           real_execution=True, other_family_satisfied=False)
    assert o is OC.satisfied

def test_classify_seeded_no_real_execution_is_unproven():
    o = g.classify_outcome("agent", typing_verdict=_V("satisfied"), honesty_verdict=_V("honest"),
                           real_execution=False, other_family_satisfied=False)
    assert o is OC.unproven

def test_classify_degraded_dishonest_is_unproven():
    o = g.classify_outcome("both", typing_verdict=_V("satisfied"), honesty_verdict=_V("degraded_dishonest"),
                           real_execution=True, other_family_satisfied=True)
    assert o is OC.unproven

def test_classify_pending_advisory_only_when_other_family_satisfied_D051():
    # consumer=both, agent satisfied, human not_yet_typed -> pending
    p = g.classify_outcome("both", typing_verdict=_V("agent_satisfied_human_pending"),
                           honesty_verdict=_V("human_not_yet_typed_pending"),
                           real_execution=True, other_family_satisfied=True)
    assert p is OC.pending
    # human-ONLY (no other satisfied family) not_yet_typed -> UNPROVEN, never advisory (D051)
    u = g.classify_outcome("human", typing_verdict=_V("agent_satisfied_human_pending"),
                           honesty_verdict=_V("human_not_yet_typed_pending"),
                           real_execution=False, other_family_satisfied=False)
    assert u is OC.unproven


# --- the acceptance test matrix (deterministic gate) -------------------------

def test_1_product_human_journey_unproven_blocks():
    r = gate("parity", journeys=[human(OC.unproven)])
    assert r.posture is P.block and r.blocks is True
    assert any(f.gap_class == g.GAP_CONSUMER_OUTCOME_UNPROVEN for f in r.findings)

def test_2_real_capture_satisfied_not_blocked():
    r = gate("parity", journeys=[human(OC.satisfied)])
    assert r.blocks is False and r.posture is P.noop

def test_4_structured_disposition_allows_close():
    r = gate("parity", journeys=[human(OC.unproven, dispositioned=True)])
    assert r.blocks is False

def test_5_substrate_no_journeys_not_opted_in_noop():
    r = gate("refactor", opted_in=False, journeys=[])
    assert r.posture is P.noop and r.blocks is False

def test_7_consumer_both_only_human_capture_agent_unproven_blocks():
    # agent family unproven on a consumer=both journey -> block
    r = gate("parity", journeys=[both(OC.unproven)])
    assert r.blocks is True

def test_9_gate_is_deterministic_independent_of_triage():
    # block decision is purely a function of inputs (no envelope/triage参与)
    r1 = gate("parity", journeys=[human(OC.unproven)])
    r2 = gate("parity", journeys=[human(OC.unproven)])
    assert r1.blocks == r2.blocks == True

def test_10_substrate_opt_in_with_unproven_journey_blocks():
    r = gate("refactor", opted_in=True, journeys=[human(OC.unproven)])
    assert r.blocks is True

def test_11_no_dodge_product_unproven_without_opt_in_blocks():
    r = gate("new_feature", opted_in=False, journeys=[human(OC.unproven)])
    assert r.blocks is True

def test_12_any_journey_bearing_plan_blocks_regardless_of_opt_in():
    assert gate("refactor", opted_in=False, journeys=[agent(OC.unproven)]).blocks is True

def test_13_product_no_journey_emits_no_consumer_journey_declared_advisory():
    r = gate("parity", journeys=[])
    assert r.posture is P.advisory and r.blocks is False
    assert any(f.gap_class == g.GAP_NO_CONSUMER_JOURNEY for f in r.findings)

def test_14_consumer_both_agent_proven_human_pending_advisory_not_blocked():
    r = gate("parity", journeys=[both(OC.pending)])
    assert r.posture is P.advisory and r.blocks is False
    assert any(f.gap_class == g.GAP_CONSUMER_OUTCOME_PENDING for f in r.findings)

def test_17_structured_non_goal_deferral_allows_close():
    r = gate("parity", journeys=[human(OC.unproven, deferred=True)])
    assert r.blocks is False

def test_19_substrate_opt_in_no_journeys_named_advisory_D052():
    r = gate("refactor", opted_in=True, journeys=[])
    assert r.posture is P.advisory and r.blocks is False
    f = [x for x in r.findings if x.gap_class == g.GAP_SUBSTRATE_OPT_IN_ADVISORY]
    assert f and f[0].blocks is False

def test_20_no_consumer_journey_finding_never_blocks():
    r = gate("parity", journeys=[])
    assert all(not f.blocks for f in r.findings)

# --- D051 obligation tests (27/28) -------------------------------------------

def test_27_human_only_not_yet_typed_blocks_not_pending():
    # a human-only journey whose family is not_yet_typed -> unproven outcome -> block
    r = gate("parity", journeys=[human(OC.unproven)])  # classify_outcome already maps human-only pending->unproven
    assert r.blocks is True
    assert all(f.gap_class != g.GAP_CONSUMER_OUTCOME_PENDING for f in r.findings)

def test_28_consumer_both_agent_unsatisfied_human_pending_blocks():
    # when agent is NOT satisfied, classify yields unproven (not pending) -> block
    o = g.classify_outcome("both", typing_verdict=_V("unsatisfied"),
                           honesty_verdict=_V("human_not_yet_typed_pending"),
                           real_execution=False, other_family_satisfied=False)
    assert o is OC.unproven
    assert gate("parity", journeys=[both(o)]).blocks is True

# --- D053 obligation: absent-metadata opt-in-only no-journey cell -------------

def test_d053_opt_in_only_no_journey_absent_metadata_substrate_advisory():
    # opt_in only, no journey, non-product goal, absent metadata -> active via opt_in,
    # no consumer journey, not product-class -> substrate_opt_in_advisory (never blocks)
    r = gate("chore", opted_in=True, product_metadata=None, journeys=[])
    assert r.posture is P.advisory and r.blocks is False
    assert any(f.gap_class == g.GAP_SUBSTRATE_OPT_IN_ADVISORY for f in r.findings)
