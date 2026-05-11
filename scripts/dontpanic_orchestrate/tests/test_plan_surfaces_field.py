"""Plan 2026-05-08-002 F001 — `surfaces:` field on plan schema (v1.5.0).

Acceptance covered:
  (a) plan with valid `surfaces:` validates and the values surface on
      LoadedPlan as a list[str] in the canonical 10-value enum.
  (b) plan without `surfaces:` still validates (backward-compat); LoadedPlan
      exposes an empty list.
  (c) plan with an invalid surface value (not in the canonical enum) fails
      validation cleanly via Pydantic, NOT via a downstream KeyError.
  (d) agent-conventions VERSION file is at v1.7.0 — schema bump landed
      (additive: external-api-wrap surface for printing-press-adapter skill).

Run: PYTHONPATH=scripts pytest \\
       scripts/dontpanic_orchestrate/tests/test_plan_surfaces_field.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import plan_loader  # noqa: E402


def _make_plan_dir(
    tmp_path: Path,
    plan_id: str,
    *,
    surfaces_block: str = "",
) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    plan_md = f"""---
id: {plan_id}
title: surfaces field test plan
type: infra
tier: trivial
status: active
date: "2026-05-08"
description: Synthetic plan exercising the v1.5.0 surfaces field.
agents_required:
  - claude
human_gates:
  - pre_impl
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
{surfaces_block}links:
  features: ./features.json
---

# surfaces field test plan

## Target

```yaml
target_env: dev
target_project: none
```
"""
    (plan_dir / "plan.md").write_text(plan_md)
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001",
                "category": "test",
                "phase": 0,
                "description": "synthetic feature for surfaces tests",
                "steps": ["scripted single step"],
                "acceptance": "synthetic acceptance text for surfaces tests",
                "passes": False,
                "depends_on": [],
            }
        ],
    }
    (plan_dir / "features.json").write_text(json.dumps(features))
    return plan_dir


class TestSurfacesField:
    def test_plan_with_surfaces_validates_and_surfaces_on_loaded_plan(
        self, tmp_path: Path
    ):
        surfaces_block = "surfaces:\n  - infra\n  - security\n"
        plan_dir = _make_plan_dir(
            tmp_path,
            "2026-05-08-100-infra-surfaces-valid",
            surfaces_block=surfaces_block,
        )
        loaded = plan_loader.load(plan_dir)
        assert loaded.surfaces == ["infra", "security"]
        assert isinstance(loaded.surfaces, list)
        assert all(isinstance(s, str) for s in loaded.surfaces)

    def test_plan_without_surfaces_validates_with_empty_list(
        self, tmp_path: Path
    ):
        plan_dir = _make_plan_dir(
            tmp_path,
            "2026-05-08-101-infra-surfaces-absent",
            surfaces_block="",
        )
        loaded = plan_loader.load(plan_dir)
        assert loaded.surfaces == []
        assert isinstance(loaded.surfaces, list)

    def test_invalid_surface_value_fails_validation(self, tmp_path: Path):
        # 'cli' is intentionally NOT in the canonical 10-value enum (D002).
        # Validator should reject via Pydantic, not via a downstream KeyError.
        surfaces_block = "surfaces:\n  - infra\n  - cli\n"
        plan_dir = _make_plan_dir(
            tmp_path,
            "2026-05-08-102-infra-surfaces-invalid",
            surfaces_block=surfaces_block,
        )
        with pytest.raises(ValidationError):
            plan_loader.load(plan_dir)

    def test_agent_conventions_version_is_v1_7_0(self):
        version_file = (
            plan_loader.SCHEMAS_DIR.parent.parent / "VERSION"
        )
        assert version_file.is_file(), (
            f"VERSION file not found at {version_file}; "
            "schemas dir should sit one level under <root>/schemas/v1.0/"
        )
        version_text = version_file.read_text().strip()
        assert version_text == "1.7.0", (
            f"agent-conventions VERSION is {version_text!r}; "
            "expected '1.7.0' per plan 2026-05-10-001 F002 "
            "(external-api-wrap surface added)"
        )

    def test_external_api_wrap_in_surfaces_enum(self):
        schema_path = plan_loader.SCHEMAS_DIR / "plan.schema.json"
        schema = json.loads(schema_path.read_text())
        surfaces_enum = schema["properties"]["surfaces"]["items"]["enum"]
        assert "external-api-wrap" in surfaces_enum, (
            f"surfaces enum missing 'external-api-wrap'; got {surfaces_enum!r}. "
            "Required by plan 2026-05-10-001 F002 (printing-press-adapter skill)."
        )
        # The other 10 canonical surfaces stay unchanged (additive bump).
        expected_base = {
            "web", "ios", "android", "backend", "infra",
            "security", "data", "ux", "ml", "docs",
        }
        assert expected_base.issubset(set(surfaces_enum)), (
            f"surfaces enum lost one of the base 10 entries; got {surfaces_enum!r}"
        )

    def test_plan_with_external_api_wrap_surface_validates(
        self, tmp_path: Path
    ):
        surfaces_block = "surfaces:\n  - external-api-wrap\n  - backend\n"
        plan_dir = _make_plan_dir(
            tmp_path,
            "2026-05-10-103-infra-surfaces-extapi",
            surfaces_block=surfaces_block,
        )
        loaded = plan_loader.load(plan_dir)
        assert loaded.surfaces == ["external-api-wrap", "backend"]
