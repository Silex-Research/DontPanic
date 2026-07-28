"""Plan F2 F003 — post-impl completion-audit gate + plan-close lifecycle.

Mirrors :mod:`sufficiency_gate` for the post-impl boundary. F1's gate
gates ``plan lock`` (draft → active); F2/F003's gate gates ``plan close``
(active → completed) and adds a supervisor backstop that catches
hand-edited active→completed flips lacking F2 audit evidence.

Public surface::

    enforce_completion_gate(plan_dir) -> None
        Read-only backstop. Raises :class:`CompletionGateError` if the
        plan is in ``status: completed`` but lacks the required F2
        evidence (completion_findings.json + audit envelope) AND no
        valid input-bound override exists. No-op when the plan is in
        any other status, when its goal_type is not in the gated set,
        or when valid evidence/override is present.

    close_plan(plan_dir, *, override_reason=None, approved_by=None,
               dry_run=False, dispatch=None) -> ClosePlanResult
        Canonical close-command body. Runs F001 + F002 + F0 classifier,
        decides pass/block, optionally writes input-bound override,
        flips plan.md status from ``active`` → ``completed`` on success.

    audit_plan(plan_dir, *, dispatch=None) -> AuditPlanResult
        Audit-only entry point. Runs F001 + F002 + F0 classifier and
        returns the decision. Does NOT mutate plan.md and does NOT
        write override.json.

    CompletionGateError (raised on refusals — usage error / blocking
        decision / stale override / contract failure)
    BackstopError (CompletionGateError subclass — hand-edited completed
        flip detected at supervisor entrypoint)
    OVERRIDE_ARTIFACT — override file name under
        ``evidence/goal-governance/post_impl/``

Override semantics (D004): SHA-256 hashes of FOUR inputs:

  - features.json
  - resolved objective_contract file
  - completion_findings.json
  - evidence manifest (concat of sorted ``uri|hash`` lines)

Drift in any input invalidates the override; the gate re-runs the
audit and refuses again unless re-approved.

D013 carry-forward: this module does NOT change any F001 or F002
internals. The ``dispatch`` seam is forwarded to F002 verbatim. F003
is purely the lifecycle / decision / mutation layer.

Capture-only invariant carries forward (Plan G D002 / F2 D009): F003
reads existing evidence; it does NOT invoke runtime_evidence/{web,ios,
android,backend,harness}.py session classes.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.completion_auditor import (
    POST_IMPL_DIR,
    CompletionAuditError,
    CompletionFinding,
    EvidenceRef,
    _build_evidence_manifest,
    _load_objective_contract,
    cluster_findings,
    compute_completion_findings,
    make_cluster_context,
    run_completion_audit,
)
from dontpanic_orchestrate.completion_dispatch import (
    CompletionAuditTranscript,
    CompletionDispatchError,
    DispatchFn,
    SameVendorRefused,
    _load_features,
    dispatch_completion_audit,
    external_audit_fingerprint,
)
from dontpanic_orchestrate.experience_readiness_gate import (
    GateResult,
    JourneyOutcome,
    OutcomeClass,
    classify_outcome,
    evaluate_consumer_outcome_gate,
    parse_product_metadata,
)
from dontpanic_orchestrate.experience_readiness_honesty import (
    RequiredDataSource,
    check_degraded_honesty,
)
from dontpanic_orchestrate.experience_readiness_typing import (
    CheckStatus,
    InvalidConsumerSurfaceTuple,
    check_journey,
)
from dontpanic_orchestrate.nested_orchestration import (
    GoalGapTriage,
    classify_goal_gap_cluster,
    goal_governance_evidence_path,
)
from dontpanic_orchestrate.sufficiency_auditor import (
    SufficiencyAuditError,
    _read_frontmatter,
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

# experience_readiness lives in the same models dir; experience_readiness_typing
# (imported above) inserts it onto sys.path, so this resolves in every checkout
# layout the _SCHEMA_CANDIDATES walk supports.
import experience_readiness as er  # noqa: E402
from models.plan_model import GoalType  # noqa: E402

# ──────────────────────────────  constants  ──────────────────────────────


_GATED_GOAL_TYPES: frozenset[GoalType] = frozenset(
    {
        GoalType.parity,
        GoalType.new_feature,
        GoalType.migration,
        GoalType.incident,
    }
)
"""Mirror of :data:`sufficiency_gate._GATED_GOAL_TYPES`. Plans whose
``goal_type`` is in this set require a post-impl completion audit
before status can flip ``active`` → ``completed``. Plans outside the
set (``infra`` / ``mechanical`` / ``refactor`` / ``no goal_type``) are
no-op exempt — their close-out is a pure status flip with no evidence
requirement (mirrors F1's lock behavior for goal_type=infra)."""

_COMPLETION_FINDINGS_ARTIFACT: str = "completion_findings.json"
"""Name of the F001 findings file under
``evidence/goal-governance/post_impl/``. Single source of truth for the
F003 hash computation; must match
:data:`completion_auditor.COMPLETION_FINDINGS_ARTIFACT`."""

OVERRIDE_ARTIFACT: str = "override.json"
"""Filename under ``evidence/goal-governance/post_impl/`` when the
operator records an explicit ``--ignore-completion-findings`` override
at close time. Mirror of F1's :data:`sufficiency_gate.OVERRIDE_ARTIFACT`."""

_OVERRIDE_SCHEMA_VERSION: int = 1

_AUDIT_DIR_NAME: str = "audit"
"""Subdirectory under ``post_impl`` where F002 writes
``audit-<auditor>-<iter>.{json,transcript.txt}``."""

_AUDIT_ENVELOPE_RE = re.compile(r"^audit-([a-z][a-z0-9_-]*)-(\d+)\.json$")
"""Filename pattern for F002 audit envelopes; the gate's backstop
uses this to find the most recent envelope without depending on
F002's filename construction internals."""

_BLOCKING_TRIAGES: frozenset[GoalGapTriage] = frozenset({"child_plan"})
"""F0 triage decisions that block ``plan close``. Per F003 design
(features.json acceptance #3): ``child_plan`` = adversarial / high
severity gap that requires its own plan, NOT operator-discretion fix."""

_BLOCKING_AUDIT_STATUSES: frozenset[str] = frozenset({"disagree", "dispatch_response_malformed"})
"""Cross-vendor envelope statuses that always block close. Offline
status (``dispatch_skipped_offline``) is conditionally blocking — only
when no override is supplied — so it lives in the close-decision
function rather than this set."""

_STATUS_ACTIVE_RE = re.compile(r"^(status:\s*)active\s*$", re.MULTILINE)
"""Frontmatter regex for the active → completed flip. Mirrors F1's
``_STATUS_DRAFT_RE`` shape."""


# ──────────────────────────────  exceptions  ──────────────────────────────


class CompletionGateError(ValueError):
    """Raised when the post-impl gate refuses a close action or backstop
    check. Subclasses ValueError so callers that don't want to import
    this module can catch it as a plain ValueError."""


class BackstopError(CompletionGateError):
    """Raised by :func:`enforce_completion_gate` when a plan with
    ``status: completed`` lacks the required F2 evidence (completion
    findings + audit envelope) AND no valid input-bound override exists.

    Distinct subclass so supervisor callers can recognize hand-edit
    detection at the dispatch boundary and surface a specific operator
    message ("you flipped status by hand — re-run dontpanic plan close")."""


# ──────────────────────────────  pure helpers  ──────────────────────────────


def _should_gate_completion(plan_data: dict[str, Any]) -> bool:
    """Return True iff the plan's ``goal_type`` is in
    :data:`_GATED_GOAL_TYPES`. Pure function on parsed frontmatter.

    Plans with no ``goal_type`` field, or with a ``goal_type`` outside
    the gated set (e.g. ``infra``, ``mechanical``, ``refactor``), are
    exempt — close-out is a pure status flip. This is the
    F003-equivalent of F1's ``_should_gate_sufficiency``."""
    raw = plan_data.get("goal_type")
    if raw is None:
        return False
    try:
        gt = GoalType(raw)
    except ValueError:
        # Plan-model schema validation flags unknown goal_types
        # elsewhere; gate stays permissive so we don't double-report.
        return False
    return gt in _GATED_GOAL_TYPES


def _sha256_hex(path: Path) -> str:
    """SHA-256 hex of file contents. ``sha256:`` prefixed for parity
    with F1's hash format (so override files cross-reference cleanly)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _sha256_hex_string(text: str) -> str:
    """SHA-256 hex of a UTF-8 string (used for the synthetic evidence
    manifest hash, which is concatenated ``uri|hash`` lines rather
    than a real file)."""
    digest = hashlib.sha256(text.encode("utf-8"))
    return f"sha256:{digest.hexdigest()}"


def _resolve_objective_contract_path(plan_dir: Path, plan_data: dict[str, Any]) -> Path:
    """Translate ``links.objective_contract`` into an absolute path.
    Mirrors F1's helper of the same name; raises
    :class:`CompletionGateError` so the close gate has a single
    exception base."""
    links = plan_data.get("links") or {}
    if not isinstance(links, dict):
        raise CompletionGateError(
            f"{plan_dir}/plan.md: links must be a mapping, got {type(links).__name__}"
        )
    ref = links.get("objective_contract")
    if not ref:
        raise CompletionGateError(
            f"{plan_dir}/plan.md: links.objective_contract is missing — required by "
            f"goal_type={plan_data.get('goal_type')!r} for the post-impl gate"
        )
    return (plan_dir / ref).resolve()


def _completion_findings_path(plan_dir: Path) -> Path:
    return goal_governance_evidence_path(plan_dir, "post_impl", _COMPLETION_FINDINGS_ARTIFACT)


def _override_path(plan_dir: Path) -> Path:
    return goal_governance_evidence_path(plan_dir, "post_impl", OVERRIDE_ARTIFACT)


def _audit_dir(plan_dir: Path) -> Path:
    return plan_dir / POST_IMPL_DIR / _AUDIT_DIR_NAME


def _evidence_manifest_signature(plan_dir: Path) -> str:
    """Build a deterministic, hash-stable string from the rebuilt
    evidence manifest. Sorted by ``(uri, hash)`` so reordering of
    filesystem walks does not change the digest. Empty manifest yields
    the empty string (its hash is well-defined and stable)."""
    refs = _build_evidence_manifest(plan_dir)
    pairs = sorted((ref.uri or "", ref.hash or "") for ref in refs)
    return "\n".join(f"{uri}|{hsh}" for uri, hsh in pairs)


def _compute_input_hashes(plan_dir: Path, plan_data: dict[str, Any]) -> dict[str, str]:
    """Compute the FOUR D004 hashes: features.json + objective_contract
    + completion_findings.json + evidence_manifest.

    Missing files raise :class:`CompletionGateError` with an
    operator-actionable message (mirrors F1's pattern). The manifest
    hash is over the concatenated ``uri|hash`` signature, NOT a file
    on disk, so the gate works even when no manifest file has been
    materialized (v1; v2 may emit a manifest file from F001)."""
    features_json = plan_dir / "features.json"
    if not features_json.is_file():
        raise CompletionGateError(f"{features_json}: features.json missing")
    contract_path = _resolve_objective_contract_path(plan_dir, plan_data)
    if not contract_path.is_file():
        raise CompletionGateError(f"{contract_path}: objective contract file missing")
    findings_path = _completion_findings_path(plan_dir)
    if not findings_path.is_file():
        raise CompletionGateError(
            f"{findings_path}: completion findings missing — "
            "run F001 (dontpanic plan audit / dontpanic plan close) first"
        )
    manifest_signature = _evidence_manifest_signature(plan_dir)
    return {
        "features_hash": _sha256_hex(features_json),
        "objective_contract_hash": _sha256_hex(contract_path),
        "completion_findings_hash": _sha256_hex(findings_path),
        "evidence_manifest_hash": _sha256_hex_string(manifest_signature),
    }


# ──────────────────────────────  override read/write  ──────────────────────────────


def _load_override(plan_dir: Path) -> dict[str, Any] | None:
    path = _override_path(plan_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CompletionGateError(f"{path}: malformed override file: {exc}") from exc
    if not isinstance(data, dict):
        raise CompletionGateError(f"{path}: override file must be a JSON object")
    return data


_OVERRIDE_HASH_KEYS: tuple[str, ...] = (
    "features_hash",
    "objective_contract_hash",
    "completion_findings_hash",
    "evidence_manifest_hash",
)


def _override_validity_check(
    override: dict[str, Any], current_hashes: dict[str, str]
) -> tuple[bool, list[str]]:
    """Compare stored override hashes against current input hashes.
    Drift in ANY of the four required hashes invalidates the
    override. Returns ``(is_valid, mismatched_keys)``."""
    mismatches: list[str] = []
    for key in _OVERRIDE_HASH_KEYS:
        if override.get(key) != current_hashes.get(key):
            mismatches.append(key)
    return len(mismatches) == 0, mismatches


def _resolved_approver(approved_by: str | None) -> str:
    """Mirror of F1's resolver. Falls through ``DONTPANIC_OPERATOR`` →
    ``USER`` → literal ``operator``."""
    if approved_by:
        return approved_by
    return os.environ.get("DONTPANIC_OPERATOR") or os.environ.get("USER") or "operator"


def _write_override(
    plan_dir: Path,
    *,
    reason: str,
    approved_by: str,
    plan_id: str,
    goal_type: str,
    objective_contract_path: str,
    hashes: dict[str, str],
    decision_summary: str,
) -> Path:
    """Persist override.json under ``post_impl/``. Caller is responsible
    for having already validated that an override is the right action
    (gate found a blocking decision)."""
    path = _override_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _OVERRIDE_SCHEMA_VERSION,
        "reason": reason,
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan_id": plan_id,
        "goal_type": goal_type,
        "objective_contract_path": objective_contract_path,
        "decision_summary": decision_summary,
        **hashes,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return path


# ──────────────────────────────  audit envelope discovery  ──────────────────────────────


def _find_audit_envelopes(plan_dir: Path) -> list[Path]:
    """List audit envelope files matching F002's filename pattern,
    sorted by iteration ascending. Empty list when no envelopes exist."""
    audit_dir = _audit_dir(plan_dir)
    if not audit_dir.is_dir():
        return []
    out: list[tuple[int, Path]] = []
    for entry in audit_dir.iterdir():
        m = _AUDIT_ENVELOPE_RE.match(entry.name)
        if m is None:
            continue
        try:
            iteration = int(m.group(2))
        except ValueError:
            continue
        out.append((iteration, entry))
    out.sort(key=lambda pair: pair[0])
    return [path for _, path in out]


def _load_latest_audit_envelope(
    plan_dir: Path, auditor: str | None = None
) -> CompletionAuditTranscript | None:
    """Load the highest-iteration envelope file as a typed transcript.
    Returns ``None`` when no envelope exists. Raises
    :class:`CompletionGateError` on malformed envelope files.

    Iteration numbers are per-auditor (plan 2026-06-12-001 F002), so in a
    mixed-auditor directory the globally-highest number can belong to a
    stale foreign auditor. Pass ``auditor`` to select the highest iteration
    FOR THAT AUDITOR; ``None`` keeps the global-highest behaviour for
    callers that validate historical state across auditor switches."""
    envelopes = _find_audit_envelopes(plan_dir)
    if auditor is not None:
        envelopes = [
            e for e in envelopes
            if (m := _AUDIT_ENVELOPE_RE.match(e.name)) and m.group(1) == auditor
        ]
    if not envelopes:
        return None
    return _load_envelope(envelopes[-1])


def _load_envelope(path: Path) -> CompletionAuditTranscript:
    """Load + schema-validate one envelope file; raises
    :class:`CompletionGateError` on malformed content."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CompletionGateError(f"{path}: malformed audit envelope: {exc}") from exc
    try:
        return CompletionAuditTranscript.model_validate(raw)
    except Exception as exc:
        raise CompletionGateError(
            f"{path}: audit envelope failed schema validation: {exc}"
        ) from exc


def _has_goal_kind_envelope(plan_dir: Path) -> bool:
    """True iff at least one audit envelope carries goal-gate evidence.

    Plan 2026-07-27-001 F004: an attached external envelope with
    ``audit_kind='experience'`` reviews the experience surface, not the
    goal contract — it must never satisfy the goal-gate backstop's
    evidence requirement. Pre-F004 envelopes have no ``audit_kind``
    (None) and are always goal evidence.

    F004 i1 (codex finding): an EXTERNAL goal envelope additionally
    proves content freshness before it counts — its
    ``source_fingerprint`` and graded finding ids must match the CURRENT
    v1 findings (via :func:`_latest_fresh_external_envelope` over the
    pure :func:`compute_completion_findings`, keeping this backstop
    read-only). A stale attached envelope predates a findings/contract
    change and cannot vouch for the completed status; dispatched
    envelopes keep the existence-only check (their staleness is governed
    at close time by the audit pipeline that produced them)."""
    has_external_goal = False
    for path in reversed(_find_audit_envelopes(plan_dir)):
        transcript = _load_envelope(path)
        if transcript.audit_kind not in (None, "goal"):
            continue
        if transcript.provenance == "external":
            has_external_goal = True
            continue
        return True
    if not has_external_goal:
        return False
    try:
        findings = compute_completion_findings(plan_dir)
    except (CompletionAuditError, OSError):
        # Findings can't be recomputed (contract missing/invalid), so the
        # external envelope's freshness is unprovable — treat as stale.
        return False
    return (
        _latest_fresh_external_envelope(plan_dir, kind="goal", findings=findings)
        is not None
    )


def _latest_fresh_external_envelope(
    plan_dir: Path,
    *,
    kind: str,
    findings: list[CompletionFinding],
) -> CompletionAuditTranscript | None:
    """Select the freshest attached external audit envelope of ``kind``
    that still matches the CURRENT v1 findings (Plan 2026-07-27-001 F004,
    D001 B1).

    Kind-strict: a ``goal`` envelope never feeds the experience check and
    vice versa. Freshness is CONTENT-based (F004 i1): the envelope's graded
    finding_ids (``auditor-overlay-*`` excluded) must exactly equal the
    current finding-id set AND its recorded ``source_fingerprint`` must
    match the current :func:`external_audit_fingerprint` over the findings
    content + contract + features + evidence manifest. Ordinal finding_ids like
    ``F2C-J001`` are reused across audit runs, so an id-only comparison
    would keep an envelope "fresh" after the finding substance changed;
    the fingerprint stales it. Envelopes without a fingerprint (pre-i1)
    are always stale. Findings drift after attach makes the envelope
    stale, and a stale envelope is ignored (the dispatched path or a
    re-attach takes over). Ties rank by mtime then iteration (D028
    semantics). Envelope files that fail schema validation are skipped
    here rather than raised: this selector runs on every audit, and a
    historical junk file must not brick the dispatched path it would
    otherwise fall back to."""
    expected = {f.finding_id for f in findings}
    expected_fingerprint: str | None = None
    ranked: list[tuple[float, int, CompletionAuditTranscript]] = []
    for path in _find_audit_envelopes(plan_dir):
        m = _AUDIT_ENVELOPE_RE.match(path.name)
        try:
            transcript = _load_envelope(path)
        except CompletionGateError:
            continue
        if transcript.provenance != "external" or transcript.audit_kind != kind:
            continue
        graded = {
            d.finding_id
            for d in transcript.findings_dispositions
            if not d.finding_id.startswith("auditor-overlay-")
        }
        if graded != expected:
            continue
        if transcript.source_fingerprint is None:
            continue  # pre-fingerprint envelope: cannot prove content freshness
        if expected_fingerprint is None:
            # Lazy: only pay the contract/manifest hash when a candidate
            # survived the cheap id-set check.
            expected_fingerprint = external_audit_fingerprint(plan_dir, findings)
        if transcript.source_fingerprint != expected_fingerprint:
            continue
        ranked.append((path.stat().st_mtime, int(m.group(2)), transcript))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[-1][2]


# ──────────────────────────────  classification  ──────────────────────────────


@dataclass(frozen=True)
class ClusterDecision:
    """One F0 triage call result for a (subsystem, journey) cluster."""

    subsystem: str
    journey: str
    finding_count: int
    triage: GoalGapTriage


def _classify(
    findings: list[CompletionFinding],
) -> list[ClusterDecision]:
    """Run :func:`classify_goal_gap_cluster` per (subsystem, journey)
    cluster of F2 findings. Returns one :class:`ClusterDecision` per
    cluster. Empty findings list → empty list (no clusters to classify
    means no triage signal to act on; close path treats that as
    pass-eligible)."""
    if not findings:
        return []
    clusters = cluster_findings(findings)
    out: list[ClusterDecision] = []
    for (subsystem, journey), gap_findings in sorted(clusters.items()):
        ctx = make_cluster_context(subsystem, journey)
        triage = classify_goal_gap_cluster(gap_findings, ctx)
        out.append(
            ClusterDecision(
                subsystem=subsystem,
                journey=journey,
                finding_count=len(gap_findings),
                triage=triage,
            )
        )
    return out


def _typed_evidence_refs(plan_dir: Path) -> list[EvidenceRef]:
    """Typed :class:`EvidenceRef` rows recorded in ``features.json``
    (``features[].evidence_refs``) — the only place experience-readiness
    typing fields (surface_class / availability / consumer_family /
    data_provenance / evidence_class) are persisted. The filesystem
    manifest rebuild is untyped by construction, so it can never satisfy
    the typed checkers; refs that fail schema validation contribute
    nothing (fail-closed)."""
    try:
        features = _load_features(plan_dir)
    except Exception:  # noqa: BLE001 — features load errors surface on the goal path
        return []
    refs: list[EvidenceRef] = []
    for feature in features:
        for raw in feature.get("evidence_refs") or []:
            # Malformed ref contributes no typed signal (fail-closed).
            with contextlib.suppress(Exception):
                refs.append(EvidenceRef.model_validate(raw))
    return refs


def _journey_outcome_class(
    journey,
    refs: list[EvidenceRef],
) -> tuple[OutcomeClass, str]:
    """Plan 2026-07-27-001 F004 i2 — classify ONE consumer journey through
    the established typed checkers (2a-core :func:`check_journey`, 2a-F004
    :func:`check_degraded_honesty`, D021 :func:`classify_outcome`).

    ``refs`` are the typed refs BOUND to this journey (uri contains
    ``/<journey.name>/``, same binding heuristic as the v1 auditor). A
    journey is ``satisfied`` only when typing is satisfied, honesty is
    honest, AND a real (non-seeded, available) execution ref exists —
    seeded, dishonest, wrong-family, or merely-present-but-untyped
    artifacts all classify as ``unproven`` instead of silently passing.
    Returns ``(outcome, detail)`` where ``detail`` names the verdicts for
    the operator-facing blocking reason. Malformed surface declarations
    fail closed to ``unproven``."""
    try:
        requirements = [
            (er.resolve_surface_token(token), er.ClaimKind.read_only)
            for token in (journey.surfaces or [])
        ]
    except er.UnknownSurfaceToken as exc:
        return OutcomeClass.unproven, f"unknown surface token ({exc})"
    if not requirements:
        return OutcomeClass.unproven, "journey declares no surfaces"

    try:
        group_results, typing_verdict = check_journey(journey.consumer, requirements, refs)
    except InvalidConsumerSurfaceTuple as exc:
        return OutcomeClass.unproven, f"consumer/surface mismatch ({exc})"

    # Honesty contract derived from the journey's own declarations: every
    # data_source its typed refs claim must be honest across the families the
    # journey's surfaces span. Allowed degraded modes come from the refs
    # themselves — the gate has no per-plan mode policy, so honesty here
    # checks masking/conflict/omission, not mode selection (D004 mode policy
    # stays with plan-specific honesty contracts).
    required_families = frozenset(
        er.surface_family(sc) for sc, _ in requirements
    )
    sources = sorted({r.data_source for r in refs if r.data_source})
    allowed_modes = {
        ds: {r.degraded_mode for r in refs if r.data_source == ds and r.degraded_mode}
        for ds in sources
    }
    honesty = check_degraded_honesty(
        [RequiredDataSource(ds, required_families) for ds in sources],
        allowed_modes,
        refs,
    )

    def _family_fully_satisfied(fam) -> bool:
        fam_results = [
            r for r in group_results if er.surface_family(r.surface_class) is fam
        ]
        return bool(fam_results) and all(
            r.status is CheckStatus.satisfied for r in fam_results
        )

    outcome = classify_outcome(
        journey.consumer,
        typing_verdict=typing_verdict,
        honesty_verdict=honesty.verdict,
        real_execution=honesty.satisfied,
        other_family_satisfied=(
            _family_fully_satisfied(er.SurfaceFamily.human)
            or _family_fully_satisfied(er.SurfaceFamily.agent)
        ),
    )
    detail = (
        f"typing={typing_verdict.value} honesty={honesty.verdict.value} "
        f"real_execution={honesty.satisfied}"
    )
    return outcome, detail


def _experience_gate_decision(
    plan_dir: Path,
    plan_data: dict[str, Any],
    findings: list[CompletionFinding],
) -> tuple[GateResult | None, CompletionAuditTranscript | None, list[str]]:
    """Plan 2026-07-27-001 F004 i2 — production consumer of the
    experience-readiness gate (plan 2026-06-14-002 D021), wired into
    :func:`audit_plan` independently of the codex F0 cluster triage.

    Builds one :class:`JourneyOutcome` per contract ``user_journey`` that
    DECLARES a ``consumer`` (D030 opt-in — journeys without a consumer are
    substrate/legacy and never block here). The outcome class comes from
    the established typed checkers via :func:`_journey_outcome_class` —
    NOT from the mere presence of captured artifacts, so a seeded,
    dishonest, or wrong-family capture classifies as ``unproven`` rather
    than suppressing the block (codex F004-i1 finding).

    A fresh operator-attached EXPERIENCE envelope (``--kind experience``)
    is consumed ONLY as a structured disposition overlay: a journey counts
    as dispositioned when the external auditor explicitly REFUTED every
    one of its ``journey_gap`` findings (``agree=false`` + ``no_finding``);
    it never upgrades the typed outcome itself. A structured ``non_goals``
    entry naming the journey (exact name or ``journey:<name>``) defers it.

    Returns ``(gate_result, experience_envelope, blocking_reasons)``;
    ``(None, None, [])`` when the contract cannot be loaded — the goal
    path will already have surfaced that failure."""
    try:
        contract = _load_objective_contract(plan_dir)
    except Exception:  # noqa: BLE001 — goal path owns contract-load errors
        return None, None, []

    exp_findings = [f for f in findings if f.gap_class == "journey_gap"]
    gaps_by_journey: dict[str, list[CompletionFinding]] = {}
    for f in exp_findings:
        gaps_by_journey.setdefault(f.journey, []).append(f)

    envelope = (
        _latest_fresh_external_envelope(plan_dir, kind="experience", findings=exp_findings)
        if exp_findings
        else None
    )

    def _refuted(finding: CompletionFinding) -> bool:
        if envelope is None:
            return False
        return any(
            d.finding_id == finding.finding_id
            and not d.agree
            and d.severity_disposition == "no_finding"
            for d in envelope.findings_dispositions
        )

    typed_refs = _typed_evidence_refs(plan_dir)
    non_goals = set(contract.non_goals or [])
    outcomes: list[JourneyOutcome] = []
    details: dict[str, str] = {}
    for journey in contract.user_journeys or []:
        if journey.consumer is None:
            continue  # D030: consumer-outcome enforcement is opt-in per journey
        needle = f"/{journey.name}/"
        bound = [r for r in typed_refs if needle in (r.uri or "")]
        outcome, detail = _journey_outcome_class(journey, bound)
        details[journey.name] = detail
        gaps = gaps_by_journey.get(journey.name, [])
        outcomes.append(
            JourneyOutcome(
                journey=journey.name,
                consumer=journey.consumer,
                outcome=outcome,
                deferred=(
                    journey.name in non_goals or f"journey:{journey.name}" in non_goals
                ),
                # Disposition overlay only: the envelope refutes the v1
                # journey_gap findings it graded; it cannot vouch for a
                # journey whose unproven signal came from the typed checkers
                # (seeded/dishonest/wrong-family evidence has no journey_gap
                # finding to refute — defer or override instead).
                dispositioned=bool(gaps) and all(_refuted(g) for g in gaps),
            )
        )

    result = evaluate_consumer_outcome_gate(
        plan_data.get("goal_type"),
        opted_in=False,
        product_metadata=parse_product_metadata(plan_data.get("delivery_class")),
        journeys=outcomes,
    )
    reasons = []
    for gf in result.findings:
        if not gf.blocks:
            continue
        gap_ids = ", ".join(
            f.finding_id for f in gaps_by_journey.get(gf.journey, [])
        ) or "none (typed-evidence verdict)"
        reasons.append(
            f"experience gate: journey {gf.journey!r} (consumer={gf.consumer}) outcome "
            f"unproven — {details.get(gf.journey, 'no typed verdict')}; "
            f"journey_gap finding(s): {gap_ids}. "
            "Capture typed real-execution evidence, attach a refuting external "
            "experience audit (`dontpanic plan attach-goal-audit --kind experience`), "
            "defer the journey via contract non_goals, or record a close override."
        )
    return result, envelope, reasons


# ──────────────────────────────  result dataclasses  ──────────────────────────────


@dataclass
class AuditPlanResult:
    """Outcome of :func:`audit_plan`. ``blocking`` collapses the
    decision matrix into a single bool the CLI can branch on."""

    plan_id: str
    findings: list[CompletionFinding] = field(default_factory=list)
    cluster_decisions: list[ClusterDecision] = field(default_factory=list)
    audit_transcript: CompletionAuditTranscript | None = None
    blocking: bool = False
    reasons: list[str] = field(default_factory=list)
    experience_gate: GateResult | None = None
    experience_transcript: CompletionAuditTranscript | None = None


@dataclass
class ClosePlanResult:
    """Outcome of :func:`close_plan`. ``status_flipped`` is True iff
    the plan.md status was actually mutated. ``override_recorded`` is
    True iff override.json was written this run."""

    plan_id: str
    plan_md: Path
    status_flipped: bool = False
    override_recorded: bool = False
    audit_result: AuditPlanResult | None = None
    notes: list[str] = field(default_factory=list)


# ──────────────────────────────  decision logic  ──────────────────────────────


def _decide_blocking(
    transcript: CompletionAuditTranscript | None,
    cluster_decisions: list[ClusterDecision],
    *,
    has_override: bool,
) -> tuple[bool, list[str]]:
    """Apply F003's block-decision matrix. Returns ``(blocking,
    reasons)``. ``has_override`` controls offline-mode handling per
    the F003 description: offline status blocks unless an override is
    in place."""
    reasons: list[str] = []
    if transcript is not None:
        if transcript.status in _BLOCKING_AUDIT_STATUSES:
            reasons.append(
                f"audit envelope status={transcript.status!r} (cross-vendor disagreement "
                "or auditor response failed schema)"
            )
        elif transcript.status == "dispatch_skipped_offline" and not has_override:
            reasons.append(
                "audit envelope status='dispatch_skipped_offline' and no operator "
                "override supplied — record one with --ignore-completion-findings "
                "<reason> if the offline run was intentional"
            )
    blocking_clusters = [d for d in cluster_decisions if d.triage in _BLOCKING_TRIAGES]
    for d in blocking_clusters:
        reasons.append(
            f"cluster {d.subsystem}/{d.journey} ({d.finding_count} finding(s)) "
            f"classified as {d.triage!r}"
        )
    return (len(reasons) > 0), reasons


# ──────────────────────────────  audit / close pipelines  ──────────────────────────────


def audit_plan(
    plan_dir: Path,
    *,
    dispatch: DispatchFn | None = None,
    iteration: int | None = None,
    implementer_agent: str | None = None,
) -> AuditPlanResult:
    """Run the full F001 → F002 → F0-classify pipeline for a plan and
    return the decision. Does NOT mutate plan.md or write override.json.

    For non-gated plans (``goal_type`` outside :data:`_GATED_GOAL_TYPES`,
    or no ``goal_type``), returns a vacuous result with
    ``blocking=False`` — there is nothing to audit.

    Used both by the ``dontpanic plan audit`` CLI subcommand and by
    :func:`close_plan` as the upstream decision producer."""
    plan_dir = Path(plan_dir).resolve()
    if not plan_dir.is_dir():
        raise CompletionGateError(f"plan_dir does not exist: {plan_dir}")

    plan_md = plan_dir / "plan.md"
    plan_data = _read_frontmatter(plan_md)
    plan_id = plan_data.get("id", plan_dir.name)

    if not _should_gate_completion(plan_data):
        return AuditPlanResult(
            plan_id=plan_id,
            findings=[],
            cluster_decisions=[],
            audit_transcript=None,
            blocking=False,
            reasons=[
                f"plan goal_type={plan_data.get('goal_type')!r} is not in the gated "
                "set — completion audit is a no-op (mirror of F1's lock behavior)"
            ],
        )

    findings = run_completion_audit(plan_dir)
    # Plan 2026-07-27-001 F004 (D001 B1): prefer a fresh operator-attached
    # external goal audit (e.g. Gemini) over a paid dispatch when present.
    # Kind-strict + content-fresh (see _latest_fresh_external_envelope).
    # Experience-kind envelopes never satisfy the goal gate.
    external = _latest_fresh_external_envelope(
        plan_dir, kind="goal", findings=findings
    )
    if external is not None:
        transcript = external
    else:
        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent=implementer_agent,
            iteration=iteration,
            dispatch=dispatch,
        )
    cluster_decisions = _classify(findings)
    blocking, reasons = _decide_blocking(transcript, cluster_decisions, has_override=False)
    # F004 i1: consumer-experience gate (D021) — runs independently of the
    # F0 cluster triage. Consumes a fresh --kind experience envelope as the
    # structured disposition record; unproven consumer journeys block.
    experience_gate, experience_transcript, experience_reasons = _experience_gate_decision(
        plan_dir, plan_data, findings
    )
    if experience_reasons:
        blocking = True
        reasons.extend(experience_reasons)
    return AuditPlanResult(
        plan_id=plan_id,
        findings=findings,
        cluster_decisions=cluster_decisions,
        audit_transcript=transcript,
        blocking=blocking,
        reasons=reasons,
        experience_gate=experience_gate,
        experience_transcript=experience_transcript,
    )


def close_plan(
    plan_dir: Path,
    *,
    override_reason: str | None = None,
    approved_by: str | None = None,
    dry_run: bool = False,
    dispatch: DispatchFn | None = None,
    iteration: int | None = None,
    implementer_agent: str | None = None,
) -> ClosePlanResult:
    """Canonical close-command body. Read-only when ``dry_run=True``.

    Refuses if the plan is not in ``status: active`` (idempotent
    behavior: re-closing a completed plan is a no-op-with-note, not
    a silent success). Runs the audit; if blocking AND
    ``override_reason`` supplied, validates inputs and writes
    override.json. Then mutates plan.md ``active`` → ``completed``.

    The CLI subcommand ``dontpanic plan close`` wraps this function.
    The override flag (``--ignore-completion-findings <reason>``)
    lives only at this level; downstream supervisor backstop calls
    don't grow override surface."""
    plan_dir = Path(plan_dir).resolve()
    plan_md = plan_dir / "plan.md"
    plan_data = _read_frontmatter(plan_md)
    plan_id = plan_data.get("id", plan_dir.name)

    status = plan_data.get("status")
    if status == "completed":
        # Idempotent re-close: not an error, just a note.
        return ClosePlanResult(
            plan_id=plan_id,
            plan_md=plan_md,
            status_flipped=False,
            override_recorded=False,
            audit_result=None,
            notes=[f"plan already completed (status={status!r}); no action taken"],
        )
    if status != "active":
        raise CompletionGateError(
            f"{plan_md}: refusing to close — current status={status!r}, expected 'active'"
        )

    if not _should_gate_completion(plan_data):
        # Exempt path: pure status flip. Override flag is meaningless;
        # refuse loudly so operator intent stays clear (matches F1
        # behavior on the lock side).
        if override_reason is not None:
            raise CompletionGateError(
                f"{plan_md}: --ignore-completion-findings is meaningless for a plan "
                f"with goal_type={plan_data.get('goal_type')!r} (not in the gated set)"
            )
        if dry_run:
            return ClosePlanResult(
                plan_id=plan_id,
                plan_md=plan_md,
                status_flipped=False,
                override_recorded=False,
                audit_result=None,
                notes=[
                    f"goal_type={plan_data.get('goal_type')!r} is exempt from the F2 "
                    "completion gate; --dry-run would flip status active → completed"
                ],
            )
        _mutate_plan_status_to_completed(plan_md)
        return ClosePlanResult(
            plan_id=plan_id,
            plan_md=plan_md,
            status_flipped=True,
            override_recorded=False,
            audit_result=None,
            notes=[
                f"goal_type={plan_data.get('goal_type')!r} is exempt from the F2 "
                "completion gate; status flipped active → completed without audit"
            ],
        )

    audit_result = audit_plan(
        plan_dir,
        dispatch=dispatch,
        iteration=iteration,
        implementer_agent=implementer_agent,
    )

    if audit_result.blocking:
        if override_reason is None:
            raise CompletionGateError(
                f"plan close refused for {plan_id} — blocking decision:\n"
                + "\n".join(f"  - {r}" for r in audit_result.reasons)
                + "\nto override: dontpanic plan close <plan-id> "
                '--ignore-completion-findings "<reason>"'
            )
        # Override path: validate inputs (raises if any of the four
        # required artifacts is missing) and write override.json.
        if dry_run:
            return ClosePlanResult(
                plan_id=plan_id,
                plan_md=plan_md,
                status_flipped=False,
                override_recorded=False,
                audit_result=audit_result,
                notes=[
                    "blocking decision; --dry-run would write override.json + flip status",
                    *audit_result.reasons,
                ],
            )
        hashes = _compute_input_hashes(plan_dir, plan_data)
        contract_ref = (plan_data.get("links") or {}).get("objective_contract", "")
        decision_summary = "; ".join(audit_result.reasons)[:500] or "no recorded reasons"
        _write_override(
            plan_dir,
            reason=override_reason,
            approved_by=_resolved_approver(approved_by),
            plan_id=plan_id,
            goal_type=plan_data.get("goal_type", "<unknown>"),
            objective_contract_path=contract_ref,
            hashes=hashes,
            decision_summary=decision_summary,
        )
        _mutate_plan_status_to_completed(plan_md)
        return ClosePlanResult(
            plan_id=plan_id,
            plan_md=plan_md,
            status_flipped=True,
            override_recorded=True,
            audit_result=audit_result,
            notes=[
                "operator override recorded at "
                f"{_override_path(plan_dir)} (input-bound; drift invalidates)"
            ],
        )

    # Non-blocking path.
    if dry_run:
        return ClosePlanResult(
            plan_id=plan_id,
            plan_md=plan_md,
            status_flipped=False,
            override_recorded=False,
            audit_result=audit_result,
            notes=["audit passed; --dry-run would flip status active → completed"],
        )
    if override_reason is not None:
        # Operator supplied an override on a passing audit; refuse so
        # they don't accidentally record a bogus override file (the
        # override is meant for blocking decisions only).
        raise CompletionGateError(
            f"{plan_md}: --ignore-completion-findings supplied but audit passed — "
            "refusing to record a no-op override; remove the flag and re-run"
        )
    _mutate_plan_status_to_completed(plan_md)
    return ClosePlanResult(
        plan_id=plan_id,
        plan_md=plan_md,
        status_flipped=True,
        override_recorded=False,
        audit_result=audit_result,
        notes=["audit passed; status flipped active → completed"],
    )


# ──────────────────────────────  plan.md mutation  ──────────────────────────────


def _mutate_plan_status_to_completed(plan_md: Path) -> None:
    """Flip ``status: active`` → ``status: completed`` inside plan.md
    frontmatter. Mirrors :func:`sufficiency_gate._mutate_plan_status_to_active`
    — single-line regex within the YAML block, preserving all other
    formatting. Refuses on missing or malformed frontmatter."""
    text = plan_md.read_text()
    if not text.startswith("---"):
        raise CompletionGateError(f"{plan_md}: missing frontmatter delimiter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise CompletionGateError(f"{plan_md}: malformed frontmatter")
    fm_text = parts[1]
    new_fm, n = _STATUS_ACTIVE_RE.subn(r"\1completed", fm_text, count=1)
    if n == 0:
        raise CompletionGateError(
            f"{plan_md}: no `status: active` line in frontmatter — refusing to flip"
        )
    plan_md.write_text("---" + new_fm + "---" + parts[2])


# ──────────────────────────────  supervisor backstop  ──────────────────────────────


def enforce_completion_gate(plan_dir: Path) -> None:
    """Read-only post-impl backstop.

    Behavior:

    1. Plan not in ``status: completed`` → silent no-op (this gate
       only fires on the post-completion boundary).
    2. Plan in ``status: completed`` but ``goal_type`` outside the
       gated set → silent no-op (exempt plans never had an audit
       requirement).
    3. Plan in ``status: completed``, gated goal_type, and EITHER a
       valid completion_findings.json + audit envelope exist OR a
       valid (hashes-match) override.json exists → silent no-op.
    4. Anything else (status='completed' but missing both evidence
       and override; or override is stale) → :class:`BackstopError`.

    Mirror of :func:`sufficiency_gate.enforce_sufficiency_gate` —
    pure modulo file I/O, never mutates state.
    """
    plan_dir = Path(plan_dir).resolve()
    plan_md = plan_dir / "plan.md"
    plan_data = _read_frontmatter(plan_md)

    if plan_data.get("status") != "completed":
        return  # gate only fires on the completion boundary
    if not _should_gate_completion(plan_data):
        return  # exempt plan — no audit requirement

    findings_path = _completion_findings_path(plan_dir)
    has_findings = findings_path.is_file()
    # F004 i1: kind-aware — an attached external envelope with
    # audit_kind='experience' reviews the experience surface and must not
    # satisfy the GOAL gate's evidence requirement. Only goal-kind (or
    # pre-F004 kind-less) envelopes count here.
    has_envelope = _has_goal_kind_envelope(plan_dir)
    override = _load_override(plan_dir)

    if override is not None:
        # Override path: validate hashes; stale override is treated as
        # a hand-edit (operator must re-run plan close).
        try:
            current_hashes = _compute_input_hashes(plan_dir, plan_data)
        except CompletionGateError as exc:
            raise BackstopError(
                f"plan {plan_data.get('id', plan_dir.name)!r} is status='completed' "
                f"with override.json but a required input is missing: {exc}"
            ) from exc
        is_valid, mismatched = _override_validity_check(override, current_hashes)
        if is_valid:
            return  # operator-recorded override; durable, hash-bound
        raise BackstopError(
            f"{_override_path(plan_dir)}: override is stale — input(s) changed "
            f"since approval: {', '.join(mismatched)}. Re-run "
            "`dontpanic plan close` (or remove override.json to force the "
            "standard gate path)."
        )

    if has_findings and has_envelope:
        # Evidence-on-disk path: the close ran cleanly. We don't
        # re-classify here (that's the close-time decision); the
        # backstop only verifies the required artifacts exist.
        return

    missing = []
    if not has_findings:
        missing.append("completion_findings.json")
    if not has_envelope:
        missing.append(
            "goal-kind audit envelope (audit-<auditor>-<iter>.json; an "
            "experience-kind envelope does not satisfy the goal gate, and an "
            "attached external envelope must still match the current findings "
            "fingerprint — a stale attach does not count)"
        )
    raise BackstopError(
        f"plan {plan_data.get('id', plan_dir.name)!r} is status='completed' but "
        f"missing F2 audit evidence: {', '.join(missing)}. "
        "Run `dontpanic plan close <plan-id>` (or record an "
        "--ignore-completion-findings override) instead of hand-editing "
        "the status field."
    )


# ──────────────────────────────  re-export base exceptions  ──────────────────────────────
# Callers (CLI) import these here so a single module surface backs the
# F003 lifecycle layer. F1 / F002 errors propagate unchanged.


__all__ = [
    "OVERRIDE_ARTIFACT",
    "AuditPlanResult",
    "BackstopError",
    "ClosePlanResult",
    "ClusterDecision",
    "CompletionAuditError",
    "CompletionDispatchError",
    "CompletionGateError",
    "DispatchFn",
    "SameVendorRefused",
    "SufficiencyAuditError",
    "audit_plan",
    "close_plan",
    "enforce_completion_gate",
]


# Type-checker hook for re-exported callable type alias.
_DispatchFnAlias: Callable = DispatchFn  # noqa: F841
