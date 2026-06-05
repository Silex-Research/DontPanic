"""Plan 2026-06-04-004 F005 — render-truth invariant.

The analogue of 001's round-trip invariant, for STATE/RENDER truth: every label
or count the dashboard publishes must equal the source it claims.

  * Live Now      == len(supervisors)
  * Active Plans  == count(plans where status==active)
  * attribution.live_count == activity.live_now
  * every section's source == its real provenance (no legacy adapter cited)
  * a stale legacy tasks/agents/activity.json in the export dir CANNOT override
    the canonical projection.

A divergent label/count fails this test. Runs in the orchestrate sweep.
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import state_cli, state_projection


def _write_plan(plans_root: Path, plan_id: str, status: str) -> None:
    d = plans_root / plan_id
    d.mkdir(parents=True)
    (d / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F005 render-truth synthetic
type: infra
tier: trivial
status: {status}
date: "2026-06-04"
description: Synthetic plan for the F005 render-truth invariant test.
agents_required:
  - claude
human_gates: []
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---
# b
## Target
```yaml
target_env: dev
target_project: none
```
""",
        encoding="utf-8",
    )
    (d / "features.json").write_text(
        '{"task_id": "%s", "schema_version": "1.0", "features": ['
        '{"id": "F001", "category": "test", "phase": 0,'
        ' "description": "synthetic feature long enough", "steps": ["s"],'
        ' "acceptance": "ok and verified", "passes": false, "depends_on": []}]}\n'
        % plan_id,
        encoding="utf-8",
    )


def _export(tmp_path: Path) -> tuple[dict, Path]:
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    _write_plan(plans_root, "2026-06-04-920-infra-a", "active")
    _write_plan(plans_root, "2026-06-04-921-infra-b", "active")
    _write_plan(plans_root, "2026-06-04-922-infra-c", "active")
    _write_plan(plans_root, "2026-06-04-923-infra-d", "completed")
    out_dir = tmp_path / "state"
    assert (
        state_cli._export_dashboard_main(
            ["--out", str(out_dir), "--plans-root", str(plans_root)]
        )
        == 0
    )
    return json.loads((out_dir / "manifest.json").read_text()), out_dir


def test_active_plans_count_equals_status_active_in_source(tmp_path):
    manifest, out_dir = _export(tmp_path)
    plans = json.loads((out_dir / "plans.json").read_text())
    status_active = sum(1 for p in plans if p.get("status") == "active")
    assert manifest["activity"]["active_plans"] == status_active == 3


def test_live_now_equals_supervisors_length_in_source(tmp_path):
    manifest, out_dir = _export(tmp_path)
    supervisors = json.loads((out_dir / "supervisors.json").read_text())
    assert manifest["activity"]["live_now"] == len(supervisors)


def test_attribution_live_count_equals_activity_live_now(tmp_path):
    manifest, _ = _export(tmp_path)
    assert manifest["attribution"]["live_count"] == manifest["activity"]["live_now"]


def test_every_section_source_equals_its_provenance(tmp_path):
    manifest, _ = _export(tmp_path)
    for entry in manifest["streams"]:
        assert entry["source"] == state_projection.STREAM_PROVENANCE[entry["name"]]
    # and no legacy adapter is cited anywhere in the rendered envelope
    blob = json.dumps(manifest)
    for legacy in state_projection.LEGACY_SOURCES:
        assert legacy not in blob


def test_stale_legacy_files_cannot_override_canonical_projection(tmp_path):
    # Plant stale legacy adapters in the export dir, then re-export. The
    # canonical projection must ignore them: counts unchanged, no citation.
    manifest_before, out_dir = _export(tmp_path)
    for legacy in state_projection.LEGACY_SOURCES:
        (out_dir / legacy).write_text(
            json.dumps({"running": 999, "agents": ["ghost"]}), encoding="utf-8"
        )
    # Re-run the export against the same plans_root.
    plans_root = tmp_path / "plans"
    assert (
        state_cli._export_dashboard_main(
            ["--out", str(out_dir), "--plans-root", str(plans_root)]
        )
        == 0
    )
    manifest_after = json.loads((out_dir / "manifest.json").read_text())
    # Canonical counts are derived from plans/supervisors — never the legacy files.
    assert manifest_after["activity"]["active_plans"] == 3
    assert manifest_after["activity"]["live_now"] == 0
    assert manifest_after["activity"] == manifest_before["activity"]
    blob = json.dumps(manifest_after)
    for legacy in state_projection.LEGACY_SOURCES:
        assert legacy not in blob  # the stale file's name is never cited
