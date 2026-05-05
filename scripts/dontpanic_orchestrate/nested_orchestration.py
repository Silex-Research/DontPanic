"""Plan 2026-05-02-003 F001 + F002 + F003 — nested-orchestration primitives.

F001: parent/child metadata + depth/cycle/repeated-finding guards.
F002: child_charter + commit_policy parsing/validation + close-out
compliance (allowed-paths + return-condition + requires).
F003: parent pause/fan-in protocol — pre_resume_after_child gate +
fan-in memo enforcement + best-effort events.jsonl trace.

Loads optional `orchestration`, `child_charter`, and `commit_policy`
blocks from plan.md frontmatter into structured Pydantic models, computes
parent-chain depth, and refuses dispatch when (a) depth exceeds the
platform cap (default 3, CLI-only override per D002), (b) the chain
forms a cycle by `plan_id`, or (c) the current plan's spawn-finding
signature collides with any parent's recorded signature (D001).

At signoff time (F002), enforces the child charter: parses the structured
`## Return Condition` section of evidence/closeout-memo.md (D004), checks
modified-file paths against `allowed_paths` when commit_policy.mode is
`child_commit`, and verifies each `commit_policy.requires` item is
satisfied by the signoff envelope.

Anti-recursion thesis: a child plan is bounded work tied to a named
parent finding/objective. depth + cycle + signature guards together
make unbounded chains "fixing the same thing" impossible. The charter
adds intentional close-out boundaries (allowed_paths, return-condition
status enum) so the child cannot quietly drift outside its declared scope.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_LOG = logging.getLogger(__name__)

DEFAULT_DEPTH_LIMIT: int = 3
"""The platform cap on parent-chain depth (D002). Frontmatter may declare a
LOWER value than this to tighten a single plan's allowed nesting; CLI's
`--allow-depth N` is the only mechanism for raising the cap at dispatch."""

GOAL_GAP_MIN_FINDINGS_PER_CLUSTER: int = 3
"""Goal Governance F0: minimum findings in a coherent cluster before the
triage classifier may recommend a child plan."""

GOAL_GAP_MIN_SEVERITY_FOR_CHILD_PLAN: str = "medium"
"""Goal Governance F0: at least one finding in the cluster must be medium+
before the triage classifier may recommend a child plan."""

GOAL_GAP_MAX_CHILD_PLANS_PER_PARENT_PASS: int = 3
"""Goal Governance F0: cap on child plans spawned from one parent goal-audit
pass. Safety rail only; does not auto-spawn children."""

GOAL_GAP_MAX_NESTING_DEPTH: int = 2
"""Goal Governance F0: tighter governance-specific cap nested within the
platform DEFAULT_DEPTH_LIMIT=3. Parent -> child is the default; grandchildren
remain out of scope without explicit operator override in a later plan."""

GOAL_GOVERNANCE_EVIDENCE_PREFIX: str = "evidence/goal-governance"
"""Goal Governance F0: plan-relative evidence prefix for objective-contract,
sufficiency, completion, and journey-walk evidence."""

GoalGapTriage = Literal["inline_fix", "child_plan", "follow_up_plan", "operator_deferred"]
GoalGovernancePassName = Literal["pre_impl", "post_impl"]

_GOAL_GAP_SEVERITY_RANK: dict[str, int] = {
    "low": 0,
    "advisory": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


class NestedOrchestrationError(ValueError):
    """Raised when a nested-orchestration guard refuses dispatch."""


class SpawnFinding(BaseModel):
    """Structured identity of the parent finding that motivates this child plan
    (D001). All five fields are required; `finding_signature` is the
    deterministic hash used by `check_repeated_finding` to detect "same
    finding climbing the chain" inception-loss.
    """

    model_config = ConfigDict(extra="forbid")

    parent_audit_id: str = Field(
        ..., description="`{plan_id}#{agent}#{iteration}` of the parent envelope."
    )
    finding_id: str = Field(
        ...,
        description="Auditor-assigned finding identifier within the parent envelope.",
    )
    finding_code: str = Field(..., description="Structured code (e.g., 'EC5', 'S101').")
    finding_class: str = Field(
        ...,
        description="Category (e.g., 'correctness', 'security', 'test_coverage').",
    )
    finding_signature: str = Field(
        ...,
        description=(
            "Deterministic SHA-256 hex prefix of `{code}|{class}|{normalized_issue}` "
            "(see `compute_finding_signature`). Used by repeated-finding hard stop."
        ),
    )


SpawnReason = Literal["auditor_finding", "operator_manual"]


class Orchestration(BaseModel):
    """`orchestration` block from a child plan's plan.md frontmatter."""

    model_config = ConfigDict(extra="forbid")

    parent_plan_id: str = Field(..., description="Plan ID of the parent.")
    spawn_reason: SpawnReason = Field(
        ..., description="auditor_finding (with spawn_finding) or operator_manual."
    )
    spawn_finding: SpawnFinding | None = Field(
        default=None,
        description=(
            "Required when spawn_reason='auditor_finding'; must be None when "
            "spawn_reason='operator_manual'."
        ),
    )
    depth_limit: int = Field(
        default=DEFAULT_DEPTH_LIMIT,
        description=(
            "Per-plan depth cap. Frontmatter may declare a LOWER value than "
            "DEFAULT_DEPTH_LIMIT (3); higher values are rejected (D002). "
            "Operator can lift the cap at dispatch via CLI `--allow-depth N`."
        ),
    )

    @model_validator(mode="after")
    def _check_spawn_consistency(self) -> Orchestration:
        if self.spawn_reason == "auditor_finding" and self.spawn_finding is None:
            raise ValueError("spawn_reason='auditor_finding' requires a non-None spawn_finding")
        if self.spawn_reason == "operator_manual" and self.spawn_finding is not None:
            raise ValueError(
                "spawn_reason='operator_manual' must NOT carry a spawn_finding "
                "(operator declares strategic_objective + return_condition in child_charter instead)"
            )
        if self.depth_limit > DEFAULT_DEPTH_LIMIT:
            raise ValueError(
                f"depth_limit={self.depth_limit} exceeds platform cap "
                f"{DEFAULT_DEPTH_LIMIT}; frontmatter cannot raise the cap (D002). "
                "Use `--allow-depth N` at dispatch instead."
            )
        if self.depth_limit < 1:
            raise ValueError(f"depth_limit must be >= 1, got {self.depth_limit}")
        return self


