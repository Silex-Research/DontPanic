"""Experience Readiness — evidence-class typing rule + checker (F002).

Plan 2026-06-15-001 (2a-core). PURE logic over F001's closed vocabulary:

- ``required_evidence_classes(surface_class, consumer, claim_kind)`` — pure
  function returning a list of REQUIREMENT GROUPS (each group satisfied by
  ANY ONE of its alternatives; ALL groups conjunctive). Rejects
  family-incompatible (consumer, surface_class) tuples (D026/D065).
- ``check_journey(consumer, requirements, evidence_refs)`` — given the full
  ``list[EvidenceRef]`` (whole refs, never a partial projection; D058), returns
  a per-(surface_class, requirement-group) result list plus a TRI-STATE journey
  verdict (D062). Enforcement is scoped to AGENT-family surfaces (D060): a
  human-family surface lacking typed evidence yields ``not_yet_typed`` (legacy
  compatibility), never a fail-closed rejection.

No I/O, no input mutation.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Locate the agent-conventions models dir (same discovery as runtime_evidence.harness).
_SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[2] / ".claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[3] / "agent-conventions" / "schemas" / "v1.0",
]
for _candidate in _SCHEMA_CANDIDATES:
    if (_candidate / "models").is_dir():
        _models = str(_candidate / "models")
        if _models not in sys.path:
            sys.path.insert(0, _models)
        break

import experience_readiness as er  # noqa: E402

EC = er.EvidenceClass
SC = er.SurfaceClass


class InvalidConsumerSurfaceTuple(ValueError):
    """A (consumer, surface_class) tuple whose families are incompatible
    (D026/D065) — e.g. consumer=agent on a human-family surface."""


class CheckStatus(str, Enum):
    satisfied = "satisfied"
    evidence_class_mismatch = "evidence_class_mismatch"
    seeded_masks_readiness = "seeded_masks_readiness"
    missing_provenance = "missing_provenance"
    not_yet_typed = "not_yet_typed"


class JourneyVerdict(str, Enum):
    satisfied = "satisfied"
    agent_satisfied_human_pending = "agent_satisfied_human_pending"
    unsatisfied = "unsatisfied"


# --- read_only requirement matrix, TOTAL over the 8 surface_classes (D045) ----
_READ_ONLY_MATRIX: dict[er.SurfaceClass, frozenset] = {
    SC.read_only_ui: frozenset({EC.screenshot, EC.recording, EC.journey_walk}),
    SC.interactive_ui: frozenset({EC.screenshot, EC.recording, EC.journey_walk}),
    SC.mobile_app: frozenset({EC.screenshot, EC.recording}),
    SC.cli_human: frozenset({EC.terminal_transcript}),
    SC.cli_agent: frozenset({EC.cli_transcript}),
    SC.agent_mcp_tool: frozenset({EC.tool_call_transcript, EC.contract_check}),
    SC.external_integration: frozenset({EC.contract_check}),
    SC.service_batch: frozenset({EC.contract_check}),
}
assert set(_READ_ONLY_MATRIX) == set(SC), "read_only matrix must be total over SurfaceClass"


def required_evidence_classes(
    surface_class: er.SurfaceClass | str,
    consumer: er.Consumer | str,
    claim_kind: er.ClaimKind | str,
) -> list[frozenset]:
    """Pure typing rule. Returns conjunctive requirement groups (each group =
    at-least-one-of its EvidenceClass alternatives). The surface read_only base
    is ALWAYS included; claim_kind ADDS groups on top (D028/D035).

    Rejects family-incompatible (consumer, surface_class) tuples (D026/D065):
    consumer=human on an agent surface, or consumer=agent on a human surface.
    consumer=both is compatible with either family.
    """
    sc = SC(surface_class)
    cons = er.Consumer(consumer)
    ck = er.ClaimKind(claim_kind)

    fam = er.surface_family(sc)
    if cons is er.Consumer.human and fam is er.SurfaceFamily.agent:
        raise InvalidConsumerSurfaceTuple(
            f"consumer=human incompatible with agent-family surface {sc.value} (D065)"
        )
    if cons is er.Consumer.agent and fam is er.SurfaceFamily.human:
        raise InvalidConsumerSurfaceTuple(
            f"consumer=agent incompatible with human-family surface {sc.value} (D065)"
        )

    groups: list[frozenset] = [_READ_ONLY_MATRIX[sc]]  # surface read_only base
    if ck is er.ClaimKind.mutation:
        groups.append(frozenset({EC.idempotency}))
        groups.append(frozenset({EC.rollback}))
    elif ck is er.ClaimKind.qualitative:
        groups.append(frozenset({EC.rubric, EC.human_signoff}))
    elif ck is er.ClaimKind.error_path:
        groups.append(frozenset({EC.structured_error}))
    # claim_kind=read_only -> base only
    return groups


# --- checker over the full EvidenceRef[] --------------------------------------

@dataclass(frozen=True)
class GroupResult:
    surface_class: er.SurfaceClass
    claim_kind: er.ClaimKind
    group_index: int
    group: frozenset
    status: CheckStatus


def _attr(ref, name):
    if isinstance(ref, dict):
        return ref.get(name)
    return getattr(ref, name, None)


def _coerce(value, enum):
    return enum(value) if value is not None else None


def _fully_typed(ref) -> bool:
    """A ref carrying the structural typed fields (surface_class + availability +
    consumer_family). Untyped human evidence lacks these -> not_yet_typed."""
    return (
        _attr(ref, "surface_class") is not None
        and _attr(ref, "availability") is not None
        and _attr(ref, "consumer_family") is not None
    )


def check_journey(
    consumer: er.Consumer | str,
    requirements: list[tuple],
    evidence_refs: list,
) -> tuple[list[GroupResult], JourneyVerdict]:
    """Evaluate a journey. ``requirements`` is a list of (surface_class,
    claim_kind). Each declared surface forms its OWN requirement set, satisfied
    INDEPENDENTLY (D057); each EvidenceRef is attributed to a surface group via
    its EvidenceRef.surface_class and consumed by AT MOST ONE group (D058)."""
    consumed: set[int] = set()  # ids of refs already consumed by a group
    results: list[GroupResult] = []

    for sc_raw, ck_raw in requirements:
        sc = SC(sc_raw)
        ck = er.ClaimKind(ck_raw)
        fam = er.surface_family(sc)
        groups = required_evidence_classes(sc, consumer, ck)
        # refs structurally bound to this surface_class (D058)
        bound = [
            (i, r) for i, r in enumerate(evidence_refs)
            if _coerce(_attr(r, "surface_class"), SC) == sc
        ]
        has_typed_bound = any(_fully_typed(r) for _, r in bound)

        for gi, group in enumerate(groups):
            status, picked = _match_group(
                group, bound, consumed, fam, has_typed_bound,
            )
            if picked is not None:
                consumed.add(picked)
            results.append(GroupResult(sc, ck, gi, group, status))

    return results, _tri_state_verdict(results)


def _match_group(group, bound, consumed, fam, has_typed_bound):
    """Return (status, ref_index_consumed_or_None) for one requirement group.

    A typed-skip (availability=unavailable) NEVER satisfies (D042). Satisfaction
    requires a non-skip ref bound to the surface whose evidence_class is in the
    group with non-seeded provenance (real|degraded), or seeded under a
    fixture_only journey (handled by caller via group provenance). Provenance
    missing -> missing_provenance; seeded(non-fixture) -> seeded_masks_readiness.
    No typed candidate on a HUMAN surface -> not_yet_typed (D060/D063); on an
    AGENT surface -> evidence_class_mismatch (fail-closed).
    """
    # candidate refs: bound, not consumed, evidence_class in group, not typed-skip
    candidates = []
    for i, r in bound:
        if i in consumed:
            continue
        ec = _coerce(_attr(r, "evidence_class"), EC)
        if ec not in group:
            continue
        if _coerce(_attr(r, "availability"), er.Availability) is er.Availability.unavailable:
            continue  # typed-skip never satisfies (D042)
        candidates.append((i, r))

    # prefer by provenance: real/degraded (present) > seeded > missing
    real = [(i, r) for i, r in candidates
            if _coerce(_attr(r, "data_provenance"), er.DataProvenance)
            in (er.DataProvenance.real, er.DataProvenance.degraded)]
    if real:
        return CheckStatus.satisfied, real[0][0]
    seeded = [(i, r) for i, r in candidates
              if _coerce(_attr(r, "data_provenance"), er.DataProvenance) is er.DataProvenance.seeded]
    if seeded:
        return CheckStatus.seeded_masks_readiness, None
    missing = [(i, r) for i, r in candidates
               if _attr(r, "data_provenance") is None]
    if missing:
        return CheckStatus.missing_provenance, None

    # no class-matching non-skip candidate bound to this surface
    if fam is er.SurfaceFamily.human and not has_typed_bound:
        return CheckStatus.not_yet_typed, None
    return CheckStatus.evidence_class_mismatch, None


def _tri_state_verdict(results: list[GroupResult]) -> JourneyVerdict:
    """D062: satisfied = ALL groups satisfied; agent_satisfied_human_pending =
    ALL agent-family groups satisfied AND every remaining non-satisfied group is
    a human-family not_yet_typed; unsatisfied = any agent-family group failed OR
    any human-family group failed with something OTHER than not_yet_typed."""
    if all(r.status is CheckStatus.satisfied for r in results):
        return JourneyVerdict.satisfied

    for r in results:
        fam = er.surface_family(r.surface_class)
        if r.status is CheckStatus.satisfied:
            continue
        if fam is er.SurfaceFamily.agent:
            return JourneyVerdict.unsatisfied  # any agent-family failure
        # human-family non-satisfied: only not_yet_typed is tolerated
        if r.status is not CheckStatus.not_yet_typed:
            return JourneyVerdict.unsatisfied
    return JourneyVerdict.agent_satisfied_human_pending


__all__ = [
    "InvalidConsumerSurfaceTuple",
    "CheckStatus",
    "JourneyVerdict",
    "required_evidence_classes",
    "GroupResult",
    "check_journey",
]
