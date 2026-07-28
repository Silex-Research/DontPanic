"""Plan F2 F001 — post-impl completion auditor.

**v1 evidence-coverage heuristic (D002), NOT a semantic completion
proof.** The auditor walks an objective contract's
``ObjectiveContract.required_evidence`` list (operator-supplied
matcher strings) against captured ``EvidenceRef`` artifacts (rebuilt
from ``evidence/goal-governance/post_impl/<source>/<journey>/``) and
surfaces gap-class findings:

- ``missing_evidence``: a required_evidence matcher has no captured
  ref whose ``uri`` or ``note`` contains the substring.
- ``journey_gap``: a contract user_journey has zero captured refs of
  any kind under any source surface.
- ``integration_gap``: reserved for cross-journey wiring gaps that
  this v1 heuristic cannot detect; no automatic emissions in v1.

What this auditor IS NOT (D002 framing):

- It does NOT certify journey correctness.
- It does NOT assert that captured artifacts demonstrate the
  contract's intended behavior.
- A matcher hit on ``uri`` / ``note`` is metadata-only — the matcher
  inspects path strings and labels, not artifact bytes.
- Empty findings means "no obvious evidence-coverage gaps detected,"
  NOT "plan complete."

The findings envelope carries
``audit_kind: "v1_evidence_coverage_heuristic"`` so downstream
consumers (F003 plan-close gate, dogfood dispositions, future
follow-ups) read the correct semantics. Behavioral / structured
completion proofs require richer schema (regex, structured
assertions, journey-walk steps) that v1 deliberately defers.

Public surface::

    run_completion_audit(plan_dir) -> list[CompletionFinding]
    CompletionFinding (Pydantic model)
    CompletionFindingsEnvelope (Pydantic model)
    COMPLETION_GAP_CLASSES (allowed gap_class enum tuple)
    COMPLETION_AUDIT_KIND ('v1_evidence_coverage_heuristic')
    COMPLETION_FINDINGS_ARTIFACT ('completion_findings.json')
    CompletionAuditError (raised on contract-load failures only;
                          per-matcher failures become findings)

    F0 adapters:
      to_goal_gap_findings(findings) -> list[GoalGapFinding]
      cluster_findings(findings) -> dict[(subsystem, journey), [...]]
      make_cluster_context(subsystem, journey) -> GoalGapClusterContext

Cross-vendor dispatch (F002) and plan-close gate (F003) are
separate features in this plan; F001 ships the auditor module
only. F1's `_resolve_goal_auditor_agent` is reused by F002 — F001
does not invoke it.

Capture-only invariant (Plan G D002 carry-forward / F2 D009): F001
reads existing EvidenceRef artifacts from disk; it does NOT
instantiate any runtime_evidence session class to re-capture.
The manifest rebuild is filesystem IO + sha256 hashing only.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dontpanic_orchestrate.nested_orchestration import (
    _GOAL_GAP_SEVERITY_RANK,
    GoalGapClusterContext,
    GoalGapFinding,
)

_SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[2] / ".claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[3] / "agent-conventions" / "schemas" / "v1.0",
]
for _candidate in _SCHEMA_CANDIDATES:
    if (_candidate / "models").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from models.features_model import EvidenceRef  # noqa: E402
from models.features_model import Type as EvidenceType  # noqa: E402
from models.objective_contract_model import ObjectiveContract  # noqa: E402

# ──────────────────────────────  constants  ──────────────────────────────


COMPLETION_GAP_CLASSES: tuple[str, ...] = (
    "missing_evidence",
    "journey_gap",
    "integration_gap",
)
"""Top-level gap-class taxonomy a completion finding may report. Pinned
here as the v1 vocabulary; D011 abort condition fires if the auditor's
gap-class needs grow beyond this set during F001 implementation."""

GapClass = Literal["missing_evidence", "journey_gap", "integration_gap"]

COMPLETION_AUDIT_KIND: Literal["v1_evidence_coverage_heuristic"] = "v1_evidence_coverage_heuristic"
"""**Load-bearing per D002.** The audit_kind field on
:class:`CompletionFindingsEnvelope` carries this literal so downstream
consumers (F003 plan-close gate, dogfood dispositions) can be sure
they are reading the v1 evidence-coverage heuristic — NOT a semantic
completion proof. v2+ heuristics that prove behavioral completeness
will introduce a different audit_kind value."""

COMPLETION_FINDINGS_ARTIFACT: str = "completion_findings.json"
"""Filename written under
``evidence/goal-governance/post_impl/<COMPLETION_FINDINGS_ARTIFACT>``."""

POST_IMPL_DIR: str = "evidence/goal-governance/post_impl"
"""Plan-relative root for post-impl evidence (mirror of F1's
``evidence/goal-governance/pre_impl`` convention)."""


_EXTENSION_TO_TYPE: dict[str, EvidenceType] = {
    ".png": EvidenceType.screenshot,
    ".jpg": EvidenceType.screenshot,
    ".jpeg": EvidenceType.screenshot,
    ".log": EvidenceType.log,
    ".jsonl": EvidenceType.log,
    ".xml": EvidenceType.test_output,
    ".html": EvidenceType.file,
}
"""Filename-extension → EvidenceRef.type lookup for manifest rebuild.
Anything not in this map → ``EvidenceType.file`` fallback."""


class CompletionAuditError(ValueError):
    """Raised on configuration / contract failures during a completion
    audit run (missing goal_type, missing/malformed contract).
    Per-matcher failures become findings, never raise."""


# ──────────────────────────────  finding model  ──────────────────────────────


class CompletionFinding(BaseModel):
    """One post-impl completion finding emitted by the F2 auditor.

    Severity validation reuses F0's ``_GOAL_GAP_SEVERITY_RANK`` so the
    completion surface stays consistent with the goal-gap classifier
    F003 will consume.
    """

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(..., min_length=1)
    gap_class: GapClass
    severity: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    narrative: str = Field(..., min_length=1)
    subsystem: str = Field(..., min_length=1)
    journey: str = Field(..., min_length=1)
    matcher_string: str | None = None
    """Set when ``gap_class='missing_evidence'`` to record the
    operator-declared required_evidence matcher that didn't hit."""
    evidence_uris: list[str] = Field(default_factory=list)
    """The captured EvidenceRef uris that DID match (for
    missing_evidence findings, this is empty by definition; for other
    gap classes, this is informational context)."""

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _GOAL_GAP_SEVERITY_RANK:
            raise ValueError(f"unknown completion-finding severity: {value!r}")
        return normalized


