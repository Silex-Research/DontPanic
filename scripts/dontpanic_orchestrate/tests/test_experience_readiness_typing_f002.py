"""F002 — evidence-class typing rule + tri-state checker.

Explicit matrix (operator-pinned):
- read_only across all valid surface_class x consumer combinations
- consumer=both with single human surface and single agent surface
- mutation / qualitative / error_path requirement groups
- invalid tuple rejection
- typed-skip never satisfies
- per-(surface, group) result output
- one EvidenceRef cannot satisfy multiple surface groups
- agent_satisfied_human_pending only when all agent groups pass and only human
  groups are not_yet_typed
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))  # dontpanic_orchestrate on path

import experience_readiness_typing as t  # noqa: E402
import experience_readiness as er  # noqa: E402

SC, EC = er.SurfaceClass, er.EvidenceClass
CK, Cons = er.ClaimKind, er.Consumer
Status, Verdict = t.CheckStatus, t.JourneyVerdict


def ref(surface_class, evidence_class, *, provenance="real", availability="available",
        consumer_family=None):
    """An EvidenceRef-like view (strings, as the real EvidenceRef stores)."""
    fam = consumer_family or er.surface_family(SC(surface_class)).value
    return SimpleNamespace(
        surface_class=SC(surface_class).value,
        evidence_class=EC(evidence_class).value if evidence_class else None,
        data_provenance=provenance,
        availability=availability,
        consumer_family=fam,
    )


# --- read_only across all valid surface_class x consumer combos --------------

def _compatible_consumers(sc):
    fam = er.surface_family(sc)
    return ([Cons.human, Cons.both] if fam is er.SurfaceFamily.human
            else [Cons.agent, Cons.both])


def test_read_only_matrix_total_and_valid_for_every_surface_consumer():
    for sc in SC:
        for cons in _compatible_consumers(sc):
            groups = t.required_evidence_classes(sc, cons, CK.read_only)
            assert len(groups) == 1, f"{sc}/{cons} read_only should be one base group"
            assert groups[0], "group must be non-empty"


def test_read_only_satisfied_by_matching_real_evidence_each_surface():
    for sc in SC:
        cons = _compatible_consumers(sc)[0]
        group = t.required_evidence_classes(sc, cons, CK.read_only)[0]
        ec = sorted(group, key=lambda e: e.value)[0]
        results, verdict = t.check_journey(cons, [(sc, CK.read_only)], [ref(sc, ec)])
        assert [r.status for r in results] == [Status.satisfied], f"{sc} {ec}"
        assert verdict is Verdict.satisfied


# --- consumer=both single human / single agent surface -----------------------

def test_consumer_both_accepts_single_human_or_single_agent_surface():
    # both is compatible with a lone human surface...
    t.required_evidence_classes(SC.read_only_ui, Cons.both, CK.read_only)
    # ...and with a lone agent surface
    t.required_evidence_classes(SC.agent_mcp_tool, Cons.both, CK.read_only)


# --- mutation / qualitative / error_path -------------------------------------

def test_mutation_adds_idempotency_and_rollback_conjunctive_groups():
    groups = t.required_evidence_classes(SC.service_batch, Cons.agent, CK.mutation)
    assert groups[0] == frozenset({EC.contract_check})  # surface base
    assert frozenset({EC.idempotency}) in groups
    assert frozenset({EC.rollback}) in groups
    assert len(groups) == 3


def test_qualitative_adds_rubric_or_human_signoff_on_top_of_base():
    groups = t.required_evidence_classes(SC.read_only_ui, Cons.human, CK.qualitative)
    assert groups[0] == frozenset({EC.screenshot, EC.recording, EC.journey_walk})
    assert frozenset({EC.rubric, EC.human_signoff}) in groups


def test_qualitative_defined_for_agent_family_too():
    groups = t.required_evidence_classes(SC.agent_mcp_tool, Cons.agent, CK.qualitative)
    assert frozenset({EC.rubric, EC.human_signoff}) in groups


def test_error_path_adds_structured_error_group():
    groups = t.required_evidence_classes(SC.agent_mcp_tool, Cons.agent, CK.error_path)
    assert frozenset({EC.structured_error}) in groups


# --- invalid tuple rejection -------------------------------------------------

@pytest.mark.parametrize("sc,cons", [
    (SC.read_only_ui, Cons.agent),   # human surface, agent consumer
    (SC.agent_mcp_tool, Cons.human),  # agent surface, human consumer
])
def test_invalid_consumer_surface_tuple_rejected(sc, cons):
    with pytest.raises(t.InvalidConsumerSurfaceTuple):
        t.required_evidence_classes(sc, cons, CK.read_only)


# --- typed-skip never satisfies (D042) ---------------------------------------

def test_typed_skip_never_satisfies():
    skip = ref(SC.agent_mcp_tool, EC.tool_call_transcript,
               provenance="degraded", availability="unavailable")
    results, verdict = t.check_journey(
        Cons.agent, [(SC.agent_mcp_tool, CK.read_only)], [skip])
    assert results[0].status is Status.evidence_class_mismatch  # skip excluded
    assert verdict is Verdict.unsatisfied


# --- per-(surface, group) result output --------------------------------------

def test_per_surface_group_results_emitted_independently():
    reqs = [(SC.agent_mcp_tool, CK.read_only), (SC.cli_agent, CK.read_only)]
    refs = [ref(SC.agent_mcp_tool, EC.tool_call_transcript)]  # only first surface satisfied
    results, verdict = t.check_journey(Cons.agent, reqs, refs)
    assert len(results) == 2
    by_sc = {r.surface_class: r.status for r in results}
    assert by_sc[SC.agent_mcp_tool] is Status.satisfied
    assert by_sc[SC.cli_agent] is Status.evidence_class_mismatch
    assert verdict is Verdict.unsatisfied


# --- one EvidenceRef cannot satisfy multiple surface groups ------------------

def test_one_ref_consumed_by_at_most_one_group():
    # two identical agent_mcp_tool read_only requirements, ONE matching ref:
    # first group consumes it, second cannot reuse it.
    reqs = [(SC.agent_mcp_tool, CK.read_only), (SC.agent_mcp_tool, CK.read_only)]
    refs = [ref(SC.agent_mcp_tool, EC.tool_call_transcript)]
    results, _ = t.check_journey(Cons.agent, reqs, refs)
    statuses = [r.status for r in results]
    assert statuses.count(Status.satisfied) == 1
    assert Status.evidence_class_mismatch in statuses


# --- tri-state verdict --------------------------------------------------------

def test_agent_satisfied_human_pending_when_human_untyped_and_agent_passes():
    reqs = [(SC.read_only_ui, CK.read_only), (SC.agent_mcp_tool, CK.read_only)]
    # agent surface satisfied; NO typed evidence bound to the human surface
    refs = [ref(SC.agent_mcp_tool, EC.tool_call_transcript)]
    results, verdict = t.check_journey(Cons.both, reqs, refs)
    by_sc = {r.surface_class: r.status for r in results}
    assert by_sc[SC.read_only_ui] is Status.not_yet_typed
    assert by_sc[SC.agent_mcp_tool] is Status.satisfied
    assert verdict is Verdict.agent_satisfied_human_pending


def test_typed_human_surface_failure_is_unsatisfied_not_pending():
    # a TYPED human ref with the wrong evidence_class -> real failure, not pending
    reqs = [(SC.read_only_ui, CK.read_only), (SC.agent_mcp_tool, CK.read_only)]
    refs = [
        ref(SC.agent_mcp_tool, EC.tool_call_transcript),
        ref(SC.read_only_ui, EC.rubric),  # typed human ref, wrong class for read_only_ui
    ]
    results, verdict = t.check_journey(Cons.both, reqs, refs)
    by_sc = {r.surface_class: r.status for r in results}
    assert by_sc[SC.read_only_ui] is Status.evidence_class_mismatch
    assert verdict is Verdict.unsatisfied


def test_seeded_masks_readiness_unless_fixture_only():
    seeded = ref(SC.agent_mcp_tool, EC.tool_call_transcript, provenance="seeded")
    results, _ = t.check_journey(Cons.agent, [(SC.agent_mcp_tool, CK.read_only)], [seeded])
    assert results[0].status is Status.seeded_masks_readiness


def test_missing_provenance_is_distinct_status():
    noprov = ref(SC.agent_mcp_tool, EC.tool_call_transcript, provenance=None)
    results, _ = t.check_journey(Cons.agent, [(SC.agent_mcp_tool, CK.read_only)], [noprov])
    assert results[0].status is Status.missing_provenance