# ──────────────────────────────  signature  ──────────────────────────────


_WHITESPACE_RE = re.compile(r"\s+")


def compute_finding_signature(finding_code: str, finding_class: str, issue: str) -> str:
    """Deterministic SHA-256 hex prefix of `{code}|{class}|{normalized_issue}`.

    Normalization collapses runs of whitespace + lowercases — same finding
    text with different formatting yields the same signature (D001).
    Returns the first 16 hex characters of the digest (64 bits) — enough
    for collision-free identity within a plan tree without bloating the
    parent_chain walk.
    """
    normalized = _WHITESPACE_RE.sub(" ", (issue or "").strip()).lower()
    payload = f"{finding_code}|{finding_class}|{normalized}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def compute_audit_finding_signature(finding: dict[str, Any]) -> str | None:
    """Plan 2026-05-02-004: derive a stable signature for a single auditor
    Finding dict (entries inside an audit envelope's ``findings`` list).

    Composition: ``{file}:{line}`` locality (when ``file`` is set) +
    ``category`` + normalized ``issue`` text, hashed via the existing
    ``compute_finding_signature`` primitive. Severity is intentionally
    excluded (D002) — a high→medium downgrade is the same finding with a
    re-evaluated severity, not a different finding.

    Returns ``None`` when ``issue`` text is missing or whitespace-only.
    Callers should treat ``None`` as a fallback signal; the diminishing-
    returns breaker degrades to count-based behavior (D004) when ANY round
    in its convergence window has an unsigned finding.

    Used by ``circuit_breakers.check_diminishing_returns`` to detect 'same
    unresolved findings persist' as opposed to 'auditor flagged a similar
    count of different findings.' Shared with the F001 repeated-finding
    guard via the same primitive so the two surfaces have one notion of
    finding identity.
    """
    issue = finding.get("issue")
    if not isinstance(issue, str) or not issue.strip():
        return None
    file_loc = finding.get("file") or ""
    line_loc = finding.get("line")
    locality = f"{file_loc}:{line_loc}" if file_loc else ""
    category = str(finding.get("category") or "")
    return compute_finding_signature(
        finding_code=locality,
        finding_class=category,
        issue=issue,
    )


# ──────────────────────────────  parent-chain helpers  ──────────────────────────────


def _read_orchestration_from_plan(plan_dir: Path) -> Orchestration | None:
    """Pop the `orchestration` block from a plan.md's frontmatter (if any)
    and parse it into the Pydantic model. Returns None for top-level plans.

    Kept here rather than on plan_loader so this module can walk parent
    chains without importing plan_loader (avoiding a circular dependency
    when plan_loader itself imports `Orchestration`).
    """
    plan_md = plan_dir / "plan.md"
    if not plan_md.is_file():
        raise FileNotFoundError(plan_md)
    text = plan_md.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    frontmatter = yaml.safe_load(parts[1]) or {}
    block = frontmatter.get("orchestration")
    if block is None:
        return None
    return Orchestration.model_validate(block)


def _resolve_parent_dir(parent_plan_id: str, plans_root: Path) -> Path:
    """Resolve `<plans_root>/<parent_plan_id>/`. Used by walk_parent_chain
    in tests where plans_root is tmp_path; production callers should pass
    `<repo>/docs/plans` as the root.
    """
    candidate = plans_root / parent_plan_id
    if not candidate.is_dir():
        raise NestedOrchestrationError(
            f"parent plan_id {parent_plan_id!r} not found under {plans_root}"
        )
    return candidate


def _read_plan_id(plan_dir: Path) -> str:
    """Cheap read of `id:` from a plan.md frontmatter without invoking the full
    Pydantic Plan validator (which would trip on `extra=forbid` against an
    unknown `orchestration` key in older callers)."""
    plan_md = plan_dir / "plan.md"
    text = plan_md.read_text()
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise NestedOrchestrationError(f"{plan_md}: malformed frontmatter")
    fm = yaml.safe_load(parts[1]) or {}
    plan_id = fm.get("id")
    if not isinstance(plan_id, str):
        raise NestedOrchestrationError(f"{plan_md}: missing or non-string `id`")
    return plan_id


def walk_parent_chain(plan_dir: Path, *, plans_root: Path | None = None) -> list[str]:
    """Return [plan_id, parent_plan_id, grandparent_plan_id, ...].

    Top-level plan (no orchestration block) returns `[plan_id]` (length 1).
    `plans_root` defaults to the directory holding `plan_dir`; tests pass
    a tmp_path. Production callers should pass `<repo>/docs/plans`.
    """
    plan_dir = plan_dir.resolve()
    if plans_root is None:
        plans_root = plan_dir.parent
    plans_root = plans_root.resolve()

    chain: list[str] = []
    seen: set[str] = set()
    current = plan_dir
    while True:
        cur_id = _read_plan_id(current)
        chain.append(cur_id)
        if cur_id in seen:
            # Cycle — let check_cycle surface the diagnostic; here just stop.
            return chain
        seen.add(cur_id)

        orch = _read_orchestration_from_plan(current)
        if orch is None:
            return chain
        parent_id = orch.parent_plan_id
        if parent_id in seen:
            chain.append(parent_id)
            return chain
        current = _resolve_parent_dir(parent_id, plans_root)


def compute_depth(plan_dir: Path, *, plans_root: Path | None = None) -> int:
    """Length of the parent chain (1 = top-level plan)."""
    return len(walk_parent_chain(plan_dir, plans_root=plans_root))


# ──────────────────────────────  guards  ──────────────────────────────


def check_depth(
    plan_dir: Path,
    *,
    override_max: int | None = None,
    plans_root: Path | None = None,
) -> None:
    """Raise NestedOrchestrationError if depth exceeds the effective cap.

    Effective cap is the LOWER of the plan's frontmatter depth_limit and
    `override_max` if set; CLI `--allow-depth N` passes override_max=N at
    dispatch (D002). Top-level plans (no orchestration block) always pass.
    """
    orch = _read_orchestration_from_plan(plan_dir)
    if orch is None:
        return

    depth = compute_depth(plan_dir, plans_root=plans_root)
    cap = override_max if override_max is not None else orch.depth_limit

    if depth > cap:
        raise NestedOrchestrationError(
            f"depth {depth} exceeds cap {cap} for plan {_read_plan_id(plan_dir)!r}"
            + (f" (CLI override allowed_depth={override_max})" if override_max else "")
        )


