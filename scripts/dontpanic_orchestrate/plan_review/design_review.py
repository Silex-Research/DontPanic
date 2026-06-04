"""Design-review volley (F005).

Layer-2 of the plan-review capability. Where the F001 deterministic lint is a
free, mechanical check, this is the *paid* red-team pass reserved for the plans
the lint cannot fully judge: it runs a **design-reviewer** auditor against a
**planner** implementer through the existing volley machinery (the executor
abstraction + the standard ``{verdict, findings}`` auditor envelope), red-teaming
a plan's feature decomposition for sizing, hidden coupling, testability traps,
dependency order, and missing prerequisites.

Closed design taxonomy (acceptance #2) — every finding is keyed to exactly one:

  * ``oversize``          — a feature too large for one dispatch (multi-surface / too many ACs)
  * ``hidden_coupling``   — an undeclared dependency between features
  * ``ac_underspecified`` — an exemplar/weak acceptance criterion (example, not invariant)
  * ``missing_prereq``    — a capability the plan never declares
  * ``reorder_deps``      — a dependency order that should be re-sequenced

Opt-in only (acceptance #3): :func:`should_run_design_volley` returns True only
when the F001 lint reports *uncertainty* (warn-severity flags — not clean, not a
clear block) OR the operator explicitly requests it. It is NEVER auto-run on
every plan; a clean plan skips it and a clearly-blocked plan is already refused
by the F004 pre-lock gate.

The volley loop here mirrors ``supervisor.dispatch_volley``'s structure — an
auditor slot reviewing, an optional implementer (planner) slot revising on
``needs_changes`` — but is decomposition-shaped rather than code-shaped, so it
neither touches a git diff nor runs patch-completeness. It reuses the
``BaseExecutor`` dispatch contract, which is what lets the synthetic test
(acceptance #4) drive it with a mock executor and zero live paid calls.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from dontpanic_orchestrate.executors.base import (
    BaseExecutor,
    DispatchTask,
)
from dontpanic_orchestrate.plan_review.report import PlanScopeReport

# The closed design-review taxonomy (acceptance #2). A finding whose ``kind`` is
# outside this set is not a valid design finding and is quarantined out of the
# standard envelope.
DESIGN_TAXONOMY: frozenset[str] = frozenset(
    {"oversize", "hidden_coupling", "ac_underspecified", "missing_prereq", "reorder_deps"}
)

DesignFindingKind = Literal[
    "oversize", "hidden_coupling", "ac_underspecified", "missing_prereq", "reorder_deps"
]
Verdict = Literal["signed_off", "needs_changes", "blocked"]

DESIGN_REVIEWER_ROLE = "design-reviewer"
PLANNER_ROLE = "planner"


# ─────────────────────────────── public types ──────────────────────────────


@dataclass(frozen=True)
class DesignFinding:
    kind: DesignFindingKind
    severity: str
    feature_id: str
    evidence: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "feature_id": self.feature_id,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, blob: dict) -> DesignFinding:
        return cls(
            kind=blob["kind"],
            severity=str(blob.get("severity", "warn")),
            feature_id=str(blob.get("feature_id", "")),
            evidence=str(blob.get("evidence", "")),
        )


@dataclass
class DesignVolleyEnvelope:
    """The standard auditor envelope a design volley returns (acceptance #1).

    ``unrecognized`` holds any emitted finding whose ``kind`` fell outside the
    closed taxonomy — quarantined so ``findings`` is taxonomy-pure (acceptance
    #2) without silently discarding what the reviewer said."""

    verdict: Verdict
    findings: list[DesignFinding] = field(default_factory=list)
    rounds: int = 1
    unrecognized: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "findings": [f.to_dict() for f in self.findings],
            "rounds": self.rounds,
            "unrecognized": list(self.unrecognized),
        }

    def findings_of_kind(self, kind: str) -> list[DesignFinding]:
        return [f for f in self.findings if f.kind == kind]


# ─────────────────────────────── trigger ───────────────────────────────────


def _has_warn_flag(report: PlanScopeReport) -> bool:
    for fr in report.features:
        if any(flag.severity == "warn" for flag in fr.scope.flags):
            return True
    return False


def should_run_design_volley(
    report: PlanScopeReport, *, operator_requested: bool = False
) -> bool:
    """Opt-in trigger (acceptance #3). True iff the operator explicitly asked OR
    the F001 lint is *uncertain* — it surfaced warn-severity flags (the
    ambiguous middle the deterministic lint cannot resolve). A fully clean plan
    (no flags) never auto-triggers a paid volley."""
    if operator_requested:
        return True
    return _has_warn_flag(report)


# ─────────────────────────────── prompts ───────────────────────────────────


def build_design_reviewer_prompt(
    plan_id: str,
    features: Sequence[dict],
    objective_contract: dict | None = None,
) -> str:
    """The design-reviewer auditor prompt: consumes the plan's features +
    objective_contract and instructs the reviewer to emit a strict JSON envelope
    keyed to the closed design taxonomy."""
    contract_block = (
        json.dumps(objective_contract, indent=2)
        if objective_contract
        else "(no objective_contract provided)"
    )
    feature_block = json.dumps(list(features), indent=2)
    taxonomy = ", ".join(sorted(DESIGN_TAXONOMY))
    return f"""You are the DESIGN REVIEWER for plan {plan_id}.

Red-team this plan's FEATURE DECOMPOSITION (not its code) for:
  - oversize: a feature too large for one ~600s dispatch (spans >1 surface, or too many ACs)
  - hidden_coupling: a feature depending on another's output without declaring depends_on
  - ac_underspecified: an acceptance criterion that gives an example instead of an invariant
  - missing_prereq: a capability (command/flag/symbol) the plan relies on but never declares
  - reorder_deps: a dependency order that should be re-sequenced

objective_contract:
{contract_block}

features.json:
{feature_block}

Return ONLY a JSON object:
  {{"verdict": "signed_off" | "needs_changes" | "blocked",
    "findings": [{{"kind": <one of: {taxonomy}>, "severity": "block"|"warn",
                   "feature_id": "<id>", "evidence": "<one line>"}}]}}
Sign off only when the decomposition has no design defect. Every finding's
"kind" MUST be one of the closed taxonomy values above."""


def build_planner_prompt(
    plan_id: str,
    features: Sequence[dict],
    prior_findings: Sequence[DesignFinding],
) -> str:
    """The planner implementer prompt for a revision round: addresses the
    design-reviewer's prior findings by re-decomposing the plan."""
    findings_block = "\n".join(
        f"  - [{f.kind}/{f.severity}] {f.feature_id}: {f.evidence}"
        for f in prior_findings
    ) or "  (none)"
    feature_block = json.dumps(list(features), indent=2)
    return f"""You are the PLANNER for plan {plan_id}.

The design reviewer raised these decomposition findings:
{findings_block}

Current features.json:
{feature_block}

Revise the decomposition to resolve every finding (split oversize features,
declare missing depends_on, sharpen exemplar ACs into invariants, declare
prerequisites, reorder dependencies). Return the revised features as JSON."""


# ─────────────────────────────── parsing ───────────────────────────────────


def parse_design_envelope(raw: str, *, rounds: int = 1) -> DesignVolleyEnvelope:
    """Parse a design-reviewer's raw response into the standard envelope.

    Findings whose ``kind`` is outside the closed taxonomy are quarantined into
    ``unrecognized`` so the returned ``findings`` list is taxonomy-pure. A
    response that is not valid JSON or lacks a verdict is treated as
    ``blocked`` (the reviewer failed to produce a usable envelope)."""
    try:
        blob = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return DesignVolleyEnvelope(verdict="blocked", rounds=rounds)
    if not isinstance(blob, dict) or "verdict" not in blob:
        return DesignVolleyEnvelope(verdict="blocked", rounds=rounds)

    verdict = blob.get("verdict")
    if verdict not in ("signed_off", "needs_changes", "blocked"):
        verdict = "blocked"

    findings: list[DesignFinding] = []
    unrecognized: list[dict] = []
    for raw_finding in blob.get("findings") or []:
        if not isinstance(raw_finding, dict):
            continue
        if raw_finding.get("kind") in DESIGN_TAXONOMY:
            findings.append(DesignFinding.from_dict(raw_finding))
        else:
            unrecognized.append(dict(raw_finding))
    return DesignVolleyEnvelope(
        verdict=verdict, findings=findings, rounds=rounds, unrecognized=unrecognized
    )


# ─────────────────────────────── the volley ────────────────────────────────


def _dispatch_review(
    auditor: BaseExecutor,
    *,
    plan_id: str,
    plan_dir,
    features: Sequence[dict],
    objective_contract: dict | None,
    iteration: int,
) -> str:
    prompt = build_design_reviewer_prompt(plan_id, features, objective_contract)
    task = DispatchTask(
        plan_id=plan_id,
        plan_dir=plan_dir,
        feature_id="(plan-decomposition)",
        feature_description="Design review of the whole plan decomposition.",
        feature_acceptance="No design defect in the decomposition.",
        feature_steps=[],
        agent_role=DESIGN_REVIEWER_ROLE,
        iteration=iteration,
        extra_context={"prompt_override": prompt},
    )
    result = auditor.dispatch(task)
    if not result.success:
        return ""  # parse_design_envelope → blocked
    return result.raw_response or result.summary or ""


def run_design_volley(
    plan_id: str,
    features: Sequence[dict],
    *,
    auditor: BaseExecutor,
    planner: BaseExecutor | None = None,
    objective_contract: dict | None = None,
    plan_dir=None,
    max_iterations: int = 2,
) -> DesignVolleyEnvelope:
    """Run the design-reviewer auditor (optionally against a planner implementer
    that revises on ``needs_changes``) and return the standard envelope.

    Mirrors ``dispatch_volley``'s loop shape: round 0 the auditor reviews; on
    ``needs_changes`` with a ``planner`` supplied it revises and the auditor
    re-reviews, up to ``max_iterations`` rounds. Terminates immediately on
    ``signed_off`` / ``blocked`` or when no planner can make progress. Pure
    w.r.t. the filesystem beyond what the injected executors do — which is
    nothing in the synthetic test (acceptance #4)."""
    current_features = list(features)
    last: DesignVolleyEnvelope | None = None
    for iteration in range(max(1, max_iterations)):
        raw = _dispatch_review(
            auditor,
            plan_id=plan_id,
            plan_dir=plan_dir,
            features=current_features,
            objective_contract=objective_contract,
            iteration=iteration,
        )
        last = parse_design_envelope(raw, rounds=iteration + 1)
        if last.verdict != "needs_changes" or planner is None:
            return last
        # Planner revises to resolve the findings, then we re-review.
        plan_prompt = build_planner_prompt(plan_id, current_features, last.findings)
        task = DispatchTask(
            plan_id=plan_id,
            plan_dir=plan_dir,
            feature_id="(plan-decomposition)",
            feature_description="Revise the plan decomposition per design findings.",
            feature_acceptance="Every design finding resolved.",
            feature_steps=[],
            agent_role=PLANNER_ROLE,
            iteration=iteration,
            extra_context={"prompt_override": plan_prompt},
        )
        revised = planner.dispatch(task)
        if revised.success and revised.raw_response:
            try:
                parsed = json.loads(revised.raw_response)
                if isinstance(parsed, list):
                    current_features = parsed
                elif isinstance(parsed, dict) and isinstance(parsed.get("features"), list):
                    current_features = parsed["features"]
            except json.JSONDecodeError:
                pass  # keep prior features; auditor will re-review unchanged
    return last if last is not None else DesignVolleyEnvelope(verdict="blocked")
