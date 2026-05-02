"""Plan 2026-05-02-003 F001 — parent/child metadata + depth/cycle/repeated-finding guards.

Loads optional `orchestration` blocks from plan.md frontmatter into
structured Pydantic models, computes parent-chain depth, and refuses
dispatch when (a) depth exceeds the platform cap (default 3, CLI-only
override per D002), (b) the chain forms a cycle by `plan_id`, or (c)
the current plan's spawn-finding signature collides with any parent's
recorded signature (D001).

Anti-recursion thesis: a child plan is bounded work tied to a named
parent finding/objective. depth + cycle + signature guards together
make unbounded chains "fixing the same thing" impossible.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_DEPTH_LIMIT: int = 3
"""The platform cap on parent-chain depth (D002). Frontmatter may declare a
LOWER value than this to tighten a single plan's allowed nesting; CLI's
`--allow-depth N` is the only mechanism for raising the cap at dispatch."""


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


__all__ = [
    "DEFAULT_DEPTH_LIMIT",
    "NestedOrchestrationError",
    "Orchestration",
    "SpawnFinding",
    "SpawnReason",
    "check_cycle",
    "check_depth",
    "check_repeated_finding",
    "compute_depth",
    "compute_finding_signature",
    "walk_parent_chain",
]