def check_cycle(plan_dir: Path, *, plans_root: Path | None = None) -> None:
    """Raise NestedOrchestrationError if any plan_id appears twice in the
    parent chain."""
    chain = walk_parent_chain(plan_dir, plans_root=plans_root)
    seen: set[str] = set()
    for plan_id in chain:
        if plan_id in seen:
            raise NestedOrchestrationError(
                f"cycle in parent chain: plan_id {plan_id!r} appears twice in chain {chain}"
            )
        seen.add(plan_id)


def check_repeated_finding(plan_dir: Path, *, plans_root: Path | None = None) -> None:
    """Raise NestedOrchestrationError if the current plan's spawn_finding
    signature matches any parent plan's recorded signature (D001).

    This is the inception-loss guard: a child claiming to fix the same
    finding that a parent in the chain already claimed to fix → hard stop.
    """
    plan_dir = plan_dir.resolve()
    if plans_root is None:
        plans_root = plan_dir.parent
    plans_root = plans_root.resolve()

    orch = _read_orchestration_from_plan(plan_dir)
    if orch is None or orch.spawn_finding is None:
        return  # Top-level or operator_manual with no finding.

    target_sig = orch.spawn_finding.finding_signature
    current_id = _read_plan_id(plan_dir)

    # Walk the chain BEYOND the current plan and check each ancestor's
    # spawn_finding.signature.
    cur_orch = orch
    while True:
        parent_id = cur_orch.parent_plan_id
        try:
            parent_dir = _resolve_parent_dir(parent_id, plans_root)
        except NestedOrchestrationError:
            return  # Parent missing — separate error path; let walker handle.

        parent_orch = _read_orchestration_from_plan(parent_dir)
        # If the parent has a spawn_finding with matching signature → collision.
        if parent_orch is not None and parent_orch.spawn_finding is not None:
            if parent_orch.spawn_finding.finding_signature == target_sig:
                raise NestedOrchestrationError(
                    f"repeated finding signature {target_sig!r} climbing parent "
                    f"chain: child plan {current_id!r} declared the same "
                    f"finding_signature as parent plan {parent_id!r} "
                    f"(code={orch.spawn_finding.finding_code}, "
                    f"class={orch.spawn_finding.finding_class})"
                )

        if parent_orch is None:
            return  # Reached a top-level plan; no more parents to check.
        cur_orch = parent_orch


# ──────────────────────────────  Goal Governance F0 — goal-gap config  ──────────────────────────────


class GoalGapFinding(BaseModel):
    """A normalized goal-governance finding used by the F0 triage classifier.

    This is deliberately smaller than an audit envelope Finding. F1/F2 can
    adapt richer auditor output into this typed shape before classification.
    """

    model_config = ConfigDict(extra="forbid")

    severity: str = Field(..., min_length=1)
    finding_id: str = Field(..., min_length=1)
    issue: str = Field(..., min_length=1)
    subsystem: str = Field(..., min_length=1)
    journey: str = Field(..., min_length=1)

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _GOAL_GAP_SEVERITY_RANK:
            raise ValueError(f"unknown goal-gap severity: {value!r}")
        return normalized


class GoalGapClusterContext(BaseModel):
    """Context for classifying one coherent goal-gap cluster."""

    model_config = ConfigDict(extra="forbid")

    subsystem: str = Field(..., min_length=1)
    journey: str = Field(..., min_length=1)
    coherence_rule: Literal["subsystem_and_journey", "same_subsystem", "same_journey", "mixed"] = (
        "subsystem_and_journey"
    )
    fits_existing_feature_scope: bool = False
    explicitly_out_of_scope: bool = False
    operator_deferred: bool = False
    existing_goal_gap_children: list[Any] = Field(default_factory=list)


def _goal_gap_severity_at_least(severity: str, threshold: str) -> bool:
    """Compare goal-gap severities. Unknown values are invalid by design."""
    try:
        severity_rank = _GOAL_GAP_SEVERITY_RANK[severity.strip().lower()]
        threshold_rank = _GOAL_GAP_SEVERITY_RANK[threshold.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"unknown goal-gap severity: {exc.args[0]!r}") from None
    return severity_rank >= threshold_rank


def classify_goal_gap_cluster(
    findings: list[GoalGapFinding],
    cluster: GoalGapClusterContext,
) -> GoalGapTriage:
    """Pure goal-gap triage classifier.

    Returns a recommendation only; it never spawns plans or mutates state.
    Rules are the F0 encoding of GOAL_GOVERNANCE_V1 §3.3 + §6.4.
    """
    if not findings:
        return "operator_deferred"
    if cluster.operator_deferred:
        return "operator_deferred"
    if cluster.explicitly_out_of_scope:
        return "follow_up_plan"

    has_medium_plus = any(
        _goal_gap_severity_at_least(f.severity, GOAL_GAP_MIN_SEVERITY_FOR_CHILD_PLAN)
        for f in findings
    )
    if (
        len(findings) >= GOAL_GAP_MIN_FINDINGS_PER_CLUSTER
        and has_medium_plus
        and cluster.coherence_rule == "subsystem_and_journey"
    ):
        return "child_plan"

    if len(findings) <= 2 and not has_medium_plus and cluster.fits_existing_feature_scope:
        return "inline_fix"

    return "operator_deferred"


def validate_goal_gap_child_plan_caps(
    existing_goal_gap_children: list[Any],
    *,
    current_depth: int = 1,
    max_children: int = GOAL_GAP_MAX_CHILD_PLANS_PER_PARENT_PASS,
    max_depth: int = GOAL_GAP_MAX_NESTING_DEPTH,
) -> None:
    """Raise if goal-gap child-plan caps would be exceeded.

    Caps are safety rails for operator-approved spawns, not auto-spawn
    triggers. ``current_depth`` follows the existing nested-orchestration
    convention: 1 is a top-level parent plan.
    """
    if len(existing_goal_gap_children) >= max_children:
        raise ValueError(
            "goal-gap child-plan cap exceeded: "
            f"{len(existing_goal_gap_children)} existing children >= max {max_children}"
        )
    next_depth = current_depth + 1
    if next_depth > max_depth:
        raise ValueError(
            f"goal-gap nesting depth cap exceeded: next_depth={next_depth} > max_depth={max_depth}"
        )


