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


@dataclass
class LoadedPlan:
    plan_dir: Path
    plan_id: str
    plan: Plan
    features: Features
    schemas_dir: Path

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

    plan = Plan.model_validate(_frontmatter(plan_md))
    features = Features.model_validate(json.loads(features_json.read_text()))

    if features.task_id != plan.id:
        raise ValueError(
            f"task_id {features.task_id!r} != plan id {plan.id!r}"
        )

    return LoadedPlan(
        plan_dir=plan_dir,
        plan_id=plan.id,
        plan=plan,
        features=features,
        schemas_dir=SCHEMAS_DIR,
    )