class CompletionFindingsEnvelope(BaseModel):
    """Envelope serialized to
    ``evidence/goal-governance/post_impl/completion_findings.json``.

    The ``audit_kind`` field is the load-bearing v1-vs-future
    discriminator (D002). Downstream consumers MUST read this and not
    over-trust empty findings as completeness."""

    model_config = ConfigDict(extra="forbid")

    audit_kind: Literal["v1_evidence_coverage_heuristic"]
    generated_at: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    contract_path: str = Field(..., min_length=1)
    evidence_manifest_uris: list[str]
    findings: list[CompletionFinding]


# ──────────────────────────────  contract loader  ──────────────────────────────


def _read_frontmatter(plan_md: Path) -> dict:
    """Read the YAML frontmatter from a plan.md. Mirrors F1's
    sufficiency_auditor pattern; kept inline so the F2 auditor doesn't
    couple to F1's module load order."""
    if not plan_md.is_file():
        raise CompletionAuditError(f"{plan_md}: plan.md does not exist")
    text = plan_md.read_text()
    if not text.startswith("---"):
        raise CompletionAuditError(
            f"{plan_md}: plan.md does not start with YAML frontmatter delimiter"
        )
    end = text.find("\n---", 3)
    if end < 0:
        raise CompletionAuditError(f"{plan_md}: unterminated frontmatter block")

    import yaml as _yaml

    raw = text[3:end]
    try:
        fm = _yaml.safe_load(raw)
    except _yaml.YAMLError as exc:
        raise CompletionAuditError(f"{plan_md}: failed to parse frontmatter: {exc}") from exc
    if not isinstance(fm, dict):
        raise CompletionAuditError(f"{plan_md}: frontmatter is not a mapping")
    return fm


