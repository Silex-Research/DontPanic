"""Plan 2026-05-23-007 F002 — tests for the parallel-readiness recommender.

Coverage matrix (the plan's acceptance #10 asks for ≥10 readiness cases):

  1. Independent features F001/F002 → both ready, max_parallel=2 emits 2 cmds.
  2. F002 depends_on F001 (F001 not passing) → F002 not ready.
  3. F001 passes → F002 becomes ready.
  4. Plan-frontmatter dependency on incomplete plan → plan-blocked reason.
  5. Plan-frontmatter dependency on completed plan → ready.
  6. Active-supervisor on same plan_id → collision warning, doesn't suppress.
  7. Active-supervisor on different plan with overlapping allowed_paths + step
     token → advisory collision warning.
  8. Active-supervisor on different plan WITHOUT overlap → no collision
     (precision bias / tolerated false negatives).
  9. Active breaker on plan → not ready + breaker warning.
 10. Malformed plan dir → load_error warning, scan continues.
 11. JSON envelope schema: required fields present + correct types.
 12. include_not_ready=False suppresses not_ready[].
 13. max_parallel caps candidate_commands but not ready[].
 14. The command writes zero files (acceptance #9 invariant).
 15. Fleet aggregation labels per-project + interleaves commands.
 16. Frontmatter dependency points at unknown plan id → not ready with
     "not in inventory" reason.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    active_supervisors,
    gate_pause,
    planning_readiness,
    projects_registry,
)


# ─────────────────────────  fixture helpers  ─────────────────────────


def _write_plan(
    plans_root: Path,
    plan_id: str,
    *,
    status: str = "active",
    dependencies: list[str] | None = None,
    features: list[dict] | None = None,
    gates: list[str] | None = None,
    allowed_paths: list[str] | None = None,
    parent_plan_id: str | None = None,
) -> Path:
    """Materialize a minimal valid plan dir for the readiness scanner."""
    plan_dir = plans_root / plan_id
    plan_dir.mkdir(parents=True)
    gates_yaml = "\n".join(f"  - {g}" for g in (gates or [])) if gates else "  []"
    deps_yaml = "\n".join(f"  - {d}" for d in (dependencies or [])) if dependencies else "  []"
    extras = ""
    if parent_plan_id:
        extras += (
            "orchestration:\n"
            f"  parent_plan_id: {parent_plan_id}\n"
            "  spawn_reason: operator_manual\n"
            "  depth_limit: 3\n"
        )
        extras += (
            "child_charter:\n"
            "  kind: implementation\n"
            "  parent_objective: synthetic\n"
            '  parent_acceptance_item: "synthetic"\n'
            "  allowed_paths:\n"
        )
        for p in allowed_paths or ["docs/synthetic/**"]:
            extras += f"    - \"{p}\"\n"
        extras += (
            "  forbidden_decisions:\n"
            "    - none\n"
            "  return_condition_summary: synthetic\n"
            "  may_edit_product_code: true\n"
            "commit_policy:\n"
            "  mode: child_commit\n"
            "  requires:\n"
            "    - tests_pass\n"
        )

    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: Synthetic plan {plan_id}
description: Synthetic readiness fixture.
type: infra
tier: trivial
status: {status}
date: "2026-05-23"
agents_required:
  - claude
  - codex
human_gates:
{gates_yaml}
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
dependencies:
{deps_yaml}
links:
  features: ./features.json
{extras}---

# Synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""
    )
    feats = features or [
        {
            "id": "F001",
            "category": "test",
            "phase": 0,
            "description": "synthetic feature one",
            "steps": ["scripted step"],
            "acceptance": "ok",
            "passes": False,
            "depends_on": [],
        }
    ]
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "schema_version": "1.0",
                "features": feats,
            },
            indent=2,
        )
        + "\n"
    )
    return plan_dir


def _feature(
    fid: str,
    *,
    passes: bool = False,
    depends_on: list[str] | None = None,
    steps: list[str] | None = None,
    description: str = "synthetic readiness fixture feature",
) -> dict:
    return {
        "id": fid,
        "category": "test",
        "phase": 0,
        "description": description,
        "steps": steps or ["scripted"],
        "acceptance": "ok",
        "passes": passes,
        "depends_on": depends_on or [],
    }


# ─────────────────────────────  tests  ─────────────────────────────


class TestIndependentFeatures:
    def test_two_independent_features_both_ready(self, tmp_path: Path) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-100-feat-two-indep",
            features=[_feature("F001"), _feature("F002")],
        )

        report = planning_readiness.analyze_repo(
            plans_root,
            max_parallel=2,
            active_entries=[],
        )
        ready_ids = {(r.plan_id, r.feature_id) for r in report.ready}
        assert ("2026-05-23-100-feat-two-indep", "F001") in ready_ids
        assert ("2026-05-23-100-feat-two-indep", "F002") in ready_ids
        assert len(report.candidate_commands) == 2


class TestFeatureDependencies:
    def test_unmet_feature_dependency_blocks(self, tmp_path: Path) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-101-feat-seq",
            features=[
                _feature("F001"),
                _feature("F002", depends_on=["F001"]),
            ],
        )
        report = planning_readiness.analyze_repo(plans_root, active_entries=[])

        ready_pairs = {(r.plan_id, r.feature_id) for r in report.ready}
        assert ("2026-05-23-101-feat-seq", "F001") in ready_pairs
        assert ("2026-05-23-101-feat-seq", "F002") not in ready_pairs

        nr = next(
            n for n in report.not_ready if n.feature_id == "F002"
        )
        assert any("F001" in r and "passes=false" in r for r in nr.reasons)

    def test_passing_dependency_unlocks_downstream(self, tmp_path: Path) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-102-feat-seq-unlocked",
            features=[
                _feature("F001", passes=True),
                _feature("F002", depends_on=["F001"]),
            ],
        )
        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        ready_pairs = {(r.plan_id, r.feature_id) for r in report.ready}
        assert ("2026-05-23-102-feat-seq-unlocked", "F002") in ready_pairs

    def test_unknown_feature_dependency_blocks_with_clear_reason(
        self, tmp_path: Path
    ) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-103-feat-bad-dep",
            features=[_feature("F001", depends_on=["F999"])],
        )
        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        nr = next(n for n in report.not_ready if n.feature_id == "F001")
        assert any("F999" in r and "not declared" in r for r in nr.reasons)


class TestPlanFrontmatterDependencies:
    def test_active_parent_roadmap_dependency_does_not_block_child(
        self, tmp_path: Path
    ) -> None:
        plans_root = tmp_path / "docs" / "plans"
        parent_id = "2026-05-23-109-infra-roadmap-parent"
        parent = plans_root / parent_id
        parent.mkdir(parents=True)
        (parent / "plan.md").write_text(
            "---\n"
            f"id: {parent_id}\n"
            "title: Roadmap parent\n"
            "status: active\n"
            "---\n"
            "# Roadmap\n"
        )
        child_id = "2026-05-23-109-feat-child"
        _write_plan(
            plans_root,
            child_id,
            dependencies=[parent_id],
            parent_plan_id=parent_id,
            features=[_feature("F001")],
        )

        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        ready_pairs = {(r.plan_id, r.feature_id) for r in report.ready}
        assert (child_id, "F001") in ready_pairs

    def test_blocked_when_dependency_plan_incomplete(self, tmp_path: Path) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-110-feat-base",
            features=[_feature("F001")],  # passes=false
        )
        _write_plan(
            plans_root,
            "2026-05-23-111-feat-dependent",
            dependencies=["2026-05-23-110-feat-base"],
            features=[_feature("F001")],
        )
        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        ready_pairs = {(r.plan_id, r.feature_id) for r in report.ready}
        assert ("2026-05-23-111-feat-dependent", "F001") not in ready_pairs
        nr = next(
            n for n in report.not_ready if n.plan_id == "2026-05-23-111-feat-dependent"
        )
        assert any("2026-05-23-110-feat-base" in r for r in nr.reasons)

    def test_unblocked_when_dependency_plan_completed_status(
        self, tmp_path: Path
    ) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-112-feat-completed-base",
            status="completed",
            features=[_feature("F001", passes=True)],
        )
        _write_plan(
            plans_root,
            "2026-05-23-113-feat-dep-on-completed",
            dependencies=["2026-05-23-112-feat-completed-base"],
            features=[_feature("F001")],
        )
        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        ready_pairs = {(r.plan_id, r.feature_id) for r in report.ready}
        assert ("2026-05-23-113-feat-dep-on-completed", "F001") in ready_pairs

    def test_unknown_dependency_plan_id_surfaces_specific_reason(
        self, tmp_path: Path
    ) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-114-feat-dep-unknown",
            dependencies=["2026-09-99-999-nonexistent"],
            features=[_feature("F001")],
        )
        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        nr = next(
            n
            for n in report.not_ready
            if n.plan_id == "2026-05-23-114-feat-dep-unknown"
        )
        assert any("not present in the inventory" in r for r in nr.reasons)


class TestCollisionWarnings:
    def test_active_supervisor_same_plan_collision(self, tmp_path: Path) -> None:
        plans_root = tmp_path / "docs" / "plans"
        plan_id = "2026-05-23-120-feat-self-collision"
        _write_plan(plans_root, plan_id, features=[_feature("F001")])
        active = [
            active_supervisors.SupervisorEntry(
                pid=os.getpid(),
                plan_id=plan_id,
                target_env="dev",
                target_project=None,
                started_at="2026-05-23T00:00:00Z",
                supervisor_config_dir=None,
            )
        ]
        report = planning_readiness.analyze_repo(plans_root, active_entries=active)

        # Collision-warned but not suppressed: precision-biased advisory.
        assert any(
            w.kind == "collision" and w.subject == f"{plan_id}:F001"
            for w in report.warnings
        )
        assert any(r.feature_id == "F001" for r in report.ready)

    def test_different_plan_overlapping_paths_warns(self, tmp_path: Path) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-121-feat-active-touches-x",
            features=[_feature("F001")],
            allowed_paths=["scripts/dontpanic_orchestrate/**"],
            parent_plan_id="2026-05-23-006-infra-planning-intelligence-roadmap-v0",
        )
        _write_plan(
            plans_root,
            "2026-05-23-122-feat-also-touches-x",
            features=[
                _feature(
                    "F001",
                    steps=[
                        "edit scripts/dontpanic_orchestrate/foo.py",
                    ],
                )
            ],
            allowed_paths=["scripts/dontpanic_orchestrate/**"],
            parent_plan_id="2026-05-23-006-infra-planning-intelligence-roadmap-v0",
        )
        active = [
            active_supervisors.SupervisorEntry(
                pid=os.getpid(),
                plan_id="2026-05-23-121-feat-active-touches-x",
                target_env="dev",
                target_project=None,
                started_at="2026-05-23T00:00:00Z",
                supervisor_config_dir=None,
            )
        ]
        report = planning_readiness.analyze_repo(plans_root, active_entries=active)
        # The second plan's F001 should produce an advisory collision warning
        # because its allowed_paths overlap with the active supervisor's plan
        # AND a step contains a path-shaped token sharing a segment.
        collision_subjects = {
            w.subject for w in report.warnings if w.kind == "collision"
        }
        assert "2026-05-23-122-feat-also-touches-x:F001" in collision_subjects

    def test_different_plan_no_overlap_no_warning(self, tmp_path: Path) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-123-feat-active-elsewhere",
            features=[_feature("F001")],
            allowed_paths=["other/area/**"],
            parent_plan_id="2026-05-23-006-infra-planning-intelligence-roadmap-v0",
        )
        _write_plan(
            plans_root,
            "2026-05-23-124-feat-unrelated",
            features=[_feature("F001", steps=["edit unrelated/place/foo.py"])],
            allowed_paths=["unrelated/**"],
            parent_plan_id="2026-05-23-006-infra-planning-intelligence-roadmap-v0",
        )
        active = [
            active_supervisors.SupervisorEntry(
                pid=os.getpid(),
                plan_id="2026-05-23-123-feat-active-elsewhere",
                target_env="dev",
                target_project=None,
                started_at="2026-05-23T00:00:00Z",
                supervisor_config_dir=None,
            )
        ]
        report = planning_readiness.analyze_repo(plans_root, active_entries=active)
        collision_subjects = {
            w.subject for w in report.warnings if w.kind == "collision"
        }
        # The unrelated plan should NOT produce a collision warning — precision
        # bias requires both path overlap AND a shared step-token segment.
        assert "2026-05-23-124-feat-unrelated:F001" not in collision_subjects


class TestBreakerAndGateState:
    def test_active_breaker_blocks_and_warns(self, tmp_path: Path) -> None:
        plans_root = tmp_path / "docs" / "plans"
        plan_id = "2026-05-23-130-feat-with-breaker"
        plan_dir = _write_plan(plans_root, plan_id, features=[_feature("F001")])
        gate_pause.add_breaker(
            plan_dir,
            "breaker:no_progress",
            plan_id=plan_id,
            reason="synthetic",
        )

        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        ready_pairs = {(r.plan_id, r.feature_id) for r in report.ready}
        assert (plan_id, "F001") not in ready_pairs
        # Breaker warning surfaces
        assert any(
            w.kind == "breaker" and w.subject == plan_id for w in report.warnings
        )

    def test_uncleared_human_gate_blocks(self, tmp_path: Path) -> None:
        plans_root = tmp_path / "docs" / "plans"
        plan_id = "2026-05-23-131-feat-gate-blocked"
        plan_dir = _write_plan(
            plans_root, plan_id, features=[_feature("F001")], gates=["pre_impl"]
        )
        # Force pre_impl into pause_gates without clearing it.
        gate_pause.record_pause(
            plan_dir, plan_id=plan_id, pause_gates=["pre_impl"], stage="pre_impl"
        )

        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        nr = next(n for n in report.not_ready if n.plan_id == plan_id)
        assert any("pre_impl" in r for r in nr.reasons)


class TestMalformedAndErrorHandling:
    def test_malformed_plan_dir_does_not_crash(self, tmp_path: Path) -> None:
        plans_root = tmp_path / "docs" / "plans"
        plans_root.mkdir(parents=True)
        # Truly malformed frontmatter -> load_error. A parseable plan.md
        # without features.json is intentionally treated as a roadmap parent.
        bad = plans_root / "2026-05-23-140-feat-broken"
        bad.mkdir()
        (bad / "plan.md").write_text(
            "---\nid: [unterminated\ntitle: broken\n---\n"
        )
        # Plus a healthy one so we know the scan continued.
        _write_plan(plans_root, "2026-05-23-141-feat-healthy", features=[_feature("F001")])

        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        assert any(w.kind == "load_error" for w in report.warnings)
        assert any(
            r.plan_id == "2026-05-23-141-feat-healthy" for r in report.ready
        )

    def test_parseable_plan_without_features_is_roadmap_parent(
        self, tmp_path: Path
    ) -> None:
        plans_root = tmp_path / "docs" / "plans"
        plans_root.mkdir(parents=True)
        roadmap = plans_root / "2026-05-23-142-infra-roadmap-parent"
        roadmap.mkdir()
        (roadmap / "plan.md").write_text(
            "---\n"
            "id: 2026-05-23-142-infra-roadmap-parent\n"
            "title: Roadmap parent\n"
            "status: active\n"
            "---\n"
            "# Roadmap\n"
        )

        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        assert not any(w.kind == "load_error" for w in report.warnings)
        nr = next(
            n
            for n in report.not_ready
            if n.plan_id == "2026-05-23-142-infra-roadmap-parent"
        )
        assert nr.kind == "plan"
        assert any("no features.json" in r for r in nr.reasons)

    def test_missing_plans_root_returns_empty_with_scope_warning(
        self, tmp_path: Path
    ) -> None:
        report = planning_readiness.analyze_repo(
            tmp_path / "does-not-exist", active_entries=[]
        )
        assert report.ready == ()
        assert any(w.kind == "scope" for w in report.warnings)


class TestJsonShape:
    def test_json_envelope_has_required_top_level_fields(
        self, tmp_path: Path
    ) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-150-feat-json-shape",
            features=[_feature("F001")],
        )
        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        rendered = planning_readiness.render_json(report)
        data = json.loads(rendered)
        for key in (
            "schema_version",
            "generated_at",
            "scope",
            "ready",
            "not_ready",
            "warnings",
            "candidate_commands",
        ):
            assert key in data
        assert data["schema_version"] == planning_readiness.SCHEMA_VERSION
        assert data["scope"] == "repo"
        assert isinstance(data["ready"], list)
        # Every ready entry has the required fields.
        for ready_entry in data["ready"]:
            for key in (
                "kind",
                "plan_id",
                "plan_dir",
                "feature_id",
                "title",
                "reason",
                "command",
            ):
                assert key in ready_entry


class TestCliFlags:
    def test_include_not_ready_false_suppresses_section(
        self, tmp_path: Path
    ) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-160-feat-suppress",
            features=[_feature("F001", depends_on=["F999"])],
        )
        report = planning_readiness.analyze_repo(
            plans_root, include_not_ready=False, active_entries=[]
        )
        assert report.not_ready == ()

    def test_max_parallel_caps_candidate_commands(self, tmp_path: Path) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-161-feat-cap",
            features=[_feature("F001"), _feature("F002"), _feature("F003")],
        )
        report = planning_readiness.analyze_repo(
            plans_root, max_parallel=2, active_entries=[]
        )
        assert len(report.ready) == 3
        assert len(report.candidate_commands) == 2

    def test_all_passing_active_plan_is_treated_as_complete(
        self, tmp_path: Path
    ) -> None:
        plans_root = tmp_path / "docs" / "plans"
        _write_plan(
            plans_root,
            "2026-05-23-162-feat-all-done",
            status="active",
            features=[
                _feature("F001", passes=True),
                _feature("F002", passes=True),
            ],
        )
        report = planning_readiness.analyze_repo(plans_root, active_entries=[])
        assert report.ready == ()
        assert report.not_ready == ()
        assert report.candidate_commands == ()


class TestNoSideEffects:
    def test_analyze_writes_no_files_into_plan_dirs(
        self, tmp_path: Path
    ) -> None:
        plans_root = tmp_path / "docs" / "plans"
        plan_dir = _write_plan(
            plans_root,
            "2026-05-23-170-feat-no-write",
            features=[_feature("F001")],
        )
        before = sorted(p.relative_to(plan_dir) for p in plan_dir.rglob("*"))
        planning_readiness.analyze_repo(plans_root, active_entries=[])
        after = sorted(p.relative_to(plan_dir) for p in plan_dir.rglob("*"))
        assert before == after


class TestFleetAggregation:
    def test_fleet_aggregates_per_project_and_labels(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Two synthetic registered projects, each with one plan that has one
        # ready feature. analyze_fleet must label items with project_name and
        # interleave candidate commands across projects.
        proj_a = tmp_path / "project-a"
        proj_b = tmp_path / "project-b"
        plans_a = proj_a / "docs" / "plans"
        plans_b = proj_b / "docs" / "plans"
        _write_plan(plans_a, "2026-05-23-180-feat-a", features=[_feature("F001")])
        _write_plan(plans_b, "2026-05-23-180-feat-b", features=[_feature("F001")])

        # DONTPANIC_HOME is already redirected by conftest; register both
        # projects in the redirected registry.
        projects_registry.add_project("proj-a", str(proj_a))
        projects_registry.add_project("proj-b", str(proj_b))

        report = planning_readiness.analyze_fleet(active_entries=[])
        assert report.scope == "fleet"
        # Both projects represented in by_project.
        assert "proj-a" in report.by_project
        assert "proj-b" in report.by_project
        # Every ready item carries project_name.
        proj_names = {r.project_name for r in report.ready}
        assert proj_names == {"proj-a", "proj-b"}
        # Round-robin interleave: first two commands cover both projects.
        assert len(report.candidate_commands) == 2

    def test_fleet_skips_inactive_project(
        self, tmp_path: Path
    ) -> None:
        proj_a = tmp_path / "active-proj"
        proj_b = tmp_path / "inactive-proj"
        plans_a = proj_a / "docs" / "plans"
        plans_b = proj_b / "docs" / "plans"
        _write_plan(plans_a, "2026-05-23-181-feat-act", features=[_feature("F001")])
        _write_plan(plans_b, "2026-05-23-181-feat-ina", features=[_feature("F001")])
        projects_registry.add_project("act-proj", str(proj_a))
        projects_registry.add_project("ina-proj", str(proj_b), active=False)

        report = planning_readiness.analyze_fleet(active_entries=[])
        assert "act-proj" in report.by_project
        assert "ina-proj" not in report.by_project
