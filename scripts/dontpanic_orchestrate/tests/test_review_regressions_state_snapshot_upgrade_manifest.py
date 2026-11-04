"""Regression tests for state snapshots and upgrade release manifests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
SCRIPT_ROOT = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from dontpanic_orchestrate import state_projection  # noqa: E402
from dontpanic_orchestrate.release_manifest import (  # noqa: E402
    ReleaseManifestValidationError,
    load_release_manifest,
)
from dontpanic_orchestrate.upgrade_releases_model import (  # noqa: E402
    UpgradeManifest,
    UpgradeRelease,
)
from dontpanic_orchestrate.agent_conventions.schemas.v1_0.models.state_snapshot_model import (  # noqa: E402
    PlanSummary,
)


STATE_SCHEMA_SOURCE = (
    REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0" / "state-snapshot.schema.json"
)
STATE_SCHEMA_PACKAGED = (
    SCRIPT_ROOT
    / "dontpanic_orchestrate"
    / "agent_conventions"
    / "schemas"
    / "v1_0"
    / "state-snapshot.schema.json"
)

MIGRATION_PLAN_ID = "2026-05-19-001-migration-move-store"


def _plan_summary() -> dict[str, object]:
    return {
        "plan_id": MIGRATION_PLAN_ID,
        "status": "active",
        "title": "Move store",
        "type": "migration",
    }


def _write_migration_plan(plans_root: Path) -> None:
    """Write a minimal plan using the layout consumed by state_projection."""
    plan_dir = plans_root / MIGRATION_PLAN_ID
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        f"id: {MIGRATION_PLAN_ID}\n"
        "title: Move store\n"
        "type: migration\n"
        "tier: local\n"
        "status: active\n"
        'date: "2026-05-19"\n'
        "goal_type: infra\n"
        "surfaces:\n"
        "  - infra\n"
        "agents_required: []\n"
        "human_gates: []\n"
        "loop_caps:\n"
        "  max_iterations: 3\n"
        "  no_progress_threshold: 2\n"
        "  wall_clock_hours: 4\n"
        "  hard_stop: false\n"
        "privacy_tier: internal\n"
        "links:\n"
        "  features: ./features.json\n"
        "  decisions: ./decisions.jsonl\n"
        "  evidence_dir: ./evidence/\n"
        "description: A bounded migration fixture.\n"
        "---\n\n"
        "# Move store\n\n"
        "## Target\n\n"
        "```yaml\n"
        "target_env: dev\n"
        "target_project: none\n"
        "```\n"
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": MIGRATION_PLAN_ID,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "infra",
                        "phase": 1,
                        "description": "Move the store.",
                        "steps": ["Move the store."],
                        "acceptance": "The store is moved.",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            }
        )
    )
    (plan_dir / "evidence").mkdir()


def _valid_release(**overrides: object) -> dict[str, object]:
    release: dict[str, object] = {
        "id": "2026-08-15-release",
        "date": "2026-08-15",
        "summary": "A test release.",
        "actions": [],
    }
    release.update(overrides)
    return release


def _valid_manifest(*, baseline_date: str = "2026-08-01", release: dict | None = None) -> dict:
    return {
        "baseline_release": "2026-08-01-baseline",
        "baseline_date": baseline_date,
        "releases": [release or _valid_release()],
    }


def test_plan_summary_accepts_migration_plan_id_and_type() -> None:
    summary = PlanSummary.model_validate(_plan_summary())

    assert summary.plan_id == MIGRATION_PLAN_ID
    assert summary.type.value == "migration"


@pytest.mark.parametrize("schema_path", [STATE_SCHEMA_SOURCE, STATE_SCHEMA_PACKAGED])
def test_state_snapshot_plan_summary_schema_accepts_migration(schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text())

    jsonschema.validate(
        instance=_plan_summary(),
        schema=schema["$defs"]["plan_summary"],
    )


def test_gather_projects_a_migration_plan(tmp_path: Path) -> None:
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    _write_migration_plan(plans_root)

    snapshot = state_projection.gather(plans_root, include=("plans",))

    assert [plan.plan_id for plan in snapshot.streams.plans] == [MIGRATION_PLAN_ID]
    assert snapshot.streams.plans[0].type.value == "migration"


def test_upgrade_release_rejects_basic_form_date() -> None:
    with pytest.raises(ValidationError):
        UpgradeRelease.model_validate(_valid_release(date="20260815"))


def test_upgrade_manifest_rejects_basic_form_baseline_date() -> None:
    with pytest.raises(ValidationError):
        UpgradeManifest.model_validate(_valid_manifest(baseline_date="20260815"))


def test_upgrade_release_accepts_iso_date_and_rejects_invalid_calendar_date() -> None:
    assert UpgradeRelease.model_validate(_valid_release(date="2026-08-15")).date == "2026-08-15"

    with pytest.raises(ValidationError):
        UpgradeRelease.model_validate(_valid_release(date="2026-02-30"))


def test_upgrade_manifest_accepts_iso_baseline_and_rejects_invalid_calendar_date() -> None:
    assert (
        UpgradeManifest.model_validate(
            _valid_manifest(baseline_date="2026-08-15")
        ).baseline_date
        == "2026-08-15"
    )

    with pytest.raises(ValidationError):
        UpgradeManifest.model_validate(_valid_manifest(baseline_date="2026-02-30"))


def test_upgrade_release_requires_actions_key() -> None:
    release = _valid_release()
    del release["actions"]

    with pytest.raises(ValidationError):
        UpgradeRelease.model_validate(release)


def test_manifest_loader_requires_release_actions_key(tmp_path: Path) -> None:
    release = _valid_release()
    del release["actions"]
    manifest_path = tmp_path / "releases.json"
    manifest_path.write_text(json.dumps(_valid_manifest(release=release)))

    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(manifest_path)


def test_upgrade_release_accepts_explicit_empty_actions() -> None:
    assert UpgradeRelease.model_validate(_valid_release()).actions == []