def _load_objective_contract(plan_dir: Path) -> ObjectiveContract:
    """Load + validate the ObjectiveContract referenced by a plan.

    Raises :class:`CompletionAuditError` on missing/malformed contract.
    Does NOT enforce that goal_type is one that requires a contract —
    F2 callers (the F003 plan-close gate) decide whether to invoke the
    auditor based on plan goal_type. Once invoked, F001 needs a
    contract to walk; absence is a hard error."""
    plan_md = plan_dir / "plan.md"
    fm = _read_frontmatter(plan_md)

    links = fm.get("links") or {}
    if not isinstance(links, dict):
        raise CompletionAuditError(
            f"{plan_md}: links must be a mapping, got {type(links).__name__}"
        )
    contract_ref = links.get("objective_contract")
    if not contract_ref:
        raise CompletionAuditError(
            f"{plan_md}: links.objective_contract is missing or empty; "
            "completion audit requires a contract reference"
        )

    contract_path = (plan_dir / contract_ref).resolve()
    if not contract_path.is_file():
        raise CompletionAuditError(
            f"{plan_md}: links.objective_contract points to {contract_ref!r}, "
            f"but the file does not exist at {contract_path}"
        )
    try:
        raw = json.loads(contract_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CompletionAuditError(
            f"{contract_path}: failed to read objective contract: {exc}"
        ) from exc
    try:
        return ObjectiveContract.model_validate(raw)
    except ValidationError as exc:
        raise CompletionAuditError(
            f"{contract_path}: objective contract failed schema validation: {exc.errors()}"
        ) from exc


# ──────────────────────────────  evidence manifest  ──────────────────────────────


def _classify_evidence_type(path: Path) -> EvidenceType:
    return _EXTENSION_TO_TYPE.get(path.suffix.lower(), EvidenceType.file)


def _build_evidence_manifest(plan_dir: Path) -> list[EvidenceRef]:
    """Scan ``evidence/goal-governance/post_impl/<source>/<journey>/<file>``
    and reconstruct in-memory :class:`EvidenceRef` instances.

    Returns refs sorted by uri (stable for downstream hashing). Hash is
    sha256 of artifact bytes; type is inferred from filename extension.
    `captured_by` is set to ``'_manifest-rebuild'`` to distinguish
    these refs from live-captured ones in any introspection.

    D009 carry-forward: this function does FILESYSTEM IO + sha256 only.
    No imports of runtime_evidence/{web,ios,android,backend,harness}.py
    session classes."""
    post_impl = plan_dir / POST_IMPL_DIR
    if not post_impl.is_dir():
        return []

    refs: list[EvidenceRef] = []
    skipped_subdirs = {"audit"}
    """Subdirs that are NOT capture sources: 'audit/' holds F2 dispatch
    transcripts (F002 territory), not captured artifacts. Keep them out
    of the manifest so F2's own dispatch artifacts don't show up as
    'evidence' for the audit."""

    for source_dir in sorted(post_impl.iterdir()):
        if not source_dir.is_dir():
            continue
        if source_dir.name in skipped_subdirs:
            continue
        for journey_dir in sorted(source_dir.iterdir()):
            if not journey_dir.is_dir():
                continue
            for artifact in sorted(journey_dir.rglob("*")):
                if not artifact.is_file():
                    continue
                payload = artifact.read_bytes()
                rel = artifact.relative_to(plan_dir)
                refs.append(
                    EvidenceRef(
                        type=_classify_evidence_type(artifact),
                        uri=str(rel),
                        hash="sha256:" + hashlib.sha256(payload).hexdigest(),
                        captured_at=datetime.now(timezone.utc),
                        captured_by="_manifest-rebuild",
                        note=None,
                    )
                )
    return refs


# ──────────────────────────────  matcher  ──────────────────────────────


def _match_required_evidence(matcher: str, refs: list[EvidenceRef]) -> list[EvidenceRef]:
    """Return refs whose uri OR note contains ``matcher`` as a
    substring. Empty matcher → no matches (treated as
    operator-error-shaped input rather than 'matches everything').

    **D002 reminder**: this is a coverage heuristic. A hit means the
    operator-declared marker shows up somewhere in evidence metadata;
    it does NOT mean the captured artifact demonstrates the contract's
    intended behavior."""
    if not matcher:
        return []
    out: list[EvidenceRef] = []
    for ref in refs:
        if matcher in ref.uri:
            out.append(ref)
            continue
        if ref.note and matcher in ref.note:
            out.append(ref)
    return out


# ──────────────────────────────  journey-gap detection  ──────────────────────────────


def _journey_has_any_capture(journey_name: str, refs: list[EvidenceRef]) -> bool:
    """A journey is 'covered' (in the v1 coverage-heuristic sense) when
    at least one captured ref's uri contains a path segment matching
    ``/<journey_name>/``. Source-agnostic per D004."""
    needle = f"/{journey_name}/"
    return any(needle in ref.uri for ref in refs)


def _emit_journey_gaps(
    contract: ObjectiveContract,
    refs: list[EvidenceRef],
) -> list[CompletionFinding]:
    """Per contract user_journey, emit one ``journey_gap`` finding at
    severity='high' when the journey has zero captured refs of any
    source. Coverage heuristic — flags absence of any capture, not the
    absence of journey functionality."""
    out: list[CompletionFinding] = []
    for i, journey in enumerate(contract.user_journeys):
        if _journey_has_any_capture(journey.name, refs):
            continue
        out.append(
            CompletionFinding(
                finding_id=f"F2C-J{i + 1:03d}",
                gap_class="journey_gap",
                severity="high",
                title=f"No captured evidence for journey {journey.name!r}",
                narrative=(
                    f"The contract's user_journey {journey.name!r} has zero "
                    "captured EvidenceRef artifacts under any source surface "
                    "(web/ios/android/backend). This is a coverage gap — the "
                    "v1 auditor cannot tell whether the journey was implemented "
                    "or whether evidence simply was not captured. Operator "
                    "must either capture artifacts under the journey or record "
                    "an explicit non-goal in the contract."
                ),
                subsystem=_journey_subsystem(journey),
                journey=journey.name,
                matcher_string=None,
                evidence_uris=[],
            )
        )
    return out


def _journey_subsystem(journey) -> str:
    """Best-effort subsystem label for a journey. Uses the journey's
    first ``surfaces`` value when set; else the journey name (which is
    the F1 / D013 carry-forward — operator-supplied, project-agnostic)."""
    if journey.surfaces:
        return journey.surfaces[0]
    return journey.name


# ──────────────────────────────  required_evidence walker  ──────────────────────────────


def _emit_missing_evidence(
    contract: ObjectiveContract,
    refs: list[EvidenceRef],
) -> list[CompletionFinding]:
    """Walk ``contract.required_evidence`` strings; emit one
    ``missing_evidence`` finding per matcher with no captured ref hit.

    Severity is operator-tunable via convention in the matcher string
    (e.g. ``critical:matcher-text``); v1 defaults to ``medium`` for
    every missing matcher and lets operators set explicit severity
    via the F1 sufficiency-pattern prompt at lock time. Keeping the
    severity uniform avoids the auditor inventing severity guesses
    that don't reflect operator intent (D002)."""
    required = contract.required_evidence or []
    out: list[CompletionFinding] = []
    for i, matcher in enumerate(required):
        matched = _match_required_evidence(matcher, refs)
        if matched:
            continue
        out.append(
            CompletionFinding(
                finding_id=f"F2C-E{i + 1:03d}",
                gap_class="missing_evidence",
                severity="medium",
                title=f"Required evidence {matcher!r} not captured",
                narrative=(
                    f"The contract declares required_evidence={matcher!r} but "
                    "no captured EvidenceRef artifact under "
                    "evidence/goal-governance/post_impl/ has a uri or note "
                    "containing this substring. Either the implementation "
                    "didn't produce this artifact, the operator's matcher "
                    "string drifted from the actual filename / note convention, "
                    "or the contract should be updated to drop the requirement. "
                    "Per D002 — this is a v1 evidence-coverage heuristic; the "
                    "matcher only inspects uri / note metadata, not artifact "
                    "bytes, and a hit would not certify journey correctness "
                    "either."
                ),
                subsystem=_matcher_subsystem(matcher, contract),
                journey=_matcher_journey(matcher, contract),
                matcher_string=matcher,
                evidence_uris=[],
            )
        )
    return out


def _matcher_subsystem(matcher: str, contract: ObjectiveContract) -> str:
    """Best-effort subsystem label for a matcher. v1 picks the first
    surface from the first user_journey whose name appears in the
    matcher; falls back to the first user_journey's first surface."""
    for journey in contract.user_journeys:
        if journey.name in matcher and journey.surfaces:
            return journey.surfaces[0]
    if contract.user_journeys[0].surfaces:
        return contract.user_journeys[0].surfaces[0]
    return "unknown"


def _matcher_journey(matcher: str, contract: ObjectiveContract) -> str:
    """Best-effort journey label for a matcher. v1 picks the first
    user_journey whose name appears in the matcher; falls back to the
    first user_journey."""
    for journey in contract.user_journeys:
        if journey.name in matcher:
            return journey.name
    return contract.user_journeys[0].name


# ──────────────────────────────  envelope writer  ──────────────────────────────


def _write_envelope(
    plan_dir: Path,
    contract_ref: str,
    refs: list[EvidenceRef],
    findings: list[CompletionFinding],
) -> Path:
    plan_id = _read_frontmatter(plan_dir / "plan.md").get("id", "<unknown>")
    envelope = CompletionFindingsEnvelope(
        audit_kind=COMPLETION_AUDIT_KIND,
        generated_at=datetime.now(timezone.utc).isoformat(),
        plan_id=str(plan_id),
        contract_path=contract_ref,
        evidence_manifest_uris=sorted(r.uri for r in refs),
        findings=findings,
    )
    out_dir = plan_dir / POST_IMPL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / COMPLETION_FINDINGS_ARTIFACT
    out_path.write_text(json.dumps(envelope.model_dump(), indent=2, default=str) + "\n")
    return out_path


# ──────────────────────────────  public entrypoint  ──────────────────────────────


def _compute_findings(
    plan_dir: Path,
) -> tuple[list[EvidenceRef], list[CompletionFinding]]:
    """Steps 1–4 of the v1 heuristic (contract load, manifest scan,
    missing_evidence + journey_gap emission). Read-only."""
    contract = _load_objective_contract(plan_dir)
    refs = _build_evidence_manifest(plan_dir)
    findings = list(_emit_missing_evidence(contract, refs))
    findings.extend(_emit_journey_gaps(contract, refs))
    return refs, findings


def compute_completion_findings(plan_dir: Path) -> list[CompletionFinding]:
    """Pure form of :func:`run_completion_audit` — same v1 findings,
    NOTHING written to disk (plan 2026-07-27-001 F004 i1 codex finding).

    Read-only consumers (external-attach prompt rendering, attach-time
    response validation, the post-completion backstop's external-envelope
    freshness check) MUST use this instead of :func:`run_completion_audit`
    so a prompt render can never write ``completion_findings.json`` and a
    refused attach can never leave evidence behind. Deterministic over
    plan-dir content: fingerprints computed from these findings match a
    later :func:`run_completion_audit` over the same tree."""
    return _compute_findings(plan_dir)[1]


def run_completion_audit(plan_dir: Path) -> list[CompletionFinding]:
    """Run the F2 v1 evidence-coverage heuristic against ``plan_dir``.

    **D002**: this is a v1 evidence-coverage heuristic, not a semantic
    completion proof. Empty findings means "no obvious coverage gaps
    detected," NOT "plan complete." Downstream consumers (F003
    plan-close gate, dogfood dispositions) MUST read the envelope's
    ``audit_kind`` field and apply the v1 semantics.

    Composition:
      1. Load the contract via :func:`_load_objective_contract`.
      2. Rebuild the evidence manifest by scanning the post_impl tree.
      3. Walk ``contract.required_evidence`` for missing_evidence
         findings.
      4. Walk ``contract.user_journeys`` for journey_gap findings.
      5. Serialize all findings into a typed envelope at
         ``evidence/goal-governance/post_impl/completion_findings.json``.

    Returns the in-memory findings list. Steps 1–4 without the write are
    :func:`compute_completion_findings`.
    """
    refs, findings = _compute_findings(plan_dir)

    fm = _read_frontmatter(plan_dir / "plan.md")
    contract_ref = fm["links"]["objective_contract"]
    _write_envelope(plan_dir, contract_ref, refs, findings)
    return findings


# ──────────────────────────────  F0 adapters (D007 — consume, don't redefine)  ──────────────────────────────


def to_goal_gap_findings(findings: Iterable[CompletionFinding]) -> list[GoalGapFinding]:
    """Map :class:`CompletionFinding` instances into F0's
    :class:`GoalGapFinding` shape (severity / finding_id / issue /
    subsystem / journey). Severity normalization handled by F0's
    own validator; titles map into ``issue`` 1:1."""
    out: list[GoalGapFinding] = []
    for f in findings:
        out.append(
            GoalGapFinding(
                severity=f.severity,
                finding_id=f.finding_id,
                issue=f.title,
                subsystem=f.subsystem,
                journey=f.journey,
            )
        )
    return out


def cluster_findings(
    findings: Iterable[CompletionFinding],
) -> dict[tuple[str, str], list[CompletionFinding]]:
    """Group findings by (subsystem, journey) for F0's
    :func:`classify_goal_gap_cluster` consumption. F0's coherence_rule
    'subsystem_and_journey' (the default) expects this clustering."""
    clusters: dict[tuple[str, str], list[CompletionFinding]] = {}
    for f in findings:
        key = (f.subsystem, f.journey)
        clusters.setdefault(key, []).append(f)
    return clusters


def make_cluster_context(subsystem: str, journey: str) -> GoalGapClusterContext:
    """Construct a :class:`GoalGapClusterContext` for one
    (subsystem, journey) cluster with F0's default coherence_rule.
    F2 v1 always uses 'subsystem_and_journey'; richer override
    semantics (the contract's ``cluster_overrides`` field) are a v2
    follow-up."""
    return GoalGapClusterContext(
        subsystem=subsystem,
        journey=journey,
        coherence_rule="subsystem_and_journey",
        fits_existing_feature_scope=False,
        explicitly_out_of_scope=False,
        operator_deferred=False,
        existing_goal_gap_children=[],
    )


__all__ = [
    "COMPLETION_AUDIT_KIND",
    "COMPLETION_FINDINGS_ARTIFACT",
    "COMPLETION_GAP_CLASSES",
    "POST_IMPL_DIR",
    "CompletionAuditError",
    "CompletionFinding",
    "CompletionFindingsEnvelope",
    "EvidenceRef",
    "EvidenceType",
    "GapClass",
    "cluster_findings",
    "compute_completion_findings",
    "make_cluster_context",
    "run_completion_audit",
    "to_goal_gap_findings",
]
