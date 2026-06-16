"""Experience Readiness — consumer-family evidence typing vocabulary (F001).

Plan 2026-06-15-001 (2a-core). This module defines the SHARED, CLOSED
vocabulary for both human and agent consumer families:

- ``SurfaceClass``      — closed structural set derived from the 8 qa-sufficiency
                          surface classes (D024).
- ``SurfaceFamily``     — human | agent, with a TOTAL map from every
                          SurfaceClass member to exactly one family (D049).
- ``Consumer``          — human | agent | both (the journey-declared consumer).
- ``ClaimKind``         — read_only | mutation | qualitative | error_path (D058).
- ``EvidenceClass``     — single closed enum referenced by F002/F003/F004 (D028).
- ``DataProvenance``    — seeded | real | degraded.
- ``Availability``      — available | unavailable.
- ``SURFACE_TOKEN_MAP`` — TOTAL, DETERMINISTIC 1:1 map from accepted journey
                          surface TOKENS onto SurfaceClass members (D050/D065).
- ``EVIDENCE_CLASS_TO_TYPE`` — full mapping of every EvidenceClass to a valid
                          EXISTING ``EvidenceRef.type`` value (D064 obligation).

Scope (D060): 2a-core defines the FULL vocabulary for both families but only
F002 ENFORCES rich typing on agent-family surfaces. This module is pure
(no I/O); all maps are total and asserted by tests.
"""

from __future__ import annotations

from enum import Enum


class SurfaceClass(str, Enum):
    """Closed structural surface set (D024). The legacy qa class 'mutation' is
    NOT here — it is a ClaimKind, not a surface (D014)."""

    read_only_ui = "read_only_ui"
    interactive_ui = "interactive_ui"
    mobile_app = "mobile_app"
    cli_human = "cli_human"
    agent_mcp_tool = "agent_mcp_tool"
    cli_agent = "cli_agent"
    external_integration = "external_integration"
    service_batch = "service_batch"


class SurfaceFamily(str, Enum):
    human = "human"
    agent = "agent"


class Consumer(str, Enum):
    human = "human"
    agent = "agent"
    both = "both"


class ClaimKind(str, Enum):
    """D058 — single closed enum. ``error_path`` is a member even though a given
    journey need not exercise it; the objective contract names the subset it
    uses, not the full enum (D064 alignment)."""

    read_only = "read_only"
    mutation = "mutation"
    qualitative = "qualitative"
    error_path = "error_path"


class EvidenceClass(str, Enum):
    # human family
    screenshot = "screenshot"
    recording = "recording"
    journey_walk = "journey_walk"
    terminal_transcript = "terminal_transcript"
    rubric = "rubric"
    human_signoff = "human_signoff"
    # agent family
    tool_call_transcript = "tool_call_transcript"
    cli_transcript = "cli_transcript"
    contract_check = "contract_check"
    # mutation (claim_kind=mutation)
    idempotency = "idempotency"
    rollback = "rollback"
    # structured (error-path)
    structured_error = "structured_error"


class DataProvenance(str, Enum):
    seeded = "seeded"
    real = "real"
    degraded = "degraded"


class Availability(str, Enum):
    available = "available"
    unavailable = "unavailable"


# --- D049: TOTAL SurfaceClass -> SurfaceFamily map (every member, exactly one) -
SURFACE_FAMILY: dict[SurfaceClass, SurfaceFamily] = {
    SurfaceClass.read_only_ui: SurfaceFamily.human,
    SurfaceClass.interactive_ui: SurfaceFamily.human,
    SurfaceClass.mobile_app: SurfaceFamily.human,
    SurfaceClass.cli_human: SurfaceFamily.human,
    SurfaceClass.agent_mcp_tool: SurfaceFamily.agent,
    SurfaceClass.cli_agent: SurfaceFamily.agent,
    SurfaceClass.external_integration: SurfaceFamily.agent,
    SurfaceClass.service_batch: SurfaceFamily.agent,
}


