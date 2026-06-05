"""Plan 2026-06-04-004 F002 — lifecycle vs activity as separate axes.

`active_plans` (plans with status==active) and `live_now` (active supervisors)
come from DISTINCT sources; with zero live supervisors nothing claims live
execution. The old "Running N" conflation is gone.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from dontpanic_orchestrate import state_cli, state_projection


# ── pure function: counts pinned to distinct sources ──────────────────────────
@dataclasses.dataclass
class _Plan:
    status: str


@dataclasses.dataclass
class _Streams:
    plans: list
    supervisors: list


@dataclasses.dataclass
class _Snap:
    streams: _Streams


def test_active_plans_counts_only_status_active():
    snap = _Snap(
        _Streams(
            plans=[_Plan("active"), _Plan("active"), _Plan("completed"), _Plan("draft")],
            supervisors=[],
        )
    )
    summary = state_projection.activity_summary(snap)
    assert summary["active_plans"] == 2
    assert summary["active_plans_source"] == state_projection.STREAM_PROVENANCE["plans"]


def test_live_now_counts_supervisors_from_distinct_source():
    snap = _Snap(_Streams(plans=[_Plan("active")], supervisors=[object(), object()]))
    summary = state_projection.activity_summary(snap)
    assert summary["live_now"] == 2
    assert summary["live_now_source"] == state_projection.STREAM_PROVENANCE["supervisors"]
    # The two axes are sourced differently — never the same file.
    assert summary["active_plans_source"] != summary["live_now_source"]
    assert summary["claims_live_execution"] is True


def test_zero_supervisors_claims_no_live_execution_even_with_active_plans():
    snap = _Snap(_Streams(plans=[_Plan("active"), _Plan("active")], supervisors=[]))
    summary = state_projection.activity_summary(snap)
    assert summary["active_plans"] == 2  # plans are active…
    assert summary["live_now"] == 0  # …but nothing is live
    assert summary["claims_live_execution"] is False


# ── integration: the exported manifest carries the activity block ─────────────
def _write_plan(plans_root: Path, plan_id: str, status: str) -> None:
    d = plans_root / plan_id
    d.mkdir(parents=True)
    (d / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F002 activity synthetic
type: infra
tier: trivial
status: {status}
date: "2026-06-04"
description: Synthetic plan for F002 activity-axes integration test.
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


def test_manifest_activity_pins_active_plans_to_status(tmp_path):
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    _write_plan(plans_root, "2026-06-04-910-infra-a", "active")
    _write_plan(plans_root, "2026-06-04-911-infra-b", "active")
    _write_plan(plans_root, "2026-06-04-912-infra-c", "completed")
    out_dir = tmp_path / "state"
    assert (
        state_cli._export_dashboard_main(
            ["--out", str(out_dir), "--plans-root", str(plans_root)]
        )
        == 0
    )
    manifest = json.loads((out_dir / "manifest.json").read_text())
    activity = manifest["activity"]
    assert activity["active_plans"] == 2  # only the two status==active plans
    # No live supervisors in the isolated test home -> no live-execution claim.
    assert activity["live_now"] == 0
    assert activity["claims_live_execution"] is False
