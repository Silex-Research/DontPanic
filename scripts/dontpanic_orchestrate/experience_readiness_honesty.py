"""2a-F004 — degraded-honesty + cross-surface agreement checker (pure, no I/O).

Consumes the MERGED 2a-core (2026-06-15-001) EvidenceRef vocabulary and closed
enums (D008/D009): the checker reads {data_source, availability, data_provenance,
consumer_family, evidence_class} off EvidenceRef-like views and never redefines
schema.

It answers three orthogonal questions for a journey's evidence set:

  1. honesty verdict (TRI-STATE, D015): honest | degraded_dishonest |
     human_not_yet_typed_pending. Evaluated PER REQUIRED FAMILY (D003/D010):
     when a data_source is down (any required family reports unavailable), every
     required family must itself carry an honest availability=unavailable signal;
     a typed family that stays `available` (masks), a degraded ref whose mode is
     not in allowed_degraded_modes (D004), or a self-inconsistent family
     (available+real AND unavailable, D012) is degraded_dishonest. A required
     HUMAN family that is not_yet_typed is DEFERRED (pending), never silently
     passed and never penalized (D013/D015); a required AGENT family that omits
     its honest signal while the source is down is masking → degraded_dishonest.

  2. cross_surface_disagreement (D006): at the (objective, data_source) pair,
     the human vs agent per-family reduced (availability, provenance) differ —
     compared on structured fields, not description text.

  3. satisfaction discriminator (D005/D011): a journey's evidence set is
     `satisfied` only if EVERY required family is typed (D015) AND it ALSO
     contains a real (non-seeded), available journey-EXECUTION EvidenceRef —
     keyed data_source=EXECUTION_DATA_SOURCE ("journey_execution"), distinct
     from every dependency source — whose evidence_class is in the closed
     execution set. A dependency transcript is an availability claim, not
     execution proof. A set of only unavailable/typed-skip tuples is honest
     about being down but NOT a success.

Reduction is deterministic (D012); grouping is by (objective=UserJourney.name,
data_source) (D016).
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Resolve the merged 2a-core models dir the same way the F002/F003 modules do.
for _c in (
    Path(__file__).resolve().parents[2] / "claude" / "shared" / "schemas" / "v1.0" / "models",
    Path(__file__).resolve().parents[2] / ".claude" / "shared" / "schemas" / "v1.0" / "models",
):
    if (_c / "experience_readiness.py").is_file():
        sys.path.insert(0, str(_c))
        break

import experience_readiness as er  # noqa: E402

Fam = er.SurfaceFamily
Prov = er.DataProvenance
Avail = er.Availability
EC = er.EvidenceClass

# D011 — the closed subset of 2a-core's evidence_class enum that PROVES execution.
# Excludes idempotency / rollback / structured_error (shared/error classes).
EXECUTION_CLASSES: frozenset = frozenset({
    EC.screenshot, EC.recording, EC.journey_walk, EC.terminal_transcript,
    EC.tool_call_transcript, EC.cli_transcript, EC.contract_check,
})

# D005/D011 (PR56 follow-up, r3422558988) — the reserved data_source key for a
# journey-EXECUTION EvidenceRef. Execution proof is journey-level ("the flow
# ran"), NOT an availability claim about a dependency, so it carries its own key
# distinct from every required dependency source. Without this discriminator an
# available+real dependency transcript (data_source=payments,
# evidence_class=tool_call_transcript) would satisfy a journey on its own.
# Consumers deriving required dependency sources from refs (completion_gate)
# must exclude this key.
EXECUTION_DATA_SOURCE = "journey_execution"


class HonestyVerdict(Enum):
    honest = "honest"
    degraded_dishonest = "degraded_dishonest"
    human_not_yet_typed_pending = "human_not_yet_typed_pending"


class DishonestReason(Enum):
    mask = "mask"                      # typed family stays available while source is down
    mode_not_allowed = "mode_not_allowed"  # degraded mode not in allowed_degraded_modes (D004)
    conflict = "conflict"             # self-inconsistent family reduction (D012)
    agent_omitted = "agent_omitted"   # required agent family gives no honest signal while down


@dataclass(frozen=True)
class RequiredDataSource:
    data_source: str
    required_families: frozenset  # of SurfaceFamily

    def __post_init__(self):
        fams = frozenset(
            f if isinstance(f, Fam) else Fam(f) for f in self.required_families
        )
        object.__setattr__(self, "required_families", fams)


@dataclass(frozen=True)
class FamilyReduction:
    family: Fam
    typed: bool
    availability: Avail | None
    provenance: Prov | None
    conflict: bool


@dataclass
class SourceResult:
    data_source: str
    source_down: bool
    families: dict  # Fam -> FamilyReduction
    dishonest_reasons: set = field(default_factory=set)  # of DishonestReason
    disagreement: bool = False
    missing_families: set = field(default_factory=set)  # required Fam with NO typed ref


@dataclass
class HonestyResult:
    verdict: HonestyVerdict
    satisfied: bool
    sources: list  # of SourceResult
    disagreements: list  # of data_source keys with cross_surface_disagreement
    # Why `satisfied` is False, for operator-facing reasons (PR56 follow-up):
    execution_evidence: bool = True  # a real EXECUTION_DATA_SOURCE ref is present
    missing_families: list = field(default_factory=list)  # "<source>:<family>"


def _as(enum_cls, value):
    if value is None or isinstance(value, enum_cls):
        return value
    return enum_cls(value)


def _reduce_family(family: Fam, refs: Sequence) -> FamilyReduction:
    """Deterministic per-family reduction (D012)."""
    if not refs:
        return FamilyReduction(family, typed=False, availability=None,
                               provenance=None, conflict=False)
    avails = {_as(Avail, r.availability) for r in refs}
    provs = {_as(Prov, getattr(r, "data_provenance", None)) for r in refs}
    # any-unavailable dominates
    availability = Avail.unavailable if Avail.unavailable in avails else Avail.available
    # degraded dominates over real; real over None
    if Prov.degraded in provs:
        provenance: Prov | None = Prov.degraded
    elif Prov.real in provs:
        provenance = Prov.real
    elif Prov.seeded in provs:
        provenance = Prov.seeded
    else:
        provenance = None
    # self-inconsistent: claims available+real AND unavailable for the same key/family
    has_available_real = any(
        _as(Avail, r.availability) is Avail.available
        and _as(Prov, getattr(r, "data_provenance", None)) is Prov.real
        for r in refs
    )
    conflict = has_available_real and Avail.unavailable in avails
    return FamilyReduction(family, typed=True, availability=availability,
                           provenance=provenance, conflict=conflict)


def _mode_allowed(refs: Sequence, allowed: Iterable[str] | None) -> bool:
    """Every degraded ref's mode must be in the allowed set for this source (D004)."""
    allowed_set = set(allowed or ())
    for r in refs:
        if _as(Prov, getattr(r, "data_provenance", None)) is Prov.degraded:
            mode = getattr(r, "degraded_mode", None)
            if mode not in allowed_set:
                return False
    return True


