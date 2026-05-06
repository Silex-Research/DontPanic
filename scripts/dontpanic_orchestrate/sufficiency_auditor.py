"""Goal Governance V1 F003 — pre-impl sufficiency auditor.

Pure text-only auditor (no MCP, no runtime evidence). Walks the
``ObjectiveContract.user_journeys`` against the proposed
``features.json`` acceptance criteria and surfaces gap-class findings
(coverage / missing feature / wiring / parity / integration).

Public surface:

    run_sufficiency_audit(plan_dir, implementer_agent=None, ...) -> list[SufficiencyFinding]
    SufficiencyFinding (Pydantic model)
    SUFFICIENCY_GAP_CLASSES (allowed gap_class enum)
    SufficiencyAuditError (raised on configuration / contract failures)

Vendor resolution per Goal Governance V1 §5 + D006: the auditor is
``project_config.resolve_dispatch_defaults()['auditor']`` resolved
against the plan's project context. Same-vendor (auditor == implementer)
is rejected unless ``DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR`` is set
to a truthy value — that env var is the operator-override channel,
recorded in close-out evidence by the caller.

Lock enforcement is intentionally NOT in this module; that lives in
F004's plan-lock gate. F003 produces the findings; F004 decides what to
do with them.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dontpanic_orchestrate import project_config
from dontpanic_orchestrate.nested_orchestration import (
    _GOAL_GAP_SEVERITY_RANK,
    goal_governance_evidence_path,
)

# Re-resolve the agent-conventions schemas dir so the v1.4.0
# ``ObjectiveContract`` model is importable. Same candidate list used by
# ``audit_writer.py`` / ``plan_loader.py`` / ``environments_loader.py``
# (kept inline rather than centralized to keep the bootstrap surface flat).
_SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[2] / ".claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[3] / "agent-conventions" / "schemas" / "v1.0",
]
for _candidate in _SCHEMA_CANDIDATES:
    if (_candidate / "models").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from models.objective_contract_model import ObjectiveContract  # noqa: E402

# ──────────────────────────────  constants  ──────────────────────────────


SUFFICIENCY_GAP_CLASSES: tuple[str, ...] = (
    "coverage_gap",
    "missing_feature",
    "wiring_gap",
    "parity_gap",
    "integration_gap",
)
"""Top-level gap-class taxonomy a sufficiency finding may report. Pinned
here as the load-bearing vocabulary the prompt instructs the auditor to
emit; ``SufficiencyFinding`` validates against this tuple."""

GapClass = Literal[
    "coverage_gap",
    "missing_feature",
    "wiring_gap",
    "parity_gap",
    "integration_gap",
]

PRE_IMPL_FINDINGS_ARTIFACT: str = "sufficiency-findings.json"
"""Filename under ``evidence/goal-governance/pre_impl/`` per F0's path
convention (mirrors :data:`nested_orchestration.GOAL_GOVERNANCE_EVIDENCE_PREFIX`).
"""

_SAME_VENDOR_OVERRIDE_ENV: str = "DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR"
"""Operator override channel. When set to ``'1'`` / ``'true'`` / ``'yes'``
(case-insensitive), the cross-vendor invariant is relaxed and
``_resolve_goal_auditor_agent`` returns the resolved auditor even when
it equals the implementer. Recorded in close-out evidence by the
caller."""


class SufficiencyAuditError(ValueError):
    """Raised on configuration or contract failures during a sufficiency
    audit run (missing goal_type, missing/malformed contract, bad
    auditor response). Subclassing ValueError keeps it catchable as a
    plain ValueError for callers that don't want to import this module."""


# ──────────────────────────────  finding model  ──────────────────────────────


class SufficiencyFinding(BaseModel):
    """One pre-impl sufficiency finding emitted by the goal auditor.

    Severity validation reuses F0's ``_GOAL_GAP_SEVERITY_RANK`` so the
    sufficiency surface stays consistent with the goal-gap classifier
    that downstream features (F004 lock gate, F005 dogfood) consume.
    """

    model_config = ConfigDict(extra="forbid")

    severity: str = Field(..., min_length=1)
    journey_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the ObjectiveContract.user_journeys[*].name this finding targets.",
    )
    gap_class: GapClass = Field(
        ...,
        description="Top-level taxonomy: coverage_gap / missing_feature / wiring_gap / parity_gap / integration_gap.",
    )
    description: str = Field(
        ...,
        min_length=40,
        description="Substantive prose; stub-length descriptions are rejected at validation.",
    )
    feature_refs: list[str] = Field(
        default_factory=list,
        description=(
            "Feature IDs from the plan's features.json that relate to this gap. "
            "Empty when no current feature covers the gap (i.e., genuine missing-feature)."
        ),
    )
    recommendation: str | None = Field(
        default=None,
        description="Optional operator-facing remediation hint.",
    )

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _GOAL_GAP_SEVERITY_RANK:
            raise ValueError(f"unknown sufficiency severity: {value!r}")
        return normalized