def surface_family(surface_class: SurfaceClass) -> SurfaceFamily:
    """Total, deterministic SurfaceClass -> SurfaceFamily (D049)."""
    return SURFACE_FAMILY[SurfaceClass(surface_class)]


# --- D050/D065: TOTAL, DETERMINISTIC 1:1 token -> SurfaceClass map ------------
# Many TOKENS may map to one CLASS (web/web_interactive distinct; ios+android
# both -> mobile_app). '8' denotes surface_CLASSES, not token count. The legacy
# 'mutation' token is NOT a surface token (it migrates to ClaimKind, D058/D063).
SURFACE_TOKEN_MAP: dict[str, SurfaceClass] = {
    "web": SurfaceClass.read_only_ui,
    "web_interactive": SurfaceClass.interactive_ui,
    "backend": SurfaceClass.service_batch,
    "mcp_tool": SurfaceClass.agent_mcp_tool,
    "cli_agent": SurfaceClass.cli_agent,
    "cli_human": SurfaceClass.cli_human,
    "ios": SurfaceClass.mobile_app,
    "android": SurfaceClass.mobile_app,
    "external": SurfaceClass.external_integration,
}


class UnknownSurfaceToken(ValueError):
    """Raised when a journey surface token is outside SURFACE_TOKEN_MAP
    (fail-closed; D050)."""


def resolve_surface_token(token: str) -> SurfaceClass:
    """Resolve a journey surface token to its SurfaceClass. Unknown tokens are
    rejected fail-closed (D050)."""
    try:
        return SURFACE_TOKEN_MAP[token]
    except KeyError as exc:
        raise UnknownSurfaceToken(
            f"unknown surface token {token!r}; accepted: "
            f"{sorted(SURFACE_TOKEN_MAP)}"
        ) from exc


# --- D064 obligation: full evidence_class -> existing EvidenceRef.type --------
# Every EvidenceClass maps to a valid EXISTING features_model.Type value; the
# EvidenceRef.type enum is NOT extended.
EVIDENCE_CLASS_TO_TYPE: dict[EvidenceClass, str] = {
    EvidenceClass.screenshot: "screenshot",
    EvidenceClass.recording: "file",
    EvidenceClass.journey_walk: "log",
    EvidenceClass.terminal_transcript: "log",
    EvidenceClass.rubric: "audit_json",
    EvidenceClass.human_signoff: "audit_json",
    EvidenceClass.tool_call_transcript: "log",
    EvidenceClass.cli_transcript: "log",
    EvidenceClass.contract_check: "test_output",
    EvidenceClass.idempotency: "test_output",
    EvidenceClass.rollback: "test_output",
    EvidenceClass.structured_error: "log",
}


def evidence_class_family(evidence_class: EvidenceClass) -> SurfaceFamily | None:
    """The owning family of an evidence_class, or None for shared/cross-family
    classes (mutation + structured_error) whose family CANNOT be inferred from
    the class — callers must use EvidenceRef.surface_class / consumer_family
    instead (D037)."""
    human = {
        EvidenceClass.screenshot,
        EvidenceClass.recording,
        EvidenceClass.journey_walk,
        EvidenceClass.terminal_transcript,
        EvidenceClass.rubric,
        EvidenceClass.human_signoff,
    }
    agent = {
        EvidenceClass.tool_call_transcript,
        EvidenceClass.cli_transcript,
        EvidenceClass.contract_check,
    }
    ec = EvidenceClass(evidence_class)
    if ec in human:
        return SurfaceFamily.human
    if ec in agent:
        return SurfaceFamily.agent
    return None  # idempotency / rollback / structured_error are shared


# --- Validators (pure; raise ValueError on contract violation) ---------------


class ConsumerSurfaceError(ValueError):
    """consumer x surface mismatch (D026)."""


class EvidenceTypingError(ValueError):
    """EvidenceRef structural-typing violation (D027/D060/D064/D065)."""


