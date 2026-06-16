"""F001 — Experience Readiness vocabulary + structural validators.

Covers the D069 implementation obligations that live at the schema layer:
full evidence_class -> EvidenceRef.type mapping; every ClaimKind incl error_path;
invalid-tuple (consumer x surface) rejection; consumer_family ==
SurfaceFamily(surface_class). Plus the total surface->family map, the 9-token
surface map (ios/android distinct tokens -> mobile_app), and the D027/D060/D064
EvidenceRef typing invariants.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Locate the agent-conventions models dir the same way runtime_evidence.harness does.
_SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[3] / ".claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[4] / "agent-conventions" / "schemas" / "v1.0",
]
for _candidate in _SCHEMA_CANDIDATES:
    if (_candidate / "models").is_dir():
        sys.path.insert(0, str(_candidate / "models"))
        break

import experience_readiness as er  # noqa: E402
from features_model import Type as EvidenceType  # noqa: E402


# --- total surface_class -> family map (D049) --------------------------------

def test_surface_family_map_is_total_over_every_surface_class():
    for sc in er.SurfaceClass:
        assert isinstance(er.surface_family(sc), er.SurfaceFamily)
    assert set(er.SURFACE_FAMILY) == set(er.SurfaceClass)


def test_surface_family_partition_matches_d049():
    human = {sc for sc in er.SurfaceClass if er.surface_family(sc) is er.SurfaceFamily.human}
    agent = {sc for sc in er.SurfaceClass if er.surface_family(sc) is er.SurfaceFamily.agent}
    assert human == {
        er.SurfaceClass.read_only_ui,
        er.SurfaceClass.interactive_ui,
        er.SurfaceClass.mobile_app,
        er.SurfaceClass.cli_human,
    }
    assert agent == {
        er.SurfaceClass.agent_mcp_tool,
        er.SurfaceClass.cli_agent,
        er.SurfaceClass.external_integration,
        er.SurfaceClass.service_batch,
    }


# --- token map: 9 tokens, ios/android distinct -> mobile_app, unknown rejected -

def test_surface_token_map_has_nine_tokens_with_ios_android_distinct():
    assert set(er.SURFACE_TOKEN_MAP) == {
        "web", "web_interactive", "backend", "mcp_tool",
        "cli_agent", "cli_human", "ios", "android", "external",
    }
    assert er.resolve_surface_token("ios") is er.SurfaceClass.mobile_app
    assert er.resolve_surface_token("android") is er.SurfaceClass.mobile_app
    assert er.resolve_surface_token("web") is er.SurfaceClass.read_only_ui
    assert er.resolve_surface_token("web_interactive") is er.SurfaceClass.interactive_ui


def test_unknown_surface_token_and_legacy_mutation_rejected_fail_closed():
    with pytest.raises(er.UnknownSurfaceToken):
        er.resolve_surface_token("mutation")  # a claim_kind, not a surface token
    with pytest.raises(er.UnknownSurfaceToken):
        er.resolve_surface_token("nope")


# --- ClaimKind incl error_path (D069 obligation) -----------------------------

def test_claimkind_is_closed_four_value_enum_including_error_path():
    assert {k.value for k in er.ClaimKind} == {
        "read_only", "mutation", "qualitative", "error_path",
    }


# --- full evidence_class -> existing EvidenceRef.type mapping (D069) ----------

def test_evidence_class_to_type_is_total_and_maps_to_existing_types():
    existing = {t.value for t in EvidenceType}
    assert set(er.EVIDENCE_CLASS_TO_TYPE) == set(er.EvidenceClass)  # every class mapped
    for ec, type_value in er.EVIDENCE_CLASS_TO_TYPE.items():
        assert type_value in existing, f"{ec} -> {type_value} not an existing EvidenceRef.type"


def test_evidence_class_family_resolves_human_agent_and_shared_none():
    assert er.evidence_class_family(er.EvidenceClass.screenshot) is er.SurfaceFamily.human
    assert er.evidence_class_family(er.EvidenceClass.contract_check) is er.SurfaceFamily.agent
    # shared classes can't be inferred from evidence_class (D037)
    for shared in (er.EvidenceClass.idempotency, er.EvidenceClass.rollback,
                   er.EvidenceClass.structured_error):
        assert er.evidence_class_family(shared) is None


# --- consumer x surface validation / invalid-tuple rejection (D026, D069) ----

@pytest.mark.parametrize("consumer,surfaces", [
    (er.Consumer.human, [er.SurfaceClass.read_only_ui]),
    (er.Consumer.agent, [er.SurfaceClass.agent_mcp_tool]),
    (er.Consumer.both, [er.SurfaceClass.read_only_ui, er.SurfaceClass.agent_mcp_tool]),
])
def test_valid_consumer_surface_combinations_accepted(consumer, surfaces):
    er.validate_consumer_surface(consumer, surfaces)  # no raise


@pytest.mark.parametrize("consumer,surfaces", [
    (er.Consumer.agent, [er.SurfaceClass.read_only_ui]),     # agent + human surface
    (er.Consumer.human, [er.SurfaceClass.agent_mcp_tool]),   # human + agent surface
    (er.Consumer.both, [er.SurfaceClass.read_only_ui]),      # both but no agent surface
    (er.Consumer.both, [er.SurfaceClass.agent_mcp_tool]),    # both but no human surface
])
def test_invalid_consumer_surface_tuples_rejected(consumer, surfaces):
    with pytest.raises(er.ConsumerSurfaceError):
        er.validate_consumer_surface(consumer, surfaces)


def test_empty_surface_set_rejected():
    with pytest.raises(er.ConsumerSurfaceError):
        er.validate_consumer_surface(er.Consumer.human, [])


# --- EvidenceRef structural typing invariants --------------------------------

def _typing(**over):
    base = dict(
        surface_class=er.SurfaceClass.agent_mcp_tool,
        consumer_family=er.SurfaceFamily.agent,
        availability=er.Availability.available,
        data_source="status",
        data_provenance=er.DataProvenance.real,
        degraded_mode=None,
        note=None,
        evidence_class=er.EvidenceClass.tool_call_transcript,
    )
    base.update(over)
    return base


def test_available_evidence_with_consistent_family_ok():
    er.validate_evidence_typing(**_typing())  # no raise


def test_family_consistency_invariant_rejects_contradiction_d065():
    with pytest.raises(er.EvidenceTypingError):
        er.validate_evidence_typing(**_typing(consumer_family=er.SurfaceFamily.human))


def test_availability_requires_data_source_and_consumer_family_d027():
    with pytest.raises(er.EvidenceTypingError):
        er.validate_evidence_typing(**_typing(data_source=None))
    with pytest.raises(er.EvidenceTypingError):
        er.validate_evidence_typing(**_typing(consumer_family=None))


def test_degraded_provenance_requires_degraded_mode_any_availability_d064():
    # degraded but available, missing degraded_mode -> rejected
    with pytest.raises(er.EvidenceTypingError):
        er.validate_evidence_typing(
            **_typing(data_provenance=er.DataProvenance.degraded, degraded_mode=None)
        )


def test_typed_skip_well_formed_ok_and_malformed_cases_rejected_d060():
    good = _typing(
        availability=er.Availability.unavailable,
        data_provenance=er.DataProvenance.degraded,
        degraded_mode="mcp_server_unavailable",
        note="skipped: mcp_server not running",
        evidence_class=er.EvidenceClass.tool_call_transcript,
    )
    er.validate_evidence_typing(**good)  # no raise
    # malformed: real provenance on a typed-skip
    with pytest.raises(er.EvidenceTypingError):
        er.validate_evidence_typing(**{**good, "data_provenance": er.DataProvenance.real})
    # malformed: each required attribution field missing
    for missing in ("degraded_mode", "note", "evidence_class", "surface_class"):
        bad = {**good, missing: None}
        # surface_class=None also drops consumer_family family-check; keep family ok
        with pytest.raises(er.EvidenceTypingError):
            er.validate_evidence_typing(**bad)
