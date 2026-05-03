"""Load + validate a plan directory against agent-conventions v1.0 schemas."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
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
from models.plan_model import Plan  # noqa: E402

from jarvis_orchestrate.nested_orchestration import (  # noqa: E402
    ChildCharter,
    CommitPolicy,
    Orchestration,
    validate_charter_policy_consistency,
)
from jarvis_orchestrate.plan_target import (  # noqa: E402
    normalize_target_project,
    parse_target_section,
    validate_prod_gates,
)


def _registry_required_gates(plan_dir: Path, target_env: str) -> list[str] | None:
    """F023 Expansion B: pull requires_gates[] from environments.json for the
    declared tier when present. Returns None if no registry / no tier / no
    requires_gates declared, leaving validate_prod_gates on its hardcoded path.
    """
    # Imported here to avoid a circular dependency at module load.
    from jarvis_orchestrate.environments_loader import (
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

    def feature(self, feature_id: str) -> dict[str, Any]:
        for f in self.features.features:
            if f.id == feature_id:
                return f.model_dump()
        raise KeyError(f"feature {feature_id!r} not in {self.plan_id}")


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text()
    if not text.startswith("---"):
        raise ValueError(f"{path}: missing frontmatter delimiter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path}: malformed frontmatter")
    return yaml.safe_load(parts[1])


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
    commit_policy = (
        CommitPolicy.model_validate(policy_block) if policy_block is not None else None
    )

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

    features = Features.model_validate(json.loads(features_json.read_text()))

    if features.task_id != plan.id:
        raise ValueError(f"task_id {features.task_id!r} != plan id {plan.id!r}")

    target = parse_target_section(plan_md_text)
    required_override = _registry_required_gates(plan_dir, target["target_env"])
    validate_prod_gates(
        target["target_env"],
        plan.human_gates or [],
        required_override=required_override,
    )

    return LoadedPlan(
        plan_dir=plan_dir,
        plan_id=plan.id,
        plan=plan,
        features=features,
        schemas_dir=SCHEMAS_DIR,
        target_env=target["target_env"],
        target_project=normalize_target_project(target["target_project"]),
        orchestration=orchestration,
        child_charter=child_charter,
        commit_policy=commit_policy,
    )
