"""2a-F004 — degraded-honesty + cross-surface agreement checker (pure).

Consumes the MERGED 2a-core EvidenceRef vocabulary / closed enums (D008/D009).
The checker reads {data_source, availability, data_provenance, consumer_family,
evidence_class} off EvidenceRef-like views and reports a tri-state honesty
verdict (D015), per-(objective, data_source) cross-surface disagreement (D006),
and an evidence-set-level satisfaction discriminator (D005/D011).

Pinned acceptance cases + the three round-3 implementation obligations (D018):
  obligation 1 — unlisted allowed_degraded_modes value is its own rejection test
  obligation 2 — multi-objective cross-surface isolation
  obligation 3 — the plan journey declares BOTH families in required_data_sources
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))  # dontpanic_orchestrate on path
# 2a-core models dir, same resolution as the F002 tests
for _c in (
    HERE.parents[3] / "claude" / "shared" / "schemas" / "v1.0" / "models",
    HERE.parents[3] / ".claude" / "shared" / "schemas" / "v1.0" / "models",
):
    if _c.is_dir():
        sys.path.insert(0, str(_c))
        break

import experience_readiness as er  # noqa: E402
import experience_readiness_honesty as h  # noqa: E402

SC, EC = er.SurfaceClass, er.EvidenceClass
Fam, Prov, Avail = er.SurfaceFamily, er.DataProvenance, er.Availability
Verdict = h.HonestyVerdict


def ref(data_source, family, availability, *, provenance="real",
        evidence_class=None, degraded_mode=None, objective="checkout"):
    """An EvidenceRef-like view (strings, as the real EvidenceRef stores)."""
    fam = family.value if isinstance(family, Fam) else family
    sc = (SC.agent_mcp_tool if fam == "agent" else SC.read_only_ui).value
    return SimpleNamespace(
        data_source=data_source,
        consumer_family=fam,
        availability=availability.value if isinstance(availability, Avail) else availability,
        data_provenance=provenance.value if isinstance(provenance, Prov) else provenance,
        evidence_class=(evidence_class.value if isinstance(evidence_class, EC)
                        else evidence_class),
        degraded_mode=degraded_mode,
        surface_class=sc,
        objective=objective,
    )


def exec_ref(family, *, objective="checkout", data_source="journey_execution"):
    """A real, available journey-EXECUTION EvidenceRef (D005/D011).

    Journey-level proof the flow ran — NOT an availability claim about a degraded
    dependency, so it carries its own data_source key, distinct from the
    required dependency sources.
    """
    ec = EC.tool_call_transcript if (family == "agent" or family is Fam.agent) else EC.screenshot
    return ref(data_source, family, Avail.available, provenance="real",
               evidence_class=ec, objective=objective)


BOTH = frozenset({Fam.human, Fam.agent})
AGENT = frozenset({Fam.agent})
RDS = h.RequiredDataSource


# --- D011: closed execution-class set is consumed from 2a-core ----------------

def test_execution_classes_are_the_closed_2a_core_subset_d011():
    assert h.EXECUTION_CLASSES == {
        EC.screenshot, EC.recording, EC.journey_walk, EC.terminal_transcript,
        EC.tool_call_transcript, EC.cli_transcript, EC.contract_check,
    }
    # the shared/error classes are NOT execution-proving
    for ec in (EC.idempotency, EC.rollback, EC.structured_error):
        assert ec not in h.EXECUTION_CLASSES


# --- acceptance case 1: honest degradation passes -----------------------------

def test_honest_degradation_all_required_families_down_is_honest():
    sources = [RDS("payments", BOTH)]
    refs = [
        ref("payments", Fam.human, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
        ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
        exec_ref(Fam.agent),  # real execution present
    ]
    res = h.check_degraded_honesty(sources, {"payments": {"provider_down"}}, refs)
    assert res.verdict is Verdict.honest
    assert res.satisfied is True
    assert res.disagreements == []


# --- acceptance case 2: masking is degraded_dishonest (D003) -------------------

def test_one_family_masking_while_other_down_is_degraded_dishonest_d003():
    sources = [RDS("payments", BOTH)]
    refs = [
        ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
        ref("payments", Fam.human, Avail.available),  # masks the outage
    ]
    res = h.check_degraded_honesty(sources, {"payments": {"provider_down"}}, refs)
    assert res.verdict is Verdict.degraded_dishonest


def test_neither_family_test_is_insufficient_only_masking_trips_it():
    # both honestly down -> NOT dishonest (guards against a 'neither family' shortcut)
    sources = [RDS("payments", BOTH)]
    refs = [
        ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
        ref("payments", Fam.human, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
    ]
    res = h.check_degraded_honesty(sources, {"payments": {"provider_down"}}, refs)
    assert res.verdict is not Verdict.degraded_dishonest


# --- OBLIGATION 1 (D018): unlisted allowed_degraded_modes rejected (D004) ------

def test_unlisted_degraded_mode_is_degraded_dishonest_obligation1():
    sources = [RDS("payments", AGENT)]
    refs = [
        ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="silent_timeout"),  # NOT in allowed list
    ]
    res = h.check_degraded_honesty(sources, {"payments": {"provider_down"}}, refs)
    assert res.verdict is Verdict.degraded_dishonest
    assert any(r.data_source == "payments"
               and h.DishonestReason.mode_not_allowed in r.dishonest_reasons
               for r in res.sources)


def test_listed_degraded_mode_is_honest_obligation1_complement():
    sources = [RDS("payments", AGENT)]
    refs = [
        ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
        exec_ref(Fam.agent),
    ]
    res = h.check_degraded_honesty(sources, {"payments": {"provider_down"}}, refs)
    assert res.verdict is Verdict.honest


# --- acceptance case 3 + D005/D011: typed-skip never satisfies -----------------

def test_journey_covered_only_by_typed_skips_is_not_satisfied():
    sources = [RDS("payments", AGENT)]
    refs = [  # only unavailable/degraded tuples, no real execution
        ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
    ]
    res = h.check_degraded_honesty(sources, {"payments": {"provider_down"}}, refs)
    assert res.satisfied is False  # honest about being down, but not a success


# --- acceptance case 4: the discriminator (D005) ------------------------------

def test_discriminator_same_unavailable_tuple_with_vs_without_real_execution():
    sources = [RDS("payments", AGENT)]
    skip = ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
               degraded_mode="provider_down")
    allowed = {"payments": {"provider_down"}}
    without = h.check_degraded_honesty(sources, allowed, [skip])
    with_exec = h.check_degraded_honesty(sources, allowed, [skip, exec_ref(Fam.agent)])
    assert without.satisfied is False
    assert with_exec.satisfied is True
    # the SAME unavailable tuple is honest either way (D005)
    assert without.verdict is not Verdict.degraded_dishonest
    assert with_exec.verdict is Verdict.honest


def test_seeded_execution_ref_does_not_satisfy():
    sources = [RDS("payments", AGENT)]
    seeded = ref("payments", Fam.agent, Avail.available, provenance="seeded",
                 evidence_class=EC.tool_call_transcript)
    res = h.check_degraded_honesty(sources, {}, [seeded])
    assert res.satisfied is False  # seeded masks readiness


# --- acceptance case 5: cross-surface disagreement (D006) ---------------------

def test_ui_available_vs_api_unavailable_is_cross_surface_disagreement():
    sources = [RDS("inventory", BOTH)]
    refs = [
        ref("inventory", Fam.human, Avail.available),            # UI promises available
        ref("inventory", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),                       # API says unavailable
    ]
    res = h.check_degraded_honesty(sources, {"inventory": {"provider_down"}}, refs)
    assert "inventory" in res.disagreements


# --- OBLIGATION 2 (D018): multi-objective cross-surface isolation --------------

def test_multi_objective_isolation_no_cross_contamination_obligation2():
    sources = [RDS("inventory", BOTH)]
    allowed = {"inventory": {"provider_down"}}
    refs = [
        # objective A: genuine disagreement on the shared data_source
        ref("inventory", Fam.human, Avail.available, objective="A"),
        ref("inventory", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down", objective="A"),
        # objective B: same data_source key, both agree available (clean)
        ref("inventory", Fam.human, Avail.available, objective="B"),
        ref("inventory", Fam.agent, Avail.available, objective="B"),
        exec_ref(Fam.agent, objective="B"),
    ]
    results = h.check_objectives({"A": [r for r in refs if r.objective == "A"],
                                  "B": [r for r in refs if r.objective == "B"]},
                                 sources, allowed)
    assert "inventory" in results["A"].disagreements
    # B must NOT inherit A's disagreement despite sharing the data_source key
    assert results["B"].disagreements == []


# --- D012: deterministic reduction --------------------------------------------

def test_any_unavailable_dominates_reduction_d012():
    sources = [RDS("payments", AGENT)]
    refs = [
        ref("payments", Fam.agent, Avail.available),
        ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
    ]
    res = h.check_degraded_honesty(sources, {"payments": {"provider_down"}}, refs)
    # available + unavailable for the same key/family = self-inconsistent -> dishonest
    assert res.verdict is Verdict.degraded_dishonest
    assert any(h.DishonestReason.conflict in r.dishonest_reasons for r in res.sources)


def test_pure_unavailable_reduces_to_unavailable_degraded_d012():
    sources = [RDS("payments", AGENT)]
    refs = [
        ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
        ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
    ]
    res = h.check_degraded_honesty(sources, {"payments": {"provider_down"}}, refs)
    fam_state = next(r for r in res.sources if r.data_source == "payments").families[Fam.agent]
    assert fam_state.availability is Avail.unavailable
    assert fam_state.provenance is Prov.degraded
    assert fam_state.conflict is False


# --- D007 human-compat path + D013/D015 tri-state -----------------------------

def test_typed_human_unavailable_label_is_consumed_d007():
    sources = [RDS("payments", BOTH)]
    refs = [
        ref("payments", Fam.human, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),  # human honest label, typed
        ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
        exec_ref(Fam.agent),
    ]
    res = h.check_degraded_honesty(sources, {"payments": {"provider_down"}}, refs)
    assert res.verdict is Verdict.honest  # human label consumed, not ignored


def test_untyped_required_human_family_is_pending_not_honest_d015():
    sources = [RDS("payments", BOTH)]
    refs = [  # only the agent family is typed-down; human family has NO evidence
        ref("payments", Fam.agent, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
    ]
    res = h.check_degraded_honesty(sources, {"payments": {"provider_down"}}, refs)
    assert res.verdict is Verdict.human_not_yet_typed_pending
    # pending is NOT a pass and NOT dishonest
    assert res.verdict is not Verdict.honest
    assert res.verdict is not Verdict.degraded_dishonest


def test_untyped_required_agent_family_when_down_is_dishonest_not_pending():
    # the agent family is the enforced one: omission while another family degrades = mask
    sources = [RDS("payments", BOTH)]
    refs = [
        ref("payments", Fam.human, Avail.unavailable, provenance="degraded",
            degraded_mode="provider_down"),
        # NO agent ref at all
    ]
    res = h.check_degraded_honesty(sources, {"payments": {"provider_down"}}, refs)
    assert res.verdict is Verdict.degraded_dishonest


# --- OBLIGATION 3 (D018): the plan journey declares BOTH families --------------

def test_plan_journey_required_data_sources_declares_both_families_obligation3():
    """The honesty contract for THIS plan's journey must require both families so
    an implementation cannot satisfy the checker while covering only one."""
    journey = h.plan_journey_required_sources()
    assert journey, "plan journey must declare at least one required data_source"
    assert all(rds.required_families == BOTH for rds in journey), (
        "every plan-journey data_source must require BOTH human and agent families")
