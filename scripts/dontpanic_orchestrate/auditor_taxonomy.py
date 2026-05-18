"""Plan 2026-05-08-003 F003 — auditor verdict taxonomy.

Pure classification layer for ``stopped_no_progress`` terminals so the
operator sees whether the auditor's remaining objection is an environmental
harness blocker, an evidence-shape disagreement against equivalent saved
evidence, an out-of-scope finding, or a real implementation defect.

Design notes (D006):
  * Classification is **advisory only**. ``implementation_defect``, mixed
    sets, and ``unknown`` always stay blocking — the supervisor never
    auto-signs-off a feature on the basis of a downgraded classification.
  * The classifier is pure: it reads already-loaded audit envelopes plus
    the finding dict itself. No subprocess, no network, no filesystem
    probing. Callers that need disk reads do them upstream.
  * No ``agent-conventions`` schema changes — the existing finding shape
    (severity / category / file / line / feature_id / issue / evidence /
    recommendation) is the input surface. Heuristics derive from `issue`
    + `evidence` text plus `category` + `feature_id` + `file` fields.

Closed v0 taxonomy:

  - ``implementation_defect`` — substantive correctness/security/etc.
    finding with no signal of environmental, shape, or scope mismatch.
    BLOCKING.
  - ``environmental_reproduction_failure`` — auditor could not run a
    test, build, tool, or auth flow due to sandbox/CLI/host state.
    Advisory; operator may run the verification locally.
  - ``evidence_shape_disagreement`` — auditor wanted a different
    representation of evidence (screenshot vs log, JSON vs text, etc.)
    AND equivalent saved evidence is referenced in the audit trail.
    Advisory; operator may surface the existing evidence.
  - ``scope_overreach`` — finding lies outside the dispatched feature's
    declared scope (mismatched feature_id, or the finding text declares
    itself out-of-scope). Advisory; operator queues a follow-up.
  - ``spec_ambiguity`` — Plan 2026-05-11-002 v3 F003 — low/medium
    severity finding whose category is documentation, naming,
    convention, or placement. The implementer's reading and the
    auditor's reading both fit the spec, but the spec is silent on the
    specific point — patch the spec then resume, or accept the
    implementer's reading. Advisory; non-blocking.
  - ``unknown`` — anything the classifier cannot place. BLOCKING.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

# Plan 2026-05-12-001 v4 F002 — injection seam for the verdict-vs-finding
# reconciliation gate. Defaults to :func:`classify_finding`; tests inject
# stubs to exercise edge cases without re-deriving the v3 heuristics.
ClassifierCallback = Callable[..., "FindingClassification"]


CLASSIFICATION_SIDECAR_PREFIX = "no_progress_classification"


# ───────────────────── Plan 2026-05-09-002 F001 ─────────────────────
#
# Auditor verdict-mismatch detection. The audit envelope schema (agent-
# conventions v1.0 audit.schema.json) has both a structured ``audit_status``
# enum and an unstructured ``summary`` text field. Auditors sometimes write
# a canonical narrative-verdict line in ``summary`` that disagrees with the
# structured field — most commonly ``**Verdict: signed_off**`` while
# ``audit_status`` defaults to ``needs_changes`` because the JSON serializer
# flipped on a high-severity finding presence. The supervisor reads only
# the structured field, so the disagreement silently produces another paid
# iteration. F001 detects + raises VerdictMismatchError so the volley fails
# loud rather than silently choosing one or the other.
#
# Design (D003 of plan 2026-05-09-002): regexes are line-anchored against
# MULTILINE so canonical lead-in patterns at the START of a line match,
# but quoted text mid-paragraph or recommendation prose does NOT trigger a
# match. Matched token must intern against the canonical audit_status enum
# (defensive — prevents arbitrary words from spoofing the verdict check).

_KNOWN_VERDICTS: frozenset[str] = frozenset(
    {
        "signed_off",
        "needs_changes",
        "blocked",
        "inconclusive",
        "redaction_required",
    }
)

_VERDICT_LINE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE | re.MULTILINE)
    for p in (
        # **Verdict: signed_off** — markdown-bolded canonical form
        r"^\s*\*{2}\s*verdict\s*:\s*([a-z_]+)\s*\*{2}\s*\.?\s*$",
        # Overall verdict: signed_off. — sentence form
        r"^\s*overall\s+verdict\s*:\s*([a-z_]+)\s*\.?\s*$",
        # Verdict: signed_off — plain canonical form
        r"^\s*verdict\s*:\s*([a-z_]+)\s*\.?\s*$",
    )
)


def parse_narrative_verdict(summary: str | None) -> str | None:
    """Plan 2026-05-09-002 F001 — extract the auditor summary's narrative
    verdict line, returning the lowercased status token or ``None``.

    Pure / deterministic. Only canonical lead-in patterns at the start of a
    line match: ``Verdict: X``, ``Overall verdict: X.``, ``**Verdict: X**``.
    Quoted text mid-paragraph or recommendation prose does NOT trigger a
    match. The matched token is checked against the canonical
    ``audit_status`` enum; arbitrary words ("great", "tbd") return None
    rather than being reported as the verdict.

    Returns ``None`` when:
      - ``summary`` is None or empty
      - no canonical pattern matches
      - matched token is not a known ``audit_status`` enum value
    """
    if not summary:
        return None
    for pattern in _VERDICT_LINE_PATTERNS:
        match = pattern.search(summary)
        if match is not None:
            token = match.group(1).strip().lower()
            if token in _KNOWN_VERDICTS:
                return token
    return None


class VerdictMismatchError(Exception):
    """Plan 2026-05-09-002 F001 — auditor envelope's narrative verdict
    line disagrees with the structured ``audit_status`` field.

    Mirrors the :class:`gate_pause.GateStateReconciliationError` shape from
    plan 2026-05-08-003 F001 — typed exception with operator-readable
    remediation. The supervisor catches once at the post-auditor-round
    seam, writes an INBOX classification event, and re-raises so the
    volley fails loud rather than silently choosing one field over the
    other (D003 + D004).
    """

    def __init__(
        self,
        *,
        plan_id: str,
        feature_id: str,
        iteration: int,
        structured_status: str,
        narrative_verdict: str,
        audit_path: Path,
        remediation: str,
    ) -> None:
        self.plan_id = plan_id
        self.feature_id = feature_id
        self.iteration = iteration
        self.structured_status = structured_status
        self.narrative_verdict = narrative_verdict
        self.audit_path = audit_path
        self.remediation = remediation
        msg = (
            f"auditor verdict mismatch [{plan_id}/{feature_id}/iter{iteration}]: "
            f"narrative_verdict={narrative_verdict!r} but "
            f"structured audit_status={structured_status!r}\n"
            f"audit_path={audit_path}\n"
            f"remediation: {remediation}"
        )
        super().__init__(msg)


def detect_verdict_mismatch(
    *,
    plan_id: str,
    feature_id: str,
    iteration: int,
    audit_path: Path,
    audit_envelope: dict[str, Any],
) -> VerdictMismatchError | None:
    """Plan 2026-05-09-002 F001 — pure check returning a fully-populated
    :class:`VerdictMismatchError` when the envelope's narrative verdict
    disagrees with the structured ``audit_status`` field, or ``None`` when
    they agree (or no narrative line is present, in which case the
    existing structured-only behavior applies).

    The caller — typically ``supervisor.dispatch_volley`` — raises the
    returned error after writing an INBOX classification event. Returning
    the populated error rather than raising directly keeps this function
    pure and testable.
    """
    structured = audit_envelope.get("audit_status")
    if not isinstance(structured, str):
        # Missing / malformed structured field is a separate concern;
        # callers handle it elsewhere (default to "inconclusive").
        return None
    summary = audit_envelope.get("summary")
    narrative = parse_narrative_verdict(
        summary if isinstance(summary, str) else None
    )
    if narrative is None:
        # Narrative-absent: structured field is canonical. Existing
        # behavior is preserved.
        return None
    if narrative == structured.lower():
        return None
    remediation = (
        "Reconcile the auditor's verdict before re-dispatching: either "
        "update the summary to match audit_status, or update audit_status "
        "to match the canonical narrative verdict. Re-running without "
        "reconciliation will hit this error again."
    )
    return VerdictMismatchError(
        plan_id=plan_id,
        feature_id=feature_id,
        iteration=iteration,
        structured_status=structured,
        narrative_verdict=narrative,
        audit_path=audit_path,
        remediation=remediation,
    )


def format_verdict_mismatch_inbox_body(err: VerdictMismatchError) -> str:
    """Plan 2026-05-09-002 F001 — operator-readable INBOX body for a
    verdict-mismatch failure. Kept module-local so every call site emits
    the same shape (parallel to :func:`format_reconciliation_inbox_body`
    in gate_pause for the GateStateReconciliationError case)."""
    return (
        f"Auditor verdict mismatch on iteration {err.iteration}.\n\n"
        f"Plan: {err.plan_id}\n"
        f"Feature: {err.feature_id}\n"
        f"Audit envelope: {err.audit_path}\n\n"
        f"Narrative verdict line: {err.narrative_verdict!r}\n"
        f"Structured audit_status: {err.structured_status!r}\n\n"
        f"Remediation: {err.remediation}\n\n"
        "The auditor wrote a canonical verdict line in the summary that "
        "disagrees with the structured field. The supervisor refuses to "
        "silently choose one or the other — silent disagreement is the "
        "exact regression the SpinDine vibe-plan-001 F001-i1 dispatch "
        "produced before this check landed."
    )


# ─────────────────────────────────────────────────────────────────


class FindingClass(str, Enum):
    IMPLEMENTATION_DEFECT = "implementation_defect"
    ENVIRONMENTAL_REPRODUCTION_FAILURE = "environmental_reproduction_failure"
    EVIDENCE_SHAPE_DISAGREEMENT = "evidence_shape_disagreement"
    SCOPE_OVERREACH = "scope_overreach"
    SPEC_AMBIGUITY = "spec_ambiguity"
    UNKNOWN = "unknown"


# Classes that NEVER unblock the operator. ``mixed`` (multi-class set
# containing a blocking class) and ``unknown`` collapse onto these.
_BLOCKING_CLASSES: frozenset[FindingClass] = frozenset(
    {FindingClass.IMPLEMENTATION_DEFECT, FindingClass.UNKNOWN}
)

# Plan 2026-05-12-001 v4 F002 — advisory-only finding classes used by the
# verdict-vs-finding reconciliation. When the auditor returns
# ``audit_status=blocked`` but every finding classifies into this set, the
# supervisor promotes the terminal from ``blocked-after-N`` to
# ``stopped_environmental_blocker`` (matching the F003 ENVIRONMENTAL_BLOCKER
# semantics) rather than trusting the verdict string. Empty findings is
# NOT vacuously advisory — see ``is_advisory_only_findings_set``.
_ADVISORY_CLASSES: frozenset[FindingClass] = frozenset(
    {
        FindingClass.ENVIRONMENTAL_REPRODUCTION_FAILURE,
        FindingClass.EVIDENCE_SHAPE_DISAGREEMENT,
        FindingClass.SPEC_AMBIGUITY,
        FindingClass.SCOPE_OVERREACH,
    }
)

# Substantive categories that default to ``implementation_defect`` when no
# other heuristic fires. ``test_coverage`` is intentionally NOT in this
# set — many test_coverage findings collapse to environmental
# (auditor sandbox can't run the test runner) and require pattern matching
# on the issue text before we promote them to a defect.
_DEFECT_CATEGORIES: frozenset[str] = frozenset(
    {"correctness", "security", "performance", "architecture", "redaction"}
)

# Severities the operator should still inspect even when the classifier
# can't pin the finding to a named class. Used to push critical/high
# findings into ``implementation_defect`` rather than ``unknown`` when no
# pattern matches — better to over-block on severity than under-block.
_SUBSTANTIVE_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})

# Plan 2026-05-11-002 v3 F003 — spec_ambiguity gate. A finding flips to
# spec_ambiguity when severity is low/medium AND category names a surface
# where the spec/convention itself is the disputed thing — documentation
# placement, naming, convention adherence, file placement. Anything
# critical/high stays in the substantive-severity heuristic so we never
# silently advisory-downgrade a real defect on category alone.
_SPEC_AMBIGUITY_SEVERITIES: frozenset[str] = frozenset({"low", "medium"})
_SPEC_AMBIGUITY_CATEGORIES: frozenset[str] = frozenset(
    {"documentation", "naming", "convention", "placement"}
)


# ───────────────────────── pattern catalogues ─────────────────────────
# Ordered most-specific → least-specific. Each entry is a compiled
# case-insensitive regex used on the concatenated ``issue`` + ``evidence``
# text. Matching ANY of a class's patterns marks the finding as that class
# UNLESS a more-specific class already matched.

_ENV_REPRO_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsandbox\b.*\b(cannot|can't|unable|not allowed|forbidden|denied)\b",
        # Plan 2026-05-12-002 v4.1 F002 D007 #2: allow 0-2 adverbs between the
        # auxiliary and the verb (e.g. "could not independently rerun"), and
        # accept "re"-prefixed + "reproduce"/"verify" variants so real auditor
        # prose maps to env_repro instead of falling through to UNKNOWN.
        r"\b(cannot|can't|unable|could not|couldn't)(?:\s+\w+){0,2}\s+"
        r"(run|rerun|re-run|execute|invoke|launch|reproduce|verify)\b",
        r"\b(permission|access)\s+denied\b",
        r"\bnetwork\s+(unavailable|disabled|offline|forbidden)\b",
        r"\bno\s+(internet|network|connectivity)\b",
        # Python tempfile-module failure marker — fires when the auditor
        # sandbox refused a writable temp directory (pytest, importlib, and
        # most stdlib setup-paths fail before they start). Real prose
        # observed: "Python reports no usable temporary directory" /
        # "FileNotFoundError: No usable temporary directory found".
        r"\bno\s+usable\s+temp(?:orary)?\s+(?:dir|directory)\b",
        r"\b(xcode|jest|gradle|cargo|swift\s+test|npm\s+test|pytest|gcloud|firebase)\b.*"
        r"\b(unavailable|missing|not\s+(found|installed)|denied|cannot\s+run|"
        r"unable\s+to\s+run|could\s+not\s+run)\b",
        r"\b(cli|gcloud|firebase|aws|gh)\s+auth(?:enticat\w+)?\b.*"
        r"\b(required|missing|expired|not\s+(set|configured|authenticated))\b",
        r"\b(simulator|device|emulator)\b.*\b(unavailable|not\s+(found|booted))\b",
        r"\bbinary\s+(not\s+found|missing)\b",
        r"\btool\s+unavailable\b",
        r"\bharness\s+(blocker|limitation|cannot)\b",
    )
)

_EVIDENCE_SHAPE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(expected|wanted|need(s|ed)?|require(s|d)?)\s+(?:a\s+)?"
        r"(screenshot|log\s+file|trace|video|recording|gif)\b",
        r"\b(expected|wanted|require(s|d)?)\s+json\s+(output|format|envelope)\b",
        r"\b(different|wrong)\s+(format|representation|shape)\s+"
        r"(than|from)\s+(expected|requested)\b",
        r"\b(operator|human)\s+screenshot\b",
        r"\bevidence\s+(format|shape)\s+(mismatch|disagreement|differs)\b",
    )
)

# Equivalent-saved-evidence markers. A finding only flips to
# ``evidence_shape_disagreement`` when the audit trail (final envelope's
# validation_performed, target_context, or referenced finding evidence
# fields) shows that equivalent evidence already landed somewhere the
# operator can inspect. Heuristic: presence of a path matching one of
# these patterns inside the validation log or any prior implementer
# envelope's `summary` or `validation_performed`.
_SAVED_EVIDENCE_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'(`])(?:\./|/)?(?:evidence|audit|docs/plans/[^/\s]+/(?:evidence|audit))/"
    r"[\w./\-]+\.(?:log|json|txt|md|png|jpg|jpeg|gif|html|csv|svg)\b",
    re.IGNORECASE,
)

_SCOPE_OVERREACH_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bunrelated\s+to\s+(this|the)\s+(feature|task|plan|change)\b",
        r"\bout\s+of\s+scope\b",
        r"\boutside\s+(the\s+)?scope\b",
        r"\bdifferent\s+(concern|feature|plan|surface)\b",
        r"\bnot\s+part\s+of\s+(this|the)\s+(feature|change|plan)\b",
    )
)


# ───────────────────────── data types ─────────────────────────


@dataclass(frozen=True)
class FindingClassification:
    """Per-finding classification result. ``finding_index`` is the position
    in the auditor's ``findings`` array so operator drill-down lines up
    with the original envelope."""

    finding_index: int
    classification: FindingClass
    severity: str
    category: str
    issue_excerpt: str
    rationale: str


@dataclass(frozen=True)
class TerminalClassification:
    """Aggregate classification for a single ``stopped_no_progress``
    terminal. ``aggregate`` is the worst-blocking class across all
    findings; ``blocking`` is True when the operator MUST inspect (any
    implementation_defect or unknown finding, or zero findings — defensive
    default)."""

    feature_id: str
    aggregate: FindingClass
    blocking: bool
    findings: tuple[FindingClassification, ...]
    recommended_action: str
    saved_evidence_paths: tuple[str, ...] = field(default_factory=tuple)


# ───────────────────────── public API ─────────────────────────


def classify_finding(
    finding: dict[str, Any],
    *,
    finding_index: int = 0,
    feature_id: str | None = None,
    saved_evidence_paths: tuple[str, ...] = (),
) -> FindingClassification:
    """Classify a single auditor finding. Pure — ``finding`` must be the
    raw dict from the auditor envelope.

    ``feature_id`` (when provided) is the dispatched feature ID; a
    finding whose own ``feature_id`` differs is candidate
    ``scope_overreach``. ``saved_evidence_paths`` is the set of paths the
    audit trail already references (used to gate
    ``evidence_shape_disagreement``)."""
    severity = str(finding.get("severity") or "unknown").lower()
    category = str(finding.get("category") or "unknown").lower()
    issue = str(finding.get("issue") or "").strip()
    evidence = str(finding.get("evidence") or "").strip()
    finding_feature_id = finding.get("feature_id")
    finding_file = finding.get("file")
    text = f"{issue}\n{evidence}".strip()

    # Order matters: scope_overreach beats env/shape because a scope-mismatched
    # finding is operator-routable regardless of its content. Then env-repro
    # (concrete tool/auth blocker), then evidence-shape (requires saved
    # evidence to flip), then defect default for substantive categories,
    # else unknown.

    if (
        feature_id
        and isinstance(finding_feature_id, str)
        and finding_feature_id != feature_id
    ):
        return FindingClassification(
            finding_index=finding_index,
            classification=FindingClass.SCOPE_OVERREACH,
            severity=severity,
            category=category,
            issue_excerpt=_excerpt(issue),
            rationale=(
                f"finding.feature_id={finding_feature_id!r} differs from "
                f"dispatched feature_id={feature_id!r}; routes as a "
                "follow-up against the cited feature, not against this "
                "volley's scope."
            ),
        )

    if any(p.search(text) for p in _SCOPE_OVERREACH_PATTERNS):
        return FindingClassification(
            finding_index=finding_index,
            classification=FindingClass.SCOPE_OVERREACH,
            severity=severity,
            category=category,
            issue_excerpt=_excerpt(issue),
            rationale=(
                "issue/evidence text declares the finding outside this "
                "feature's scope; route as a follow-up plan."
            ),
        )

    if any(p.search(text) for p in _ENV_REPRO_PATTERNS):
        cited_file = (
            f" (referenced file: {finding_file})"
            if isinstance(finding_file, str) and finding_file
            else ""
        )
        return FindingClassification(
            finding_index=finding_index,
            classification=FindingClass.ENVIRONMENTAL_REPRODUCTION_FAILURE,
            severity=severity,
            category=category,
            issue_excerpt=_excerpt(issue),
            rationale=(
                "auditor reports a sandbox/host/auth blocker preventing "
                f"reproduction{cited_file}; operator can run the "
                "verification locally."
            ),
        )

    if any(p.search(text) for p in _EVIDENCE_SHAPE_PATTERNS):
        if saved_evidence_paths:
            return FindingClassification(
                finding_index=finding_index,
                classification=FindingClass.EVIDENCE_SHAPE_DISAGREEMENT,
                severity=severity,
                category=category,
                issue_excerpt=_excerpt(issue),
                rationale=(
                    "auditor disagrees with evidence representation; "
                    "audit trail already references equivalent saved "
                    f"evidence at {list(saved_evidence_paths)[:3]}"
                    + ("…" if len(saved_evidence_paths) > 3 else "")
                    + ". Operator may surface the existing artifact."
                ),
            )
        # Shape-disagreement without saved evidence remains blocking — we
        # don't know whether equivalent evidence exists, so falling back
        # to the substantive-severity heuristic (or spec_ambiguity for
        # low/medium documentation findings) preserves blocking behavior
        # only where severity warrants it.

    if (
        severity in _SPEC_AMBIGUITY_SEVERITIES
        and category in _SPEC_AMBIGUITY_CATEGORIES
    ):
        return FindingClassification(
            finding_index=finding_index,
            classification=FindingClass.SPEC_AMBIGUITY,
            severity=severity,
            category=category,
            issue_excerpt=_excerpt(issue),
            rationale=(
                f"severity={severity}, category={category} — finding sits "
                "on a documentation/naming/convention/placement surface "
                "where the spec is the disputed thing, not the code. "
                "Patch the spec then resume, or accept the implementer's "
                "reading."
            ),
        )

    if severity in _SUBSTANTIVE_SEVERITIES or category in _DEFECT_CATEGORIES:
        return FindingClassification(
            finding_index=finding_index,
            classification=FindingClass.IMPLEMENTATION_DEFECT,
            severity=severity,
            category=category,
            issue_excerpt=_excerpt(issue),
            rationale=(
                f"severity={severity}, category={category} — substantive "
                "finding with no environmental/shape/scope marker; "
                "treat as a real implementation defect."
            ),
        )

    return FindingClassification(
        finding_index=finding_index,
        classification=FindingClass.UNKNOWN,
        severity=severity,
        category=category,
        issue_excerpt=_excerpt(issue),
        rationale=(
            "no taxonomy pattern matched and severity/category are not "
            "substantive; remains blocking pending operator review."
        ),
    )


def is_advisory_only_findings_set(
    findings: list[dict[str, Any]] | None,
    *,
    feature_id: str | None = None,
    saved_evidence_paths: tuple[str, ...] = (),
    taxonomy_classifier: "ClassifierCallback | None" = None,
) -> bool:
    """Plan 2026-05-12-001 v4 F002 — verdict-vs-finding reconciliation gate.

    Returns True iff ``findings`` is NON-EMPTY AND every finding classifies
    to one of the advisory v3 classes (``environmental_reproduction_failure``
    / ``evidence_shape_disagreement`` / ``spec_ambiguity`` /
    ``scope_overreach``). Empty findings is NOT vacuously advisory — when
    the auditor returns ``audit_status=blocked`` with no findings we have
    no evidence that the blocker is environmental and the supervisor must
    surface the missing-findings case via the separate ``blocked_no_findings``
    terminal rather than auto-promoting.

    ``taxonomy_classifier`` is an injection seam (per F002 spec). It must
    accept ``(finding, *, finding_index, feature_id, saved_evidence_paths)``
    and return a :class:`FindingClassification`. Defaults to
    :func:`classify_finding`. Tests inject a stub to exercise corner cases
    without re-deriving the v3 taxonomy heuristics.

    Used by ``supervisor.dispatch_volley`` to override a verdict=blocked
    terminal to ``stopped_environmental_blocker`` (matching F003
    ENVIRONMENTAL_BLOCKER semantics) when every finding is advisory-only.
    Mixed sets containing any substantive class (``implementation_defect``,
    ``unknown``) keep the original ``blocked`` terminal — substantive
    findings + verdict=blocked = real blocker.
    """
    if not findings:
        return False
    classifier = taxonomy_classifier or classify_finding
    for idx, finding in enumerate(findings):
        if not isinstance(finding, dict):
            return False
        c = classifier(
            finding,
            finding_index=idx,
            feature_id=feature_id,
            saved_evidence_paths=saved_evidence_paths,
        )
        if c.classification not in _ADVISORY_CLASSES:
            return False
    return True


def collect_saved_evidence_paths(envelopes: list[dict[str, Any]]) -> tuple[str, ...]:
    """Pure — scan envelope summaries / validation_performed entries /
    finding evidence text for paths matching the saved-evidence pattern.
    Order-preserving + de-duplicated. Used to gate the
    ``evidence_shape_disagreement`` classification."""
    seen: dict[str, None] = {}
    for env in envelopes:
        if not isinstance(env, dict):
            continue
        haystacks: list[str] = []
        summary = env.get("summary")
        if isinstance(summary, str):
            haystacks.append(summary)
        validations = env.get("validation_performed")
        if isinstance(validations, list):
            haystacks.extend(str(v) for v in validations if isinstance(v, str))
        findings = env.get("findings")
        if isinstance(findings, list):
            for f in findings:
                if isinstance(f, dict):
                    ev = f.get("evidence")
                    if isinstance(ev, str):
                        haystacks.append(ev)
        for h in haystacks:
            for m in _SAVED_EVIDENCE_PATH_PATTERN.finditer(h):
                token = m.group(0).strip().strip("\"'`(")
                seen.setdefault(token, None)
    return tuple(seen.keys())


def classify_terminal(
    *,
    feature_id: str,
    final_audit_envelope: dict[str, Any],
    prior_envelopes: list[dict[str, Any]] | None = None,
) -> TerminalClassification:
    """Aggregate classifier for a ``stopped_no_progress`` terminal.

    Reads the final auditor envelope's findings, classifies each, and
    derives the worst-class aggregate. ``prior_envelopes`` (implementer +
    earlier auditor envelopes from the same volley) feed
    ``collect_saved_evidence_paths`` so the shape-disagreement gate has
    visibility into evidence the implementer landed in earlier rounds.
    """
    findings = final_audit_envelope.get("findings")
    if not isinstance(findings, list):
        findings = []

    saved_paths = collect_saved_evidence_paths(
        [final_audit_envelope, *(prior_envelopes or [])]
    )

    classifications: list[FindingClassification] = []
    for idx, finding in enumerate(findings):
        if not isinstance(finding, dict):
            classifications.append(
                FindingClassification(
                    finding_index=idx,
                    classification=FindingClass.UNKNOWN,
                    severity="unknown",
                    category="unknown",
                    issue_excerpt="",
                    rationale="finding entry was not a dict; treated as unknown.",
                )
            )
            continue
        classifications.append(
            classify_finding(
                finding,
                finding_index=idx,
                feature_id=feature_id,
                saved_evidence_paths=saved_paths,
            )
        )

    aggregate, blocking = _aggregate(classifications)
    return TerminalClassification(
        feature_id=feature_id,
        aggregate=aggregate,
        blocking=blocking,
        findings=tuple(classifications),
        recommended_action=_recommend(aggregate, blocking, classifications),
        saved_evidence_paths=saved_paths,
    )


def write_classification_sidecar(
    *,
    plan_dir: Path,
    feature_id: str,
    iteration: int,
    classification: TerminalClassification,
) -> Path:
    """Persist the per-finding classification next to audit envelopes so
    the operator (and the F2 close gate) has a stable artifact to cite.

    Returned path: ``<plan_dir>/audit/no_progress_classification_{feature_id}_iter{N}.json``.
    """
    audit_dir = plan_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{CLASSIFICATION_SIDECAR_PREFIX}_{feature_id}_iter{iteration}.json"
    payload = {
        "schema_version": "1.0",
        "kind": CLASSIFICATION_SIDECAR_PREFIX,
        "captured_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feature_id": classification.feature_id,
        "aggregate": classification.aggregate.value,
        "blocking": classification.blocking,
        "recommended_action": classification.recommended_action,
        "saved_evidence_paths": list(classification.saved_evidence_paths),
        "findings": [
            {
                "finding_index": f.finding_index,
                "classification": f.classification.value,
                "severity": f.severity,
                "category": f.category,
                "issue_excerpt": f.issue_excerpt,
                "rationale": f.rationale,
            }
            for f in classification.findings
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return path


def format_inbox_body(classification: TerminalClassification) -> str:
    """Operator-readable INBOX body — names the aggregate class, the
    blocking flag, the recommended action, and a per-finding mini-table
    so the operator sees which findings drove the aggregate."""
    block_label = "BLOCKING" if classification.blocking else "ADVISORY"
    lines = [
        f"Auditor verdict taxonomy [{classification.aggregate.value}] — {block_label}.",
        "",
        f"Feature: {classification.feature_id}",
        f"Recommended next action: {classification.recommended_action}",
        "",
    ]
    if classification.findings:
        lines.append("Per-finding classification:")
        for f in classification.findings:
            lines.append(
                f"  - [{f.classification.value}] severity={f.severity}, "
                f"category={f.category}: {f.issue_excerpt}"
            )
        lines.append("")
    if classification.saved_evidence_paths:
        lines.append(
            "Audit trail referenced existing evidence at: "
            + ", ".join(classification.saved_evidence_paths[:5])
            + ("…" if len(classification.saved_evidence_paths) > 5 else "")
        )
    if classification.blocking:
        lines.append(
            "Aggregate class blocks auto-advance. Operator must review the "
            "underlying audit envelope before declaring the volley resolved."
        )
    else:
        lines.append(
            "Aggregate class is advisory: every finding mapped to a non-"
            "defect harness/scope class. F003 does NOT auto-sign-off; the "
            "operator still owns the close decision."
        )
    return "\n".join(lines)


# ───────────────────────── internals ─────────────────────────


def _excerpt(issue: str, *, limit: int = 160) -> str:
    issue = issue.replace("\n", " ").strip()
    if len(issue) <= limit:
        return issue
    return issue[: limit - 1].rstrip() + "…"


def _aggregate(
    classifications: list[FindingClassification],
) -> tuple[FindingClass, bool]:
    """Reduce per-finding classes to a single terminal class + blocking
    flag. Empty findings collapse to ``unknown`` blocking — a no-progress
    terminal with no findings is opaque and operator must inspect."""
    if not classifications:
        return FindingClass.UNKNOWN, True

    classes = {c.classification for c in classifications}
    blocking = bool(classes & _BLOCKING_CLASSES)

    # Worst-class wins. UNKNOWN ranks above defect because unknown means
    # "we couldn't even classify — operator must inspect"; defect is also
    # blocking but at least operator-actionable. Then advisory classes,
    # in declared specificity order.
    for cls in (
        FindingClass.UNKNOWN,
        FindingClass.IMPLEMENTATION_DEFECT,
        FindingClass.SCOPE_OVERREACH,
        FindingClass.ENVIRONMENTAL_REPRODUCTION_FAILURE,
        FindingClass.EVIDENCE_SHAPE_DISAGREEMENT,
        FindingClass.SPEC_AMBIGUITY,
    ):
        if cls in classes:
            return cls, blocking
    # Defensive — every FindingClass member is in the loop above.
    return FindingClass.UNKNOWN, True


def _recommend(
    aggregate: FindingClass,
    blocking: bool,
    classifications: list[FindingClassification],
) -> str:
    if aggregate == FindingClass.IMPLEMENTATION_DEFECT:
        return (
            "Inspect the auditor's findings against the implementer's "
            "diff and decide between (a) sending another implementer "
            "round with revised guidance, or (b) closing the volley as "
            "blocked pending design changes."
        )
    if aggregate == FindingClass.UNKNOWN:
        return (
            "Auditor produced findings the taxonomy could not place. "
            "Inspect the audit envelope manually before deciding "
            "whether to retry, escalate, or close as blocked."
        )
    if aggregate == FindingClass.ENVIRONMENTAL_REPRODUCTION_FAILURE:
        return (
            "Re-run the cited verification locally on a host that has the "
            "missing tool/auth/sandbox capability. If the verification "
            "passes locally, attach the evidence and close the volley as "
            "operator-verified; if it fails, that becomes a real defect."
        )
    if aggregate == FindingClass.EVIDENCE_SHAPE_DISAGREEMENT:
        return (
            "Surface the saved evidence already referenced in the audit "
            "trail to the auditor (or to the operator review) — the "
            "implementer landed equivalent artifacts in a shape the "
            "auditor did not request."
        )
    if aggregate == FindingClass.SCOPE_OVERREACH:
        return (
            "Queue the cited concerns as a separate plan / feature; they "
            "lie outside this volley's scope and should not block "
            "close-out."
        )
    if aggregate == FindingClass.SPEC_AMBIGUITY:
        return (
            "Operator-review for spec gap; patch spec then resume or "
            "accept implementer's reading. The finding sits on a "
            "documentation/naming/convention/placement surface where "
            "implementer + auditor both fit the spec but the spec is "
            "silent on the disputed point. Two paths: (a) update the "
            "spec/feature description to disambiguate and re-dispatch, "
            "or (b) accept the implementer's interpretation and close "
            "the volley operator-resolved."
        )
    return "Operator review required."


__all__ = [
    "CLASSIFICATION_SIDECAR_PREFIX",
    "ClassifierCallback",
    "FindingClass",
    "FindingClassification",
    "TerminalClassification",
    "VerdictMismatchError",
    "classify_finding",
    "classify_terminal",
    "collect_saved_evidence_paths",
    "detect_verdict_mismatch",
    "format_inbox_body",
    "format_verdict_mismatch_inbox_body",
    "is_advisory_only_findings_set",
    "parse_narrative_verdict",
    "write_classification_sidecar",
]