# ──────────────────────────────  contract loading  ──────────────────────────────


def _read_frontmatter(plan_md: Path) -> dict[str, Any]:
    """Read YAML frontmatter from ``plan.md``. Mirrors
    :func:`plan_loader._frontmatter` deliberately — keeping a local copy
    keeps the sufficiency auditor independently importable without
    pulling the whole plan_loader surface into the F003 boundary."""
    if not plan_md.is_file():
        raise SufficiencyAuditError(f"plan.md not found at {plan_md}")
    text = plan_md.read_text()
    if not text.startswith("---"):
        raise SufficiencyAuditError(f"{plan_md}: missing frontmatter delimiter '---'")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SufficiencyAuditError(f"{plan_md}: malformed frontmatter")
    fm = yaml.safe_load(parts[1])
    if not isinstance(fm, dict):
        raise SufficiencyAuditError(f"{plan_md}: frontmatter is not a mapping")
    return fm


def _load_objective_contract(plan_dir: Path) -> ObjectiveContract:
    """Load + validate the ObjectiveContract referenced by a plan.

    Raises :class:`SufficiencyAuditError` with an actionable message on
    each failure mode: missing goal_type, missing links field, missing
    file on disk, or malformed contract contents.
    """
    plan_md = plan_dir / "plan.md"
    fm = _read_frontmatter(plan_md)

    goal_type = fm.get("goal_type")
    if goal_type is None:
        raise SufficiencyAuditError(
            f"{plan_md}: plan does not declare goal_type; sufficiency audit "
            "is only meaningful for goal_type ∈ {parity, new_feature, migration, incident}"
        )

    links = fm.get("links") or {}
    if not isinstance(links, dict):
        raise SufficiencyAuditError(
            f"{plan_md}: links must be a mapping, got {type(links).__name__}"
        )

    contract_ref = links.get("objective_contract")
    if not contract_ref:
        raise SufficiencyAuditError(
            f"{plan_md}: links.objective_contract is missing or empty; required by "
            f"goal_type={goal_type!r}"
        )

    contract_path = (plan_dir / contract_ref).resolve()
    if not contract_path.is_file():
        raise SufficiencyAuditError(
            f"{plan_md}: links.objective_contract points to {contract_ref!r}, "
            f"but the file does not exist at {contract_path}"
        )

    try:
        raw = json.loads(contract_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SufficiencyAuditError(
            f"{contract_path}: failed to read objective contract: {exc}"
        ) from exc

    try:
        return ObjectiveContract.model_validate(raw)
    except ValidationError as exc:
        raise SufficiencyAuditError(
            f"{contract_path}: objective contract failed schema validation: {exc.errors()}"
        ) from exc


# ──────────────────────────────  vendor resolution  ──────────────────────────────


def _is_truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_goal_auditor_agent(
    plan_dir: Path,
    implementer_agent: str | None = None,
) -> str:
    """Resolve the goal auditor agent for a plan, honoring D006's
    cross-vendor invariant.

    Resolution path:

    1. Resolve project context for ``plan_dir`` via
       :func:`project_config.find_project_for_plan_dir`. ``None`` when
       the plan lives outside any registered project — falls through
       to host-local defaults.
    2. Call :func:`project_config.resolve_dispatch_defaults` to walk the
       D004 precedence (project config → global config → hardcoded
       fallback claude/codex). Returns the canonical ``implementer`` and
       ``auditor`` strings.
    3. Override the resolved implementer with ``implementer_agent`` when
       the caller supplies one (lets a runtime override drive the
       cross-vendor check without mutating config).
    4. If ``effective_implementer == auditor`` (same-vendor), refuse
       unless :data:`_SAME_VENDOR_OVERRIDE_ENV` is set truthy in the
       environment. Same-vendor adversarial review is the antipattern
       Goal Governance V1 §5 explicitly bans by default.

    Returns the auditor agent name (e.g. ``'codex'``). Raises
    :class:`ValueError` (specifically :class:`SufficiencyAuditError`)
    when the cross-vendor invariant is violated without override.
    """
    project_match = project_config.find_project_for_plan_dir(plan_dir)
    project_path = project_match[0] if project_match is not None else None

    defaults = project_config.resolve_dispatch_defaults(project_path)
    auditor = defaults["auditor"]
    resolved_implementer = implementer_agent or defaults["implementer"]

    if not auditor:
        raise SufficiencyAuditError(
            "no goal auditor configured: project_config.resolve_dispatch_defaults "
            "returned empty 'auditor'"
        )

    if resolved_implementer == auditor and not _is_truthy_env(
        os.environ.get(_SAME_VENDOR_OVERRIDE_ENV)
    ):
        raise SufficiencyAuditError(
            "cross-vendor invariant (D006 / Goal Governance V1 §5) violated: "
            f"resolved auditor {auditor!r} equals implementer {resolved_implementer!r}. "
            f"Set {_SAME_VENDOR_OVERRIDE_ENV}=1 to override (and record the override "
            "in close-out evidence)."
        )

    return auditor


# ──────────────────────────────  prompt + response shaping  ──────────────────────────────


def _journey_acceptance_signals(journey: Any) -> list[str]:
    """Robust accessor: ``user_journey.acceptance_signals`` may be None
    on the model. Empty list keeps the prompt rendering clean."""
    return list(getattr(journey, "acceptance_signals", None) or [])


def _build_sufficiency_prompt(
    contract: ObjectiveContract,
    features: list[dict[str, Any]],
) -> str:
    """Compose the auditor prompt.

    The prompt is the load-bearing piece — it directs the auditor toward
    the gap classes that matter (Goal Governance V1 §3.1):

      * coverage matrix gaps — features cover only some user journeys;
      * missing-feature gaps — a journey has no feature pointing at it;
      * wiring gaps — features exist but acceptance criteria do not
        bind back to user-facing flows;
      * parity gaps — for parity goals, source-of-truth states the
        proposed features fail to reach;
      * integration gaps — features exist in isolation but compose
        incorrectly across surfaces.

    The auditor is instructed to emit a single JSON array of finding
    objects, one per gap, conforming to the
    :class:`SufficiencyFinding` shape.
    """
    sections: list[str] = []
    sections.append("# Pre-impl sufficiency audit")
    sections.append("")
    sections.append(
        "Walk the proposed features against the user-facing outcome described in "
        "the objective contract below. Surface gap-class findings the operator "
        "must resolve before the plan locks for implementation."
    )
    sections.append("")

    sections.append("## Objective contract")
    sections.append(f"- goal_type: {contract.goal_type.value}")
    sections.append(f"- source_of_truth: {contract.source_of_truth}")
    sections.append(f"- completion_test: {contract.completion_test}")
    if contract.non_goals:
        sections.append("- non_goals:")
        for ng in contract.non_goals:
            sections.append(f"  - {ng}")
    if contract.required_evidence:
        sections.append("- required_evidence (post-impl):")
        for ev in contract.required_evidence:
            sections.append(f"  - {ev}")
    sections.append("")

    sections.append("## User journeys")
    for journey in contract.user_journeys:
        sections.append(f"### {journey.name}")
        sections.append(journey.description)
        if journey.surfaces:
            sections.append(f"- surfaces: {', '.join(journey.surfaces)}")
        if journey.states:
            sections.append(f"- states: {', '.join(journey.states)}")
        signals = _journey_acceptance_signals(journey)
        if signals:
            sections.append("- acceptance_signals:")
            for sig in signals:
                sections.append(f"  - {sig}")
        sections.append("")

    sections.append("## Proposed features")
    if not features:
        sections.append("(no features declared yet)")
    else:
        for feat in features:
            fid = feat.get("id", "<missing id>")
            desc = feat.get("description", "").strip()
            sections.append(f"### {fid}")
            sections.append(desc or "(no description)")
            acceptance = feat.get("acceptance")
            if acceptance:
                sections.append(f"- acceptance: {acceptance}")
            steps = feat.get("steps") or []
            if steps:
                sections.append("- steps:")
                for step in steps:
                    sections.append(f"  - {step}")
            sections.append("")

    sections.append("## Gap classes to surface")
    sections.append("Use exactly one of these strings for each finding's `gap_class` field:")
    for gc in SUFFICIENCY_GAP_CLASSES:
        sections.append(f"- `{gc}`")
    sections.append("")
    sections.append("Severity must be one of: " + ", ".join(sorted(_GOAL_GAP_SEVERITY_RANK.keys())))
    sections.append("")

    sections.append("## Output contract")
    sections.append(
        "Reply with a SINGLE JSON array. Each element is a finding object with these fields:"
    )
    sections.append(
        "- `severity` (string, one of the allowed values)\n"
        "- `journey_id` (string, must match a `name` from the user_journeys above)\n"
        "- `gap_class` (string, one of the gap classes above)\n"
        "- `description` (string, ≥ 40 characters of substantive prose)\n"
        "- `feature_refs` (list of feature IDs that relate; empty for missing-feature gaps)\n"
        "- `recommendation` (optional string; null when not applicable)\n"
    )
    sections.append(
        "Return an empty JSON array `[]` if you find no gaps. Do NOT wrap the "
        "array in any object, prose, or fenced markdown — emit raw JSON only."
    )

    return "\n".join(sections)


def _strip_code_fence(text: str) -> str:
    """Tolerate ```json ... ``` fenced output. The prompt asks for raw
    JSON, but auditors often wrap it; stripping is forgiving without
    being permissive about content."""
    stripped = text.strip()
    if stripped.startswith("```"):
        # drop opening fence (with optional language tag) + closing fence
        first_newline = stripped.find("\n")
        if first_newline != -1:
            inner = stripped[first_newline + 1 :]
            if inner.endswith("```"):
                inner = inner[: -len("```")]
            return inner.strip()
    return stripped


def _parse_sufficiency_response(response: str) -> list[SufficiencyFinding]:
    """Parse the auditor's JSON output into validated findings.

    Raises :class:`SufficiencyAuditError` on:

      * non-JSON response;
      * top-level value that is not an array;
      * any element that fails :class:`SufficiencyFinding` validation
        (severity below the audit envelope enum, unknown gap_class,
        too-short description, etc.).
    """
    cleaned = _strip_code_fence(response)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise SufficiencyAuditError(
            f"sufficiency auditor response is not valid JSON: {exc.msg}"
        ) from exc

    if not isinstance(payload, list):
        raise SufficiencyAuditError(
            f"sufficiency auditor response must be a JSON array, got {type(payload).__name__}"
        )

    findings: list[SufficiencyFinding] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise SufficiencyAuditError(
                f"sufficiency response element [{index}] must be an object, "
                f"got {type(item).__name__}"
            )
        try:
            findings.append(SufficiencyFinding.model_validate(item))
        except ValidationError as exc:
            raise SufficiencyAuditError(
                f"sufficiency response element [{index}] failed validation: {exc.errors()}"
            ) from exc
    return findings


# ──────────────────────────────  entry point  ──────────────────────────────


DispatchFn = Callable[[str, str], str]
"""Callable type for the auditor dispatch seam.

Signature: ``dispatch(agent_name, prompt) -> response_text``.

F003 doesn't ship a default real-dispatch implementation: the public
:func:`run_sufficiency_audit` accepts the seam so tests can inject a
synthetic auditor. F004 (or a follow-up) wires the production path
when the lock gate begins consuming sufficiency findings."""


def _load_features(plan_dir: Path) -> list[dict[str, Any]]:
    features_json = plan_dir / "features.json"
    if not features_json.is_file():
        raise SufficiencyAuditError(f"features.json not found at {features_json}")
    try:
        raw = json.loads(features_json.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SufficiencyAuditError(f"{features_json}: failed to read: {exc}") from exc
    items = raw.get("features") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise SufficiencyAuditError(
            f"{features_json}: expected top-level mapping with 'features' list"
        )
    return items


def run_sufficiency_audit(
    plan_dir: Path,
    *,
    implementer_agent: str | None = None,
    dispatch: DispatchFn | None = None,
) -> list[SufficiencyFinding]:
    """Run a pre-impl sufficiency audit on ``plan_dir``.

    Loads the objective contract + features, resolves the goal auditor
    via project_config (D006 cross-vendor invariant enforced), builds
    the prompt, dispatches the auditor through ``dispatch`` (or raises
    if no dispatcher is wired), parses the response, persists the
    findings under ``evidence/goal-governance/pre_impl/`` per F0's
    convention, and returns the finding list.

    Pure text-only — no MCP, no runtime evidence. Lock enforcement is
    F004's job.
    """
    plan_dir = Path(plan_dir).resolve()
    if not plan_dir.is_dir():
        raise SufficiencyAuditError(f"plan_dir does not exist: {plan_dir}")

    contract = _load_objective_contract(plan_dir)
    features = _load_features(plan_dir)
    auditor = _resolve_goal_auditor_agent(plan_dir, implementer_agent=implementer_agent)
    prompt = _build_sufficiency_prompt(contract, features)

    if dispatch is None:
        raise SufficiencyAuditError(
            "no dispatch function provided; F003 leaves production wiring to "
            "F004's lock gate. Pass `dispatch=<callable>` to drive a real auditor."
        )

    response = dispatch(auditor, prompt)
    findings = _parse_sufficiency_response(response)

    out_path = goal_governance_evidence_path(plan_dir, "pre_impl", PRE_IMPL_FINDINGS_ARTIFACT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "auditor": auditor,
                "implementer": implementer_agent,
                "findings": [f.model_dump() for f in findings],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    return findings


__all__ = [
    "DispatchFn",
    "GapClass",
    "PRE_IMPL_FINDINGS_ARTIFACT",
    "SUFFICIENCY_GAP_CLASSES",
    "SufficiencyAuditError",
    "SufficiencyFinding",
    "run_sufficiency_audit",
]
