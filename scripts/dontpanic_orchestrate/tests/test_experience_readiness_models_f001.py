"""F001 — EvidenceRef + UserJourney model wiring (the new fields live ON the
shared Pydantic models, with the structural invariants enforced at validation)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dontpanic_orchestrate.agent_conventions.schemas.v1_0.models.features_model import (  # noqa: E402
    EvidenceRef,
)
from dontpanic_orchestrate.agent_conventions.schemas.v1_0.models.objective_contract_model import (  # noqa: E402
    UserJourney,
)


def test_legacy_evidence_ref_without_new_fields_still_valid():
    ref = EvidenceRef(type="log", uri="evidence/x.log")
    assert ref.evidence_class is None and ref.availability is None


def test_evidence_ref_accepts_full_typed_agent_fields():
    ref = EvidenceRef(
        type="log", uri="evidence/mcp.log",
        evidence_class="tool_call_transcript", data_provenance="real",
        data_source="status", availability="available", consumer_family="agent",
        surface_class="agent_mcp_tool",
    )
    assert ref.consumer_family == "agent"


def test_evidence_ref_rejects_family_contradiction():
    with pytest.raises(ValidationError):
        EvidenceRef(
            type="log", uri="e.log",
            data_source="s", availability="available",
            consumer_family="human", surface_class="agent_mcp_tool",  # D065 violation
        )


def test_evidence_ref_rejects_unknown_closed_enum_value():
    with pytest.raises(ValidationError):
        EvidenceRef(type="log", uri="e.log", evidence_class="not_a_real_class")


def test_user_journey_accepts_consumer_and_fixture_only():
    j = UserJourney(name="agent-cli", description="agent runs cli read-only",
                    surfaces=["cli_agent"], consumer="agent", fixture_only=False)
    assert j.consumer == "agent" and j.fixture_only is False


def test_user_journey_rejects_consumer_surface_mismatch():
    with pytest.raises(ValidationError):
        UserJourney(name="bad", description="agent consumer but human surface",
                    surfaces=["web"], consumer="agent")  # D026


def test_user_journey_without_consumer_is_unvalidated_legacy():
    j = UserJourney(name="legacy", description="no consumer declared",
                    surfaces=["whatever-free-form"])
    assert j.consumer is None