def _is_real_execution(ref) -> bool:
    """A real, available journey-execution ref: keyed EXECUTION_DATA_SOURCE,
    execution-proving class, real provenance, available (D005/D011)."""
    if getattr(ref, "data_source", None) != EXECUTION_DATA_SOURCE:
        return False
    ec = getattr(ref, "evidence_class", None)
    if ec is None:
        return False
    if _as(EC, ec) not in EXECUTION_CLASSES:
        return False
    return (_as(Prov, getattr(ref, "data_provenance", None)) is Prov.real
            and _as(Avail, ref.availability) is Avail.available)


def check_degraded_honesty(
    required_sources: Sequence[RequiredDataSource],
    allowed_degraded_modes: Mapping[str, Iterable[str]],
    refs: Sequence,
) -> HonestyResult:
    """Evaluate one objective's evidence set. Pure; no I/O."""
    allowed_modes = allowed_degraded_modes or {}
    by_source: dict[str, list] = {}
    for r in refs:
        by_source.setdefault(getattr(r, "data_source", None), []).append(r)

    source_results: list[SourceResult] = []
    any_dishonest = False
    any_human_pending = False
    any_required_missing = False
    disagreements: list[str] = []

    for rds in required_sources:
        ds = rds.data_source
        ds_refs = by_source.get(ds, [])
        fam_refs = {
            fam: [r for r in ds_refs if _as(Fam, getattr(r, "consumer_family", None)) is fam]
            for fam in (Fam.human, Fam.agent)
        }
        reductions = {fam: _reduce_family(fam, fam_refs[fam]) for fam in (Fam.human, Fam.agent)}

        # the source is "down" if ANY required family honestly reports unavailable
        source_down = any(
            reductions[fam].availability is Avail.unavailable
            for fam in rds.required_families
        )

        reasons: set = set()
        missing: set = set()
        for fam in rds.required_families:
            red = reductions[fam]
            if not red.typed:
                # D015: honest certification requires EVERY required family typed.
                # An untyped required family blocks satisfaction whatever the
                # source state (PR56 r3422558994 — previously only checked while
                # the source was down).
                missing.add(fam)
                any_required_missing = True
                if fam is Fam.human:
                    any_human_pending = True  # deferred, not penalized (D013/D015)
                elif source_down:
                    reasons.add(DishonestReason.agent_omitted)  # agent masking by omission
                continue
            if red.conflict:
                reasons.add(DishonestReason.conflict)
            if not _mode_allowed(fam_refs[fam], allowed_modes.get(ds)):
                reasons.add(DishonestReason.mode_not_allowed)
            if source_down and red.availability is Avail.available:
                reasons.add(DishonestReason.mask)  # typed but masks the outage

        # cross_surface_disagreement (D006): both families typed but reduced state differs
        disagreement = False
        h, a = reductions[Fam.human], reductions[Fam.agent]
        if h.typed and a.typed and (
            h.availability is not a.availability or h.provenance is not a.provenance
        ):
            disagreement = True
            disagreements.append(ds)

        if reasons:
            any_dishonest = True
        source_results.append(SourceResult(
            data_source=ds, source_down=source_down, families=reductions,
            dishonest_reasons=reasons, disagreement=disagreement,
            missing_families=missing,
        ))

    # tri-state precedence (D015): dishonest > pending > honest
    if any_dishonest:
        verdict = HonestyVerdict.degraded_dishonest
    elif any_human_pending:
        verdict = HonestyVerdict.human_not_yet_typed_pending
    else:
        verdict = HonestyVerdict.honest

    # D005/D011/D015: satisfied only when honest, EVERY required family is
    # typed, AND a real journey-execution ref (reserved key) is present.
    execution_evidence = any(_is_real_execution(r) for r in refs)
    satisfied = (verdict is HonestyVerdict.honest
                 and not any_required_missing
                 and execution_evidence)
    missing_families = [
        f"{sr.data_source}:{fam.value}"
        for sr in source_results
        for fam in sorted(sr.missing_families, key=lambda f: f.value)
    ]

    return HonestyResult(verdict=verdict, satisfied=satisfied,
                         sources=source_results, disagreements=disagreements,
                         execution_evidence=execution_evidence,
                         missing_families=missing_families)


def check_objectives(
    objective_to_refs: Mapping[str, Sequence],
    required_sources: Sequence[RequiredDataSource],
    allowed_degraded_modes: Mapping[str, Iterable[str]],
) -> dict[str, HonestyResult]:
    """Evaluate each objective (UserJourney.name) independently (D006/D016).

    Refs are grouped by objective by the CALLER (via the harness journey
    argument / post_impl/<source>/<journey>/ path); this function guarantees no
    cross-objective contamination even when two objectives share a data_source.
    """
    return {
        objective: check_degraded_honesty(required_sources, allowed_degraded_modes, refs)
        for objective, refs in objective_to_refs.items()
    }


def plan_journey_required_sources() -> list[RequiredDataSource]:
    """The honesty contract for THIS plan's own journey (obligation 3, D018).

    Every declared data_source requires BOTH families so an implementation
    cannot satisfy the checker while covering only one family.
    """
    both = frozenset({Fam.human, Fam.agent})
    return [
        RequiredDataSource("dontpanic_status", both),
        RequiredDataSource("dontpanic_doctor", both),
    ]
