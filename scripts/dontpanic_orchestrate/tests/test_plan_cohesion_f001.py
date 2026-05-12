"""Plan 2026-05-12-001 F001 — lock-time plan-cohesion validator.

Reproduces the two plan-004 pre-lock inconsistencies that D024 motivated:

  (a) ``child_charter.allowed_paths`` still pointed at ``axiom/packages/**``
      after the D006 rename, while feature steps named paths under
      ``dashboard/`` — drift mid-dispatch would have cost ~9M tokens.
  (b) ``parent_acceptance_item`` deferred F003-F005 "until operator
      credentials in place", but F001 acceptance #4 demanded a smoke
      test against ``<firebase-project-id>`` (a credentialed Firebase project).

Both cases must surface as WARN findings with copy-paste remediation
hints. A clean plan must NOT false-positive.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"


def _load_doctor():
    spec = importlib.util.spec_from_file_location("jarvis_doctor", DOCTOR_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_doctor"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def doctor():
    return _load_doctor()


def _write_plan(
    plan_dir: Path,
    *,
    plan_id: str,
    allowed_paths: list[str],
    parent_acceptance_item: str,
    features: list[dict],
    may_edit_product_code: bool = True,
    status: str = "active",
) -> None:
    plan_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = textwrap.dedent(
        f"""\
        ---
        id: {plan_id}
        title: synthetic plan for F001 cohesion tests
        type: fix
        tier: local
        status: {status}
        date: "2026-05-12"
        goal_type: infra
        privacy_tier: internal
        orchestration:
          parent_plan_id: 2026-01-01-001-parent-synthetic
          spawn_reason: operator_manual
          depth_limit: 3
        child_charter:
          kind: implementation
          parent_objective: "synthetic"
          parent_acceptance_item: {json.dumps(parent_acceptance_item)}
          allowed_paths:
        """
    )
    paths_block = "\n".join(f"    - {json.dumps(p)}" for p in allowed_paths)
    frontmatter += paths_block + "\n"
    frontmatter += textwrap.dedent(
        f"""\
          return_condition_summary: "synthetic"
          may_edit_product_code: {str(may_edit_product_code).lower()}
        ---

        # synthetic plan body
        """
    )
    (plan_dir / "plan.md").write_text(frontmatter)
    (plan_dir / "features.json").write_text(
        json.dumps({"task_id": plan_id, "schema_version": "1.0", "features": features}, indent=2)
    )


# ── (a) allowed_paths drift — the plan-004 axiom/-vs-dashboard case ──


def test_allowed_paths_drift_is_flagged_per_plan_004(doctor, tmp_path) -> None:
    plan_dir = tmp_path / "2026-05-12-100-fixture-allowed-paths-drift"
    _write_plan(
        plan_dir,
        plan_id="2026-05-12-100-fixture-allowed-paths-drift",
        allowed_paths=["axiom/packages/**"],
        parent_acceptance_item="all features land",
        features=[
            {
                "id": "F001",
                "category": "feat",
                "phase": 1,
                "description": "wire the realtime dashboard",
                "steps": [
                    "Read `dashboard/app.tsx` current structure.",
                    "Add a hook to dashboard/src/hooks/useRealtime.ts.",
                ],
                "acceptance": "dashboard renders live data",
                "passes": False,
                "depends_on": [],
            }
        ],
    )

    results = doctor.validate_plan_cohesion(plan_dir)
    drift = [r for r in results if "allowed-paths" in r.name]
    assert drift, f"expected an allowed-paths warning; got {[r.name for r in results]}"
    finding = drift[0]
    assert finding.warn is True
    assert finding.ok is True  # warn doesn't fail the doctor
    assert "dashboard" in finding.message
    assert "axiom/packages/**" in finding.message
    assert finding.remediation, "every finding must carry a remediation hint"
    assert "dashboard/" in finding.remediation


# ── (b) acceptance-vs-deferred-resource — the plan-004 <firebase-project-id> case ──


def test_acceptance_vs_deferred_resource_is_flagged_per_plan_004(doctor, tmp_path) -> None:
    plan_dir = tmp_path / "2026-05-12-101-fixture-acceptance-deferred"
    _write_plan(
        plan_dir,
        plan_id="2026-05-12-101-fixture-acceptance-deferred",
        allowed_paths=["scripts/**", "docs/plans/2026-05-12-101-fixture-acceptance-deferred/**"],
        parent_acceptance_item=(
            "F001 + F002 land locally; F003-F005 against <firebase-project-id> "
            "deferred until operator credentials in place"
        ),
        features=[
            {
                "id": "F001",
                "category": "feat",
                "phase": 1,
                "description": "local-fixture adapter",
                "steps": [
                    "Add a synchronous fixture loader at scripts/firebase_adapter/loader.py."
                ],
                "acceptance": (
                    "(1) loader parses fixture; (2) tests pass; "
                    "(3) round-trip smoke test against <firebase-project-id> with seed Firestore state"
                ),
                "passes": False,
                "depends_on": [],
            }
        ],
    )

    results = doctor.validate_plan_cohesion(plan_dir)
    deferred = [r for r in results if "acceptance-deferred" in r.name]
    assert deferred, f"expected an acceptance-deferred warning; got {[r.name for r in results]}"
    finding = deferred[0]
    assert finding.warn is True
    assert "<firebase-project-id>" in finding.message
    assert finding.remediation
    assert "fixture" in finding.remediation or "local" in finding.remediation


def test_acceptance_with_deferral_but_no_shared_resource_is_not_flagged(doctor, tmp_path) -> None:
    """Strict-intersection regression: a parent that defers some other
    resource must not condemn a feature whose acceptance names a
    different credentialed resource. The shared-token requirement is
    what keeps the check from over-firing."""
    plan_dir = tmp_path / "2026-05-12-105-no-shared-resource"
    _write_plan(
        plan_dir,
        plan_id="2026-05-12-105-no-shared-resource",
        allowed_paths=["scripts/**"],
        parent_acceptance_item=(
            "F003-F005 deferred until axiom-workspace-prod1 credentials in place"
        ),
        features=[
            {
                "id": "F001",
                "category": "feat",
                "phase": 1,
                "description": "x",
                "steps": ["Read scripts/foo.py."],
                "acceptance": "smoke against <firebase-project-id> succeeds",
                "passes": False,
                "depends_on": [],
            }
        ],
    )
    findings = [r for r in doctor.validate_plan_cohesion(plan_dir) if "acceptance-deferred" in r.name]
    assert findings == [], (
        "parent defers axiom-workspace-prod1 but feature names <firebase-project-id> — "
        "no shared resource, so the check should stay quiet"
    )


# ── (c) clean plan — negative case, no false positives ──


def test_clean_plan_emits_no_findings(doctor, tmp_path) -> None:
    plan_dir = tmp_path / "2026-05-12-102-fixture-clean"
    _write_plan(
        plan_dir,
        plan_id="2026-05-12-102-fixture-clean",
        allowed_paths=["scripts/**", "docs/plans/2026-05-12-102-fixture-clean/**"],
        parent_acceptance_item="all features land",
        features=[
            {
                "id": "F001",
                "category": "feat",
                "phase": 1,
                "description": "synchronous adapter",
                "steps": [
                    "Read scripts/firebase_adapter/loader.py current shape.",
                    "Add a fixture test under scripts/firebase_adapter/tests/test_loader.py.",
                ],
                "acceptance": "(1) loader parses fixture; (2) tests pass",
                "passes": False,
                "depends_on": [],
            }
        ],
    )

    results = doctor.validate_plan_cohesion(plan_dir)
    assert results == [], f"clean plan should produce zero findings; got {[r.name for r in results]}"


# ── (d) top-level plan (no child_charter) is skipped ──


def test_top_level_plan_without_charter_is_skipped(doctor, tmp_path) -> None:
    plan_dir = tmp_path / "2026-05-12-103-top-level"
    plan_dir.mkdir()
    (plan_dir / "plan.md").write_text(
        textwrap.dedent(
            """\
            ---
            id: 2026-05-12-103-top-level
            title: top-level plan
            type: feat
            tier: local
            status: active
            date: "2026-05-12"
            goal_type: infra
            privacy_tier: internal
            ---

            # body
            """
        )
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": "2026-05-12-103-top-level",
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "feat",
                        "phase": 1,
                        "description": "x",
                        "steps": ["Edit anywhere/anything.py freely."],
                        "acceptance": "smoke against jarvis-prod99 succeeds",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            }
        )
    )
    assert doctor.validate_plan_cohesion(plan_dir) == []


# ── (e) walker — both fixtures + clean plan under one root ──


def test_check_plan_cohesion_walks_root_and_aggregates(doctor, tmp_path) -> None:
    plans_root = tmp_path / "docs" / "plans"
    plans_root.mkdir(parents=True)

    _write_plan(
        plans_root / "p-drift",
        plan_id="2026-05-12-200-fixture-drift",
        allowed_paths=["axiom/packages/**"],
        parent_acceptance_item="all features land",
        features=[
            {
                "id": "F001",
                "category": "feat",
                "phase": 1,
                "description": "x",
                "steps": ["Edit `dashboard/app.tsx`."],
                "acceptance": "x",
                "passes": False,
                "depends_on": [],
            }
        ],
    )
    _write_plan(
        plans_root / "p-clean",
        plan_id="2026-05-12-201-fixture-clean",
        allowed_paths=["scripts/**"],
        parent_acceptance_item="all features land",
        features=[
            {
                "id": "F001",
                "category": "feat",
                "phase": 1,
                "description": "x",
                "steps": ["Read scripts/foo.py."],
                "acceptance": "tests pass",
                "passes": False,
                "depends_on": [],
            }
        ],
    )

    results = doctor.check_plan_cohesion(plans_root=plans_root)
    # Drift finding present, no false positive on the clean plan.
    drift = [r for r in results if "p-drift" in r.name or "2026-05-12-200" in r.name]
    clean = [r for r in results if "p-clean" in r.name or "2026-05-12-201" in r.name]
    assert drift, f"walker should surface the drifting plan; got {[r.name for r in results]}"
    # The clean plan should not contribute any WARN findings.
    assert all(r.warn is False for r in clean), f"clean plan triggered a warn: {clean}"


def test_check_plan_cohesion_skips_draft_plans(doctor, tmp_path) -> None:
    """Drafts are pre-lock — drift inside a draft is expected, since the
    operator is still editing it. The walker must filter draft plans out
    so cohesion findings only fire after `dontpanic plan lock` flips
    status to ``active``."""
    plans_root = tmp_path / "docs" / "plans"
    plans_root.mkdir(parents=True)

    # Draft plan with the same allowed_paths drift as the (a) reproducer.
    # Under the locked-only filter, this drift must NOT surface.
    _write_plan(
        plans_root / "p-draft-drift",
        plan_id="2026-05-12-400-fixture-draft-drift",
        allowed_paths=["axiom/packages/**"],
        parent_acceptance_item="all features land",
        features=[
            {
                "id": "F001",
                "category": "feat",
                "phase": 1,
                "description": "x",
                "steps": ["Edit `dashboard/app.tsx`."],
                "acceptance": "x",
                "passes": False,
                "depends_on": [],
            }
        ],
        status="draft",
    )
    # Locked plan with the same drift — this one SHOULD surface, to prove
    # the filter is per-plan rather than blanket-suppressing.
    _write_plan(
        plans_root / "p-locked-drift",
        plan_id="2026-05-12-401-fixture-locked-drift",
        allowed_paths=["axiom/packages/**"],
        parent_acceptance_item="all features land",
        features=[
            {
                "id": "F001",
                "category": "feat",
                "phase": 1,
                "description": "x",
                "steps": ["Edit `dashboard/app.tsx`."],
                "acceptance": "x",
                "passes": False,
                "depends_on": [],
            }
        ],
        status="active",
    )

    results = doctor.check_plan_cohesion(plans_root=plans_root)
    drift = [r for r in results if "allowed-paths" in r.name]
    plan_ids_with_drift = {r.name.split(":")[1] for r in drift}
    assert "2026-05-12-401-fixture-locked-drift" in plan_ids_with_drift, (
        f"locked plan with drift should be flagged; got {[r.name for r in drift]}"
    )
    assert "2026-05-12-400-fixture-draft-drift" not in plan_ids_with_drift, (
        f"draft plan must be skipped; got {[r.name for r in drift]}"
    )


def test_check_plan_cohesion_empty_root_returns_pass(doctor, tmp_path) -> None:
    plans_root = tmp_path / "docs" / "plans"
    plans_root.mkdir(parents=True)
    results = doctor.check_plan_cohesion(plans_root=plans_root)
    assert len(results) == 1
    only = results[0]
    assert only.ok is True and only.warn is False
    assert "internally consistent" in only.message or "no plans" in only.message


# ── (f) deferral marker is necessary — without it, no acceptance warning ──


def test_acceptance_without_deferral_marker_is_not_flagged(doctor, tmp_path) -> None:
    plan_dir = tmp_path / "2026-05-12-104-no-deferral"
    _write_plan(
        plan_dir,
        plan_id="2026-05-12-104-no-deferral",
        allowed_paths=["scripts/**"],
        parent_acceptance_item="all features land cleanly with credentials available",
        features=[
            {
                "id": "F001",
                "category": "feat",
                "phase": 1,
                "description": "x",
                "steps": ["Read scripts/foo.py."],
                "acceptance": "smoke against <firebase-project-id> succeeds",
                "passes": False,
                "depends_on": [],
            }
        ],
    )
    findings = [r for r in doctor.validate_plan_cohesion(plan_dir) if "acceptance-deferred" in r.name]
    assert findings == [], "parent has no deferral marker — should not flag"


# ── (g) --validate-plans CLI flag surfaces the findings via run_all_checks ──


def test_run_all_checks_includes_plan_cohesion_when_opted_in(doctor, tmp_path, monkeypatch) -> None:
    plans_root = tmp_path / "docs" / "plans"
    plans_root.mkdir(parents=True)
    _write_plan(
        plans_root / "p-drift",
        plan_id="2026-05-12-300-fixture-drift",
        allowed_paths=["axiom/packages/**"],
        parent_acceptance_item="ok",
        features=[
            {
                "id": "F001",
                "category": "feat",
                "phase": 1,
                "description": "x",
                "steps": ["Edit `dashboard/app.tsx`."],
                "acceptance": "ok",
                "passes": False,
                "depends_on": [],
            }
        ],
    )
    monkeypatch.setattr(doctor, "PLANS_ROOT", plans_root)

    # validate_plans=False → no plan-cohesion entries in the result set.
    off = doctor.run_all_checks(skip_auth=True, include_projects=False, validate_plans=False)
    assert not any(r.name.startswith("plan-cohesion") for r in off)

    # validate_plans=True → at least one plan-cohesion finding (the drift).
    on = doctor.run_all_checks(skip_auth=True, include_projects=False, validate_plans=True)
    cohesion = [r for r in on if r.name.startswith("plan-cohesion")]
    assert cohesion, f"--validate-plans should surface cohesion findings; got {[r.name for r in on]}"
    assert any(r.warn for r in cohesion)