def goal_governance_evidence_path(
    plan_dir: Path,
    pass_name: GoalGovernancePassName,
    artifact: str,
) -> Path:
    """Return a path under evidence/goal-governance/{pre_impl|post_impl}/."""
    artifact_path = Path(artifact)
    if artifact_path.is_absolute() or ".." in artifact_path.parts:
        raise ValueError(f"artifact must be relative and stay under evidence prefix: {artifact!r}")
    return plan_dir / GOAL_GOVERNANCE_EVIDENCE_PREFIX / pass_name / artifact_path


GOAL_GAP_CHILD_CHARTER_TEMPLATE = """\
# Goal-gap context (schema comments; builder validates these before rendering)
# parent_objective_contract_id: "{parent_objective_contract_id}"
# gap_class: "{gap_class}"
# cluster_scope:
{cluster_scope_comments}
# severity: "{severity}"
# surfaces_affected:
{surfaces_affected_comments}
# why_child_plan_not_feature: "{why_child_plan_not_feature}"
child_charter:
  kind: implementation
  parent_objective: "{parent_objective}"
  parent_acceptance_item: "{parent_acceptance_item}"
  allowed_paths:
{allowed_paths}
  forbidden_decisions:
{forbidden_decisions}
  return_condition_summary: "{return_condition_summary}"
  may_edit_product_code: {may_edit_product_code}
  may_spawn_children: false
"""
"""Reference template for goal-gap child charters. F1/F2 may render this into
plan.md frontmatter after explicit operator approval."""


def _yaml_block(value: Any, *, indent: int = 4) -> str:
    dumped = yaml.safe_dump(value, default_flow_style=False, sort_keys=False).rstrip()
    return "\n".join((" " * indent) + line for line in dumped.splitlines())


def _comment_block(value: Any) -> str:
    dumped = yaml.safe_dump(value, default_flow_style=False, sort_keys=False).rstrip()
    return "\n".join(f"#   {line}" for line in dumped.splitlines())


def build_goal_gap_charter(
    *,
    parent_objective_contract_id: str,
    gap_class: str,
    cluster_scope: dict[str, Any],
    severity: str,
    surfaces_affected: list[str],
    why_child_plan_not_feature: str,
    existing_goal_gap_children: list[Any],
    parent_objective: str = "Close a bounded goal-governance gap.",
    parent_acceptance_item: str = "Goal-governance child gap closes.",
    allowed_paths: list[str] | None = None,
    forbidden_decisions: list[str] | None = None,
    return_condition_summary: str | None = None,
    may_edit_product_code: bool = True,
) -> str:
    """Render a goal-gap child-charter YAML snippet.

    The rationale is intentionally required; it records why this gap is a
    bounded child plan rather than another feature or a follow-up plan.
    """
    validate_goal_gap_child_plan_caps(existing_goal_gap_children)
    if len(why_child_plan_not_feature.strip()) < 20:
        raise ValueError("why_child_plan_not_feature must be at least 20 characters")
    if not parent_objective_contract_id.strip():
        raise ValueError("parent_objective_contract_id is required")
    if not gap_class.strip():
        raise ValueError("gap_class is required")
    if not surfaces_affected:
        raise ValueError("surfaces_affected must not be empty")
    _goal_gap_severity_at_least(severity, "low")

    resolved_allowed_paths = allowed_paths or ["**/*"]
    resolved_forbidden = forbidden_decisions or []
    resolved_return = return_condition_summary or (
        f"Goal-gap child closes {gap_class} for objective {parent_objective_contract_id}."
    )
    return GOAL_GAP_CHILD_CHARTER_TEMPLATE.format(
        parent_objective_contract_id=parent_objective_contract_id,
        gap_class=gap_class,
        cluster_scope_comments=_comment_block(cluster_scope),
        severity=severity.strip().lower(),
        surfaces_affected_comments=_comment_block(surfaces_affected),
        why_child_plan_not_feature=why_child_plan_not_feature.strip(),
        parent_objective=parent_objective,
        parent_acceptance_item=parent_acceptance_item,
        allowed_paths=_yaml_block(resolved_allowed_paths),
        forbidden_decisions=_yaml_block(resolved_forbidden),
        return_condition_summary=resolved_return,
        may_edit_product_code=str(may_edit_product_code).lower(),
    )


GOAL_GAP_FAN_IN_MEMO_TEMPLATE = """\
# Fan-in from {child_plan_id}

objective_contract_id: {objective_contract_id}
gap_class_closed: {gap_class_closed}

## What changed in the child
<one or two sentences summarizing the child's contribution>

## How the parent objective contract was observed
<which artifact / commit / test demonstrates the goal gap is closed>

## Open follow-ups
<anything the parent's next iteration should pick up; '(none)' is fine>

## Return Condition

status: satisfied
"""
"""Goal-gap-specific fan-in memo template. The standard Return Condition
section remains unchanged; the sibling parser validates the two goal fields."""


_GOAL_GAP_OBJECTIVE_CONTRACT_RE = re.compile(
    r"^\s*objective_contract_id\s*:\s*(\S.*?)\s*$",
    re.MULTILINE,
)
_GOAL_GAP_CLASS_CLOSED_RE = re.compile(
    r"^\s*gap_class_closed\s*:\s*(\S.*?)\s*$",
    re.MULTILINE,
)


def parse_goal_gap_fan_in_memo_fields(memo_path: Path) -> dict[str, str]:
    """Parse goal-gap-specific fan-in memo fields.

    This sibling parser leaves the generic fan-in status parser untouched. It
    first reuses parse_return_condition_section() so malformed return-condition
    memos fail with the existing errors, then validates the two goal fields.
    """
    parse_return_condition_section(memo_path)
    text = memo_path.read_text()
    objective_match = _GOAL_GAP_OBJECTIVE_CONTRACT_RE.search(text)
    if objective_match is None:
        raise ReturnConditionError(
            f"goal-gap fan-in memo missing `objective_contract_id:` line in {memo_path}"
        )
    gap_match = _GOAL_GAP_CLASS_CLOSED_RE.search(text)
    if gap_match is None:
        raise ReturnConditionError(
            f"goal-gap fan-in memo missing `gap_class_closed:` line in {memo_path}"
        )
    return {
        "objective_contract_id": objective_match.group(1).strip(),
        "gap_class_closed": gap_match.group(1).strip(),
    }