def validate_consumer_surface(
    consumer: Consumer | str, surface_classes: list[SurfaceClass | str]
) -> None:
    """D026: consumer=human needs >=1 human-family surface; consumer=agent
    needs >=1 agent-family surface; consumer=both needs >=1 of EACH. Empty
    surface set is rejected. Raises ConsumerSurfaceError on mismatch."""
    cons = Consumer(consumer)
    fams = {surface_family(SurfaceClass(sc)) for sc in surface_classes}
    if not fams:
        raise ConsumerSurfaceError("a consumer-facing journey must declare >=1 surface")
    if cons in (Consumer.human, Consumer.both) and SurfaceFamily.human not in fams:
        raise ConsumerSurfaceError(f"consumer={cons.value} requires >=1 human-family surface")
    if cons in (Consumer.agent, Consumer.both) and SurfaceFamily.agent not in fams:
        raise ConsumerSurfaceError(f"consumer={cons.value} requires >=1 agent-family surface")


def validate_evidence_typing(
    *,
    surface_class: SurfaceClass | str | None,
    consumer_family: SurfaceFamily | str | None,
    availability: Availability | str | None,
    data_source: str | None,
    data_provenance: DataProvenance | str | None,
    degraded_mode: str | None,
    note: str | None,
    evidence_class: EvidenceClass | str | None,
) -> None:
    """Structural EvidenceRef invariants (raise EvidenceTypingError):

    - D027: availability set => BOTH data_source AND consumer_family set.
    - D065: consumer_family == surface_family(surface_class) when both set.
    - D064: data_provenance=degraded => degraded_mode set (any availability).
    - D060/D064 typed-skip (availability=unavailable) malformed unless it carries
      data_provenance=degraded + degraded_mode + note + evidence_class + surface_class.
    """
    avail = Availability(availability) if availability is not None else None
    prov = DataProvenance(data_provenance) if data_provenance is not None else None
    # closed-enum membership for the string-typed fields (fail-closed on unknown)
    if evidence_class is not None:
        EvidenceClass(evidence_class)
    if surface_class is not None:
        SurfaceClass(surface_class)
    if consumer_family is not None:
        SurfaceFamily(consumer_family)

    if avail is not None and (data_source is None or consumer_family is None):
        raise EvidenceTypingError(
            "availability requires BOTH data_source AND consumer_family (D027)"
        )

    if surface_class is not None and consumer_family is not None:
        if SurfaceFamily(consumer_family) != surface_family(SurfaceClass(surface_class)):
            raise EvidenceTypingError(
                f"consumer_family {SurfaceFamily(consumer_family).value} contradicts "
                f"surface_class {SurfaceClass(surface_class).value} family "
                f"{surface_family(SurfaceClass(surface_class)).value} (D065)"
            )

    if prov is DataProvenance.degraded and degraded_mode is None:
        raise EvidenceTypingError(
            "a degraded data_source (data_provenance=degraded) requires degraded_mode (D064)"
        )

    if avail is Availability.unavailable:
        # typed-skip — must be honest + fully attributed (D060/D064)
        if prov is not DataProvenance.degraded:
            raise EvidenceTypingError("typed-skip requires data_provenance=degraded (D060)")
        for field_name, value in (
            ("degraded_mode", degraded_mode),
            ("note", note),
            ("evidence_class", evidence_class),
            ("surface_class", surface_class),
        ):
            if value is None:
                raise EvidenceTypingError(f"typed-skip missing {field_name} (D060/D064)")


__all__ = [
    "SurfaceClass",
    "SurfaceFamily",
    "Consumer",
    "ClaimKind",
    "EvidenceClass",
    "DataProvenance",
    "Availability",
    "SURFACE_FAMILY",
    "surface_family",
    "SURFACE_TOKEN_MAP",
    "resolve_surface_token",
    "UnknownSurfaceToken",
    "EVIDENCE_CLASS_TO_TYPE",
    "evidence_class_family",
    "ConsumerSurfaceError",
    "EvidenceTypingError",
    "validate_consumer_surface",
    "validate_evidence_typing",
]
