"""Load + validate a plan directory against agent-conventions v1.0 schemas."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Discover schemas. Priority order from plan-artifacts SKILL.md.
_SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[2] / ".claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[3] / "agent-conventions" / "schemas" / "v1.0",
]


def _find_schemas_dir() -> Path:
    for c in _SCHEMA_CANDIDATES:
        if (c / "models").is_dir():
            sys.path.insert(0, str(c))
            return c
    raise FileNotFoundError(
        "agent-conventions v1.0 schemas not found. Tried: "
        + ", ".join(str(c) for c in _SCHEMA_CANDIDATES)
    )


SCHEMAS_DIR = _find_schemas_dir()
from models.features_model import Features  # noqa: E402
from models.plan_model import ExternalRef, Plan  # noqa: E402

from dontpanic_orchestrate.integrations.pm_tool_sync import (  # noqa: E402
    ExternalSyncRecord,
    ExternalSyncStatus,
)
from dontpanic_orchestrate.nested_orchestration import (  # noqa: E402
    ChildCharter,
    CommitPolicy,
    Orchestration,
    validate_charter_policy_consistency,
)
from dontpanic_orchestrate.plan_target import (  # noqa: E402
    normalize_target_project,
    parse_target_section,
    validate_prod_gates,
)

__all__ = [
    "ExternalRef",
    "ExternalSyncRecord",
    "ExternalSyncStatus",
    "Features",
    "LoadedPlan",
    "Plan",
    "load",
]


def _registry_required_gates(plan_dir: Path, target_env: str) -> list[str] | None:
    """F023 Expansion B: pull requires_gates[] from environments.json for the
    declared tier when present. Returns None if no registry / no tier / no
    requires_gates declared, leaving validate_prod_gates on its hardcoded path.
    """
    # Imported here to avoid a circular dependency at module load.
    from dontpanic_orchestrate.environments_loader import (
        EnvironmentsError,
        find_repo_root_for_plan,
        load_environments,
    )

    repo_root = find_repo_root_for_plan(plan_dir)
    if repo_root is None:
        return None
    try:
        env = load_environments(repo_root)
    except EnvironmentsError:
        return None
    block = getattr(env, target_env, None)
    if block is None:
        return None
    if not block.requires_gates:
        return None
    return list(block.requires_gates)


@dataclass
class LoadedPlan:
    plan_dir: Path
    plan_id: str
    plan: Plan
    features: Features
    schemas_dir: Path
    target_env: str = "dev"
    target_project: str | None = None
    # Plan 2026-05-08-002 F001: surfaces this plan declares it touches.
    # Always a list (empty when plan omits the optional `surfaces:` field);
    # consumers iterate without None-checking. Values are the canonical
    # 10-value enum from agent-conventions v1.5.0 plan.schema.json.
    surfaces: list[str] = field(default_factory=list)
    # Plan 2026-05-02-003 F001: optional `orchestration` block (parent/child
    # metadata). None for top-level plans; populated for child plans that
    # declare an `orchestration:` frontmatter section.
    orchestration: Orchestration | None = None
    # Plan 2026-05-02-003 F002: optional `child_charter` + `commit_policy`
    # blocks. Only valid when `orchestration.parent_plan_id` is set; loader
    # rejects charter on a top-level plan. When charter is present and
    # commit_policy is absent, loader synthesizes the default
    # `CommitPolicy(mode='evidence_only', requires=[])` per D003.
    child_charter: ChildCharter | None = None
    commit_policy: CommitPolicy | None = None
    # Plan 2026-05-20-001 F002: optional `external_refs[]` — opt-in
    # pointers to external entities (PM-tool issues, etc.) that the plan
    # lifecycle hooks consult. Empty list when absent so consumers can
    # iterate without None-checking.
    external_refs: list[ExternalRef] = field(default_factory=list)

    def feature(self, feature_id: str) -> dict[str, Any]:
        for f in self.features.features:
            if f.id == feature_id:
                return f.model_dump()
        raise KeyError(f"feature {feature_id!r} not in {self.plan_id}")


# Plan 2026-05-09-002 F002 — post-reconcile sync trigger.
#
# The agent-conventions v1.0 plan.status enum is
# {draft / active / ready_for_audit / in_audit / completed / abandoned /
# blocked}. Only ``active`` signals "lock complete, ready for implementer
# dispatch" (D004 of plan 2026-05-09-002). Post-implementation states
# (ready_for_audit, in_audit, completed) and abnormal terminals
# (abandoned, blocked) MUST NOT trigger implicit ``pre_impl`` clearance —
# a completed plan should not be re-dispatchable through this seam.

_IMPLICIT_PRE_IMPL_STATUSES: frozenset[str] = frozenset({"active"})


def plan_status_enables_implicit_pre_impl(loaded: LoadedPlan) -> bool:
    """Plan 2026-05-09-002 F002 — return True iff ``loaded.plan.status`` is
    exactly ``active``. Pure read of the LoadedPlan; no IO.

    ``active`` is the single status value where the operator has
    explicitly locked the plan as ready for implementer dispatch and
    expects the lock D-entry + status flip to be load-bearing — i.e.
    they should NOT have to additionally run ``dontpanic approve <plan>
    pre_impl`` to make dispatch proceed. Every other status value
    (draft / ready_for_audit / in_audit / completed / abandoned /
    blocked) returns False, preserving the existing manual approve/
    resume contract.
    """
    status = getattr(loaded.plan, "status", None)
    if status is None:
        return False
    # Status is a Pydantic enum from agent-conventions; the .value carries
    # the canonical string. Tolerate either enum or plain string in case a
    # future loader pathway delivers it as a literal.
    value = status.value if hasattr(status, "value") else str(status)
    return value in _IMPLICIT_PRE_IMPL_STATUSES


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text()
    if not text.startswith("---"):
        raise ValueError(f"{path}: missing frontmatter delimiter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path}: malformed frontmatter")
    return yaml.safe_load(parts[1])


def resolve_plan_dir(
    plan_arg: str,
    *,
    project_path: Path | None = None,
    plans_dir: str = "docs/plans",
) -> Path | None:
    """Resolve a plan ID (or absolute path) to a plan directory.

    Resolution order:
      1. If ``plan_arg`` is itself an existing directory, use it directly.
      2. If ``project_path`` is set, look under
         ``<project_path>/<plans_dir>/<plan_arg>/``.
      3. Else look under ``<cwd>/<plans_dir>/<plan_arg>/`` (the
         backward-compatible behavior every existing caller depends on).

    The ``plans_dir`` argument is the project-relative override threaded
    in by F003: when a per-project ``.dontpanic/dontpanic.json`` sets
    ``plans_dir``, callers pass that string here. Default matches the
    convention every shipped plan uses.

    Returns the resolved Path on success; ``None`` when no candidate
    exists. Callers (CLI) translate ``None`` into a hard exit-2 refusal —
    there is intentionally no silent ``Path.cwd()`` fallback baked in here.
    """
    direct = Path(plan_arg)
    if direct.is_dir():
        return direct.resolve()
    if project_path is not None:
        candidate = (project_path / plans_dir / plan_arg).resolve()
        if candidate.is_dir():
            return candidate
    cwd_match = (Path.cwd() / plans_dir / plan_arg).resolve()
    if cwd_match.is_dir():
        return cwd_match
    return None


def _normalize_features_payload(payload: dict) -> dict:
    """Loosen ``verified_by`` at the load boundary.

    The canonical (codegen'd) ``Features`` model declares ``verified_by`` as a
    list, but the operator convention writes it as a bare string (one verifier).
    Both ``plan_loader`` and ``state export-dashboard`` route through here, so we
    coerce a string to a single-element list before strict validation rather than
    hand-editing the generated subtree model or every plan's committed data.
    """
    for feature in payload.get("features") or []:
        if isinstance(feature, dict) and isinstance(feature.get("verified_by"), str):
            feature["verified_by"] = [feature["verified_by"]]
    return payload


def load(plan_dir: Path) -> LoadedPlan:
    plan_dir = plan_dir.resolve()
    if not plan_dir.is_dir():
        raise FileNotFoundError(plan_dir)

    plan_md = plan_dir / "plan.md"
    features_json = plan_dir / "features.json"
    if not plan_md.is_file():
        raise FileNotFoundError(plan_md)
    if not features_json.is_file():
        raise FileNotFoundError(features_json)

    plan_md_text = plan_md.read_text()
    fm = _frontmatter(plan_md)
    # Plan 2026-05-02-003 F001 + F002: pop the optional nested-orchestration
    # blocks before Plan.model_validate (which has extra='forbid' and would
    # reject them). The blocks live on LoadedPlan as separate parser-level
    # concerns; canonical Plan model in agent-conventions/schemas is unchanged
    # (D006-style schema discipline — no schema bump required for nested
    # orchestration v1).
    orch_block = fm.pop("orchestration", None)
    charter_block = fm.pop("child_charter", None)
    policy_block = fm.pop("commit_policy", None)
    plan = Plan.model_validate(fm)
    orchestration = Orchestration.model_validate(orch_block) if orch_block is not None else None
    child_charter = (
        ChildCharter.model_validate(charter_block) if charter_block is not None else None
    )
    commit_policy = CommitPolicy.model_validate(policy_block) if policy_block is not None else None

    # Plan 2026-05-02-003 F002 cross-validation:
    # (a) child_charter is only valid on a child plan (orchestration set).
    # (b) charter present + commit_policy absent → synthesize default per D003.
    # (c) charter + policy must agree on may_edit_product_code vs mode (D003).
    if child_charter is not None:
        if orchestration is None or not orchestration.parent_plan_id:
            raise ValueError(
                f"{plan_md}: child_charter requires orchestration.parent_plan_id; "
                "child_charter is only valid on child plans"
            )
        if commit_policy is None:
            commit_policy = CommitPolicy()  # default: mode='evidence_only', requires=[]
        validate_charter_policy_consistency(child_charter, commit_policy)

    features = Features.model_validate(
        _normalize_features_payload(json.loads(features_json.read_text()))
    )

    if features.task_id != plan.id:
        raise ValueError(f"task_id {features.task_id!r} != plan id {plan.id!r}")

    target = parse_target_section(plan_md_text)
    required_override = _registry_required_gates(plan_dir, target["target_env"])
    validate_prod_gates(
        target["target_env"],
        plan.human_gates or [],
        required_override=required_override,
    )

    surfaces_list: list[str] = [s.value for s in plan.surfaces] if plan.surfaces else []

    return LoadedPlan(
        plan_dir=plan_dir,
        plan_id=plan.id,
        plan=plan,
        features=features,
        schemas_dir=SCHEMAS_DIR,
        target_env=target["target_env"],
        target_project=normalize_target_project(target["target_project"]),
        surfaces=surfaces_list,
        orchestration=orchestration,
        child_charter=child_charter,
        commit_policy=commit_policy,
        external_refs=list(plan.external_refs or []),
    )