# ──────────────────────────────  F002 — child charter + commit policy  ──────────────────────────────
#
# The charter declares the bounded work (allowed_paths, return-condition,
# kind), and the commit_policy declares whether the child is allowed to
# commit code (child_commit) or only produce evidence (evidence_only).
# Cross-field invariant (D003): mode and may_edit_product_code must agree.
# Enforcement is at signoff time, NOT at dispatch — the agent can technically
# write anywhere, but signoff refuses to land if it drifted outside scope.


ChildCharterKind = Literal["implementation"]
"""Only 'implementation' children are supported in v1. 'governance_design'
and any future kinds are deferred to v2."""

CommitPolicyMode = Literal["child_commit", "evidence_only"]
"""'child_commit' = child squashes its own commits to the working tree;
'evidence_only' = child produces evidence/* only (no product-code edits).
'parent_squash' is deferred to v2."""

ReturnConditionStatus = Literal["satisfied", "blocked", "superseded"]
"""D004: the three legal close-out statuses. 'satisfied' = parent's return
condition met; 'blocked' = child terminated without resolving; 'superseded' =
work moved to a different plan or scope changed."""

RequiresItem = Literal["patch_completeness", "tests_pass", "evidence_packaged"]
"""commit_policy.requires items (subset). Each must be satisfied by the
signoff envelope at close-out time, else ChildCharterViolation."""


class ReturnConditionError(ValueError):
    """Raised by parse_return_condition_section when the close-out memo's
    `## Return Condition` section is missing or malformed (D004)."""


class ChildCharterViolation(ValueError):
    """Raised at signoff time when the child charter check fails:
    return-condition section missing/invalid, files modified outside
    allowed_paths under child_commit mode, or a commit_policy.requires
    item is unsatisfied. signoff envelope MUST NOT be written on raise
    (no-partial-artifact, mirrors plan 005 F002 acceptance #5)."""


class CommitPolicy(BaseModel):
    """`commit_policy` block from a child plan's frontmatter.

    Default `mode='evidence_only'` per D003 — code-writing authority must
    be explicit, not inherited from defaults. Cross-field invariant with
    `child_charter.may_edit_product_code` is enforced separately by
    `validate_charter_policy_consistency` (the two blocks parse independently
    so the cross-check happens after both have validated).
    """

    model_config = ConfigDict(extra="forbid")

    mode: CommitPolicyMode = Field(
        default="evidence_only",
        description=(
            "'child_commit' or 'evidence_only'. Defaults to 'evidence_only' "
            "(D003 — code-writing authority must be explicit). 'parent_squash' "
            "is deferred to v2 and rejected at parse time."
        ),
    )
    requires: list[RequiresItem] = Field(
        default_factory=list,
        description=(
            "Subset of {'patch_completeness', 'tests_pass', 'evidence_packaged'}. "
            "Each item is checked by check_child_charter_compliance against the "
            "signoff envelope at close-out time."
        ),
    )

    @field_validator("mode", mode="before")
    @classmethod
    def _check_mode(cls, v: Any) -> Any:
        if v == "parent_squash":
            raise ValueError(
                "commit_policy.mode='parent_squash' is deferred to v2 "
                "(plan 003 v1 supports modes 'child_commit' and 'evidence_only')"
            )
        return v


class ChildCharter(BaseModel):
    """`child_charter` block from a child plan's frontmatter.

    Declares the bounded work, parent objective, allowed paths, and
    return-condition shape. `may_edit_product_code` has NO default per D003 —
    operator must declare intent explicitly when authoring the plan.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ChildCharterKind = Field(
        ...,
        description=(
            "Only 'implementation' is supported in v1. 'governance_design' is "
            "deferred to v2 and rejected at parse time with a deferral message."
        ),
    )
    parent_objective: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="What the parent needed when it spawned this child (≤500 chars).",
    )
    parent_acceptance_item: str = Field(
        ...,
        min_length=1,
        description="The parent acceptance clause this child unblocks.",
    )
    allowed_paths: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "fnmatch-style glob patterns. When commit_policy.mode='child_commit', "
            "every modified file must match at least one glob; otherwise "
            "ChildCharterViolation. Mode='evidence_only' skips this check."
        ),
    )
    forbidden_decisions: list[str] = Field(
        default_factory=list,
        description="Free-form decisions the child must not take (informational).",
    )
    return_condition_summary: str = Field(
        ...,
        min_length=1,
        description=(
            "One short text describing the observable signal — used to render "
            "the `## Return Condition` section template in the close-out memo. "
            "The structured `status:` line is what enforcement reads (D004)."
        ),
    )
    may_edit_product_code: bool = Field(
        ...,
        description=(
            "Whether the child is allowed to modify product code. NO default "
            "per D003 — operator must declare intent explicitly. Cross-field "
            "invariant with commit_policy.mode."
        ),
    )
    may_spawn_children: bool = Field(
        default=False,
        description=(
            "Whether this child may itself appear as a parent_plan_id on a "
            "grandchild plan. Defaults False; v1 enforces no grandchild-spawn "
            "in nested_orchestration guards (deferred wiring lives in F003)."
        ),
    )

    @field_validator("kind", mode="before")
    @classmethod
    def _check_kind(cls, v: Any) -> Any:
        if v == "governance_design":
            raise ValueError(
                "child_charter.kind='governance_design' is deferred to v2 "
                "(plan 003 v1 supports kind='implementation' only)"
            )
        return v


def validate_charter_policy_consistency(charter: ChildCharter, policy: CommitPolicy) -> None:
    """D003 cross-field invariant: commit_policy.mode and
    child_charter.may_edit_product_code must agree on intent.

    - mode='child_commit' requires may_edit_product_code=True
    - mode='evidence_only' requires may_edit_product_code=False

    Raises ValueError on mismatch. Plan_loader calls this after both blocks
    have parsed (Pydantic validators on either side cannot see the other
    block, so the cross-check is a separate function call).
    """
    if policy.mode == "child_commit" and not charter.may_edit_product_code:
        raise ValueError(
            "commit_policy.mode='child_commit' requires "
            "child_charter.may_edit_product_code=true (D003 cross-field invariant)"
        )
    if policy.mode == "evidence_only" and charter.may_edit_product_code:
        raise ValueError(
            "commit_policy.mode='evidence_only' requires "
            "child_charter.may_edit_product_code=false "
            "(D003 cross-field invariant — code-writing authority is "
            "child_commit-only)"
        )


# ──────────────────────────────  Return Condition parser (D004)  ──────────────────────────────


# The heading must be exactly `## Return Condition` (case-sensitive on the
# words; leading whitespace permitted). The status line is case-insensitive
# on both keyword and value (per D004).
_RETURN_CONDITION_HEADING_RE = re.compile(r"^\s*##\s+Return Condition\s*$", re.MULTILINE)
_NEXT_H2_HEADING_RE = re.compile(r"^\s*##\s+", re.MULTILINE)
_STATUS_LINE_RE = re.compile(r"^\s*status\s*:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
_LEGAL_STATUSES = {"satisfied", "blocked", "superseded"}


def parse_return_condition_section(memo_path: Path) -> ReturnConditionStatus:
    """D004: parse the structured `## Return Condition` section of the
    close-out memo and return one of {'satisfied', 'blocked', 'superseded'}.

    Heading must be exactly `## Return Condition` (h2; leading whitespace
    permitted). Within the section, finds the FIRST line matching
    `^\\s*status:\\s*<value>\\s*$` (keyword + value case-insensitive).
    Returns the lowercased status.

    Raises ReturnConditionError on:
      - missing memo file
      - missing `## Return Condition` section
      - missing `status:` line within the section
      - illegal status value (not in {satisfied, blocked, superseded})
      - multiple `status:` lines (ambiguous)
    """
    if not memo_path.is_file():
        raise ReturnConditionError(f"close-out memo not found: {memo_path}")
    text = memo_path.read_text()

    heading_match = _RETURN_CONDITION_HEADING_RE.search(text)
    if heading_match is None:
        raise ReturnConditionError(
            f"`## Return Condition` section missing in {memo_path} "
            "(D004 — must be a literal h2 heading)"
        )

    section_start = heading_match.end()
    next_heading = _NEXT_H2_HEADING_RE.search(text, pos=section_start)
    section_text = (
        text[section_start : next_heading.start()] if next_heading else text[section_start:]
    )

    status_matches = list(_STATUS_LINE_RE.finditer(section_text))
    if not status_matches:
        raise ReturnConditionError(
            f"`## Return Condition` section in {memo_path} has no "
            "`status:` line (D004 — must be `status: satisfied|blocked|superseded`)"
        )
    if len(status_matches) > 1:
        raise ReturnConditionError(
            f"`## Return Condition` section in {memo_path} has multiple "
            f"`status:` lines (found {len(status_matches)}); only one is permitted"
        )

    raw_value = status_matches[0].group(1).strip().lower()
    if raw_value not in _LEGAL_STATUSES:
        raise ReturnConditionError(
            f"`## Return Condition` status={raw_value!r} not in "
            f"{sorted(_LEGAL_STATUSES)!r} in {memo_path}"
        )
    return raw_value  # type: ignore[return-value]


# ──────────────────────────────  signoff-time charter compliance  ──────────────────────────────


def _matches_any_glob(path: str, globs: list[str]) -> bool:
    """fnmatch a path against a list of glob patterns. Returns True on any
    match. Empty `globs` returns False (vacuous-true would defeat the check)."""
    return any(fnmatch.fnmatch(path, g) for g in globs)


def _git_modified_files(plan_dir: Path) -> list[str]:
    """Best-effort `git diff --name-only HEAD` from the repo root inferred
    from plan_dir. Returns the list of modified-but-not-committed paths
    (relative to repo root). Returns [] if git is unavailable, the plan_dir
    is not in a git repo, or the command fails — callers should be tolerant
    of empty results (the allowed_paths check is meaningful only when there
    are modified files to check)."""
    repo_root: Path | None = None
    cur = plan_dir.resolve()
    for ancestor in (cur, *cur.parents):
        if (ancestor / ".git").exists():
            repo_root = ancestor
            break
    if repo_root is None:
        return []

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_child_charter_compliance(
    *,
    plan_dir: Path,
    child_charter: ChildCharter,
    commit_policy: CommitPolicy,
    signoff_data: dict[str, Any],
    modified_files: list[str] | None = None,
) -> dict[str, Any]:
    """Plan 2026-05-02-003 F002: signoff-time charter compliance check.

    Three checks (D003 + D004):

    (1) ``parse_return_condition_section`` against
        ``<plan_dir>/evidence/closeout-memo.md``. Missing section / illegal
        value / ambiguity → ChildCharterViolation. The parsed status is
        returned in the compliance dict; recording does NOT raise on
        ``blocked``/``superseded`` — F003 is what refuses parent re-entry on
        non-satisfied (per AC#6).

    (2) When ``commit_policy.mode='child_commit'``: every modified file
        (passed in or queried via ``git diff --name-only HEAD``) must match
        at least one glob in ``child_charter.allowed_paths``; otherwise
        ChildCharterViolation. Mode='evidence_only' skips this check
        entirely (no git invocation).

    (3) For each item in ``commit_policy.requires``:
        - 'tests_pass' → ``signoff_data['signoff']`` is True (the volley
          signed off; absent or False → violation).
        - 'patch_completeness' → ``signoff_data['audits']`` is non-empty
          (at least one audit envelope underpins the signoff).
        - 'evidence_packaged' → ``<plan_dir>/evidence/`` exists and is
          non-empty.

    Returns a side-car compliance dict (intended for persistence at
    ``audit/charter-compliance-{plan_id}.json``). Does NOT mutate
    ``signoff_data``; the canonical Signoff schema (agent-conventions
    v1.0) stays unchanged — schema-discipline pattern matching F001's
    pop-orchestration-block-before-validate.

    Raises ``ChildCharterViolation`` (or ``ReturnConditionError``, which is
    NOT a subclass) on any failure; the supervisor's signoff_writer call
    catches both and refuses to persist a partial signoff envelope.
    """
    memo_path = plan_dir / "evidence" / "closeout-memo.md"
    try:
        status = parse_return_condition_section(memo_path)
    except ReturnConditionError as exc:
        raise ChildCharterViolation(str(exc)) from exc

    if commit_policy.mode == "child_commit":
        files = modified_files if modified_files is not None else _git_modified_files(plan_dir)
        violations = [f for f in files if not _matches_any_glob(f, child_charter.allowed_paths)]
        if violations:
            raise ChildCharterViolation(
                f"files modified outside allowed_paths: {violations} "
                f"(allowed_paths={list(child_charter.allowed_paths)})"
            )

    satisfied: list[str] = []
    for item in commit_policy.requires:
        if item == "tests_pass":
            if not signoff_data.get("signoff"):
                raise ChildCharterViolation(
                    "requires=tests_pass not satisfied: "
                    f"signoff_data['signoff']={signoff_data.get('signoff')!r} "
                    "(volley did not sign off)"
                )
            satisfied.append("tests_pass")
        elif item == "patch_completeness":
            if not signoff_data.get("audits"):
                raise ChildCharterViolation(
                    "requires=patch_completeness not satisfied: "
                    "signoff_data['audits'] is empty (no audit envelopes)"
                )
            satisfied.append("patch_completeness")
        elif item == "evidence_packaged":
            evidence_dir = plan_dir / "evidence"
            if not evidence_dir.is_dir() or not any(evidence_dir.iterdir()):
                raise ChildCharterViolation(
                    f"requires=evidence_packaged not satisfied: {evidence_dir} is missing or empty"
                )
            satisfied.append("evidence_packaged")
        # Pydantic Literal validation prevents unknown items from reaching here.

    return {
        "task_id": signoff_data.get("task_id"),
        "return_condition_status": status,
        "compliance_checks_satisfied": satisfied,
        "commit_policy_mode": commit_policy.mode,
        "decided_at": _now_iso(),
    }


# ──────────────────────────────  F003 — parent pause / fan-in protocol  ──────────────────────────────
#
# When a child plan dispatches, the supervisor arms a
# `pre_resume_after_child:{child_plan_id}` gate on the parent. The parent's
# next dispatch sees the unmet gate and pauses. To resume, the operator runs
# `jarvis approve <parent> pre_resume_after_child --child <child>`, which
# refuses unless (a) the fan-in memo at parent's
# `evidence/fan-in-from-{child_plan_id}.md` exists and declares
# `## Return Condition / status: satisfied`, AND (b) the child's
# `audit/charter-compliance-{child_plan_id}.json` records
# `return_condition_status: satisfied` (or `--accept-non-satisfied` is set).
#
# Anti-recursion thesis: the explicit-approval-with-status-satisfied
# requirement is the operator's last-mile check that the child actually
# resolved the parent finding before parent work resumes.


PRE_RESUME_GATE_PREFIX = "pre_resume_after_child:"


def pre_resume_gate_name(child_plan_id: str) -> str:
    """Canonical gate name for a parent waiting on a specific child plan."""
    return f"{PRE_RESUME_GATE_PREFIX}{child_plan_id}"


def fan_in_memo_path(parent_plan_dir: Path, child_plan_id: str) -> Path:
    """Path the operator must author at parent re-entry: `<parent>/evidence/
    fan-in-from-{child_plan_id}.md`. Existence + structured `## Return
    Condition / status: satisfied` are the operator's explicit declaration
    that they have reviewed the child's outcome and are resuming the parent."""
    return parent_plan_dir / "evidence" / f"fan-in-from-{child_plan_id}.md"


FAN_IN_MEMO_TEMPLATE = """\
# Fan-in from {child_plan_id}

## What changed in the child
<one or two sentences summarizing the child's contribution>

## How the parent return_condition_summary was observed
<which artifact / commit / test demonstrates the parent finding is resolved>

## Open follow-ups
<anything the parent's next iteration should pick up; '(none)' is fine>

## Return Condition

status: satisfied
"""
"""Stub the CLI prints when the operator runs `approve pre_resume_after_child`
with the memo missing. The structured `## Return Condition / status: …`
section is mandatory — the rest is operator-editable narrative."""


# ----- best-effort events.jsonl trace (D006) -----


def events_log_path(plan_dir: Path) -> Path:
    return plan_dir / "events.jsonl"


def record_event(
    plan_dir: Path,
    kind: str,
    payload: dict[str, Any],
    *,
    plan_id: str | None = None,
) -> bool:
    """Best-effort append-one-JSON-line trace. NEVER raises (D006).

    Returns True on successful append, False on failure. Failures log a
    WARNING with kind + plan_id + reason and return silently — events.jsonl
    is a trace/index for human visibility, NOT canonical state. Canonical
    state lives in plan files, audit/<envelope>.json, audit/gate-state.json,
    and audit/signoff-*.json (D006).

    Caller's responsibility to pass a JSON-serializable payload; this
    function adds `kind`, `plan_id`, and `ts` automatically.
    """
    record = {
        "kind": kind,
        "plan_id": plan_id,
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **payload,
    }
    try:
        line = json.dumps(record, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        _LOG.warning(
            "record_event: failed to serialize kind=%s plan_id=%s reason=%s",
            kind,
            plan_id,
            exc,
        )
        return False

    path = events_log_path(plan_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(line + "\n")
    except OSError as exc:
        _LOG.warning(
            "record_event: failed to append to %s kind=%s reason=%s",
            path,
            kind,
            exc,
        )
        return False
    return True


# ----- child compliance side-car reader (F002 D008 → F003 consumer) -----


def child_compliance_side_car_path(child_plan_dir: Path, child_plan_id: str) -> Path:
    """The F002 D008 side-car. F003 reads this to gate parent re-entry."""
    return child_plan_dir / "audit" / f"charter-compliance-{child_plan_id}.json"


def read_child_compliance(child_plan_dir: Path, child_plan_id: str) -> dict[str, Any] | None:
    """Read the child's charter-compliance side-car. Returns the parsed dict
    or None if the file is missing or malformed. The caller decides how to
    treat None (typically: refuse parent re-entry without
    `--accept-non-satisfied`, with a message naming the missing artifact)."""
    path = child_compliance_side_car_path(child_plan_dir, child_plan_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


# ----- fan-in memo parser (reuses F002's `## Return Condition` parser) -----


def parse_fan_in_memo_status(memo_path: Path) -> ReturnConditionStatus:
    """F003: parse the operator's fan-in memo for the structured `##
    Return Condition / status:` line. Reuses F002's parser since the contract
    is identical — only the file location differs.

    Raises ReturnConditionError on missing file / section / value (same as
    F002). The CLI handler converts the raise into ChildPauseApproveError
    so the user sees consistent F003 framing.
    """
    return parse_return_condition_section(memo_path)


# ----- approve / refuse pre_resume_after_child gate -----


class ChildPauseApproveError(NestedOrchestrationError):
    """F003: approve_pre_resume_after_child refused. Specific reasons:
    gate not active for this child, fan-in memo missing or non-satisfied,
    child compliance side-car missing or non-satisfied without override."""


def approve_pre_resume_after_child(
    parent_plan_dir: Path,
    *,
    parent_plan_id: str,
    child_plan_id: str,
    child_plan_dir: Path,
    accept_non_satisfied: bool = False,
) -> dict[str, Any]:
    """F003: validate + clear the `pre_resume_after_child:{child_plan_id}`
    gate on the parent. Returns a dict with the validation outcome (memo
    status, child status, override flag) suitable for INBOX bodies.

    Validation order (raises ChildPauseApproveError on first failure):

    1. Gate must be currently armed for this child.
    2. Fan-in memo at parent's
       ``evidence/fan-in-from-{child_plan_id}.md`` must exist.
    3. The memo must contain a structured ``## Return Condition / status:
       satisfied`` line. Even with ``--accept-non-satisfied``, the memo's
       OWN status must be ``satisfied`` — the memo is the operator's
       explicit re-entry declaration; ``--accept-non-satisfied`` only
       overrides the *child-side* status.
    4. Read the child's ``audit/charter-compliance-{child_plan_id}.json``
       side-car. If missing OR ``return_condition_status != 'satisfied'``,
       refuse unless ``accept_non_satisfied=True`` (records the override).

    On success, calls ``gate_pause.clear_pre_resume_after_child`` and
    returns the outcome dict. Caller (CLI) wraps with INBOX +
    ``record_event`` (best-effort).

    Note: this function does NOT itself write the INBOX entry or events
    line — that surface concern lives in the CLI handler. Same separation
    of concerns as F002's compliance check vs. side-car write.
    """
    # Late import to avoid load-time cycle (gate_pause imports nothing from
    # here, but the CLI surface routes through both modules).
    from dontpanic_orchestrate import gate_pause

    gate_str = pre_resume_gate_name(child_plan_id)
    active = gate_pause.active_pre_resume_after_children(parent_plan_dir)
    if gate_str not in active:
        raise ChildPauseApproveError(
            f"gate {gate_str!r} is not currently armed on parent "
            f"{parent_plan_id!r}; nothing to approve. Active gates: "
            f"{active or '(none)'}"
        )

    memo_path = fan_in_memo_path(parent_plan_dir, child_plan_id)
    if not memo_path.is_file():
        raise ChildPauseApproveError(
            f"fan-in memo missing at {memo_path}. Author it (template "
            f"available via CLI) and re-run approve."
        )

    try:
        memo_status = parse_fan_in_memo_status(memo_path)
    except ReturnConditionError as exc:
        raise ChildPauseApproveError(f"fan-in memo at {memo_path} malformed: {exc}") from exc

    if memo_status != "satisfied":
        raise ChildPauseApproveError(
            f"fan-in memo at {memo_path} declares status={memo_status!r}; "
            "must be 'satisfied' for parent re-entry. The memo is the "
            "operator's explicit re-entry declaration; --accept-non-satisfied "
            "overrides ONLY the child-side compliance status, not this memo."
        )

    child_compliance = read_child_compliance(child_plan_dir, child_plan_id)
    child_status = child_compliance.get("return_condition_status") if child_compliance else None

    override_applied = False
    if child_status != "satisfied":
        if not accept_non_satisfied:
            artifact_hint = (
                child_compliance_side_car_path(child_plan_dir, child_plan_id)
                if child_compliance is not None
                else f"{child_compliance_side_car_path(child_plan_dir, child_plan_id)} (file missing)"
            )
            raise ChildPauseApproveError(
                f"child {child_plan_id!r} compliance status={child_status!r} "
                f"(read from {artifact_hint}); refuse to clear "
                f"{gate_str!r} without --accept-non-satisfied. To override, "
                "re-run with --accept-non-satisfied and record the rationale "
                "in the parent's decisions.jsonl."
            )
        override_applied = True

    cleared = gate_pause.clear_pre_resume_after_child(
        parent_plan_dir,
        child_plan_id,
        plan_id=parent_plan_id,
        actor="operator",
        reason=(
            "approve_pre_resume_after_child: memo+child both satisfied"
            if not override_applied
            else f"approve_pre_resume_after_child: --accept-non-satisfied (child status={child_status!r})"
        ),
    )
    return {
        "gate": gate_str,
        "cleared": cleared,
        "memo_path": str(memo_path),
        "memo_status": memo_status,
        "child_status": child_status,
        "override_applied": override_applied,
    }


__all__ = [
    "DEFAULT_DEPTH_LIMIT",
    "FAN_IN_MEMO_TEMPLATE",
    "GOAL_GAP_CHILD_CHARTER_TEMPLATE",
    "GOAL_GAP_FAN_IN_MEMO_TEMPLATE",
    "GOAL_GAP_MAX_CHILD_PLANS_PER_PARENT_PASS",
    "GOAL_GAP_MAX_NESTING_DEPTH",
    "GOAL_GAP_MIN_FINDINGS_PER_CLUSTER",
    "GOAL_GAP_MIN_SEVERITY_FOR_CHILD_PLAN",
    "GOAL_GOVERNANCE_EVIDENCE_PREFIX",
    "PRE_RESUME_GATE_PREFIX",
    "ChildCharter",
    "ChildCharterKind",
    "ChildCharterViolation",
    "ChildPauseApproveError",
    "CommitPolicy",
    "CommitPolicyMode",
    "GoalGapClusterContext",
    "GoalGapFinding",
    "GoalGapTriage",
    "GoalGovernancePassName",
    "NestedOrchestrationError",
    "Orchestration",
    "RequiresItem",
    "ReturnConditionError",
    "ReturnConditionStatus",
    "SpawnFinding",
    "SpawnReason",
    "approve_pre_resume_after_child",
    "build_goal_gap_charter",
    "check_child_charter_compliance",
    "check_cycle",
    "check_depth",
    "check_repeated_finding",
    "child_compliance_side_car_path",
    "classify_goal_gap_cluster",
    "compute_audit_finding_signature",
    "compute_depth",
    "compute_finding_signature",
    "events_log_path",
    "fan_in_memo_path",
    "goal_governance_evidence_path",
    "parse_goal_gap_fan_in_memo_fields",
    "parse_fan_in_memo_status",
    "parse_return_condition_section",
    "pre_resume_gate_name",
    "read_child_compliance",
    "record_event",
    "validate_goal_gap_child_plan_caps",
    "validate_charter_policy_consistency",
    "walk_parent_chain",
]
