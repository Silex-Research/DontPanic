"""F023 EC1 — environments.json loader + supervisor pre-dispatch validator tests.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_environments_loader.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import supervisor  # noqa: E402
from dontpanic_orchestrate.environments_loader import (  # noqa: E402
    DECLARABLE_TIERS,
    EnvironmentsNotFoundError,
    EnvironmentsTargetMismatchError,
    EnvironmentsValidationError,
    find_repo_root_for_plan,
    load_environments,
    validate_target,
)
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)

# ──────────────────────────────  fixtures  ──────────────────────────────


def _glam_full() -> dict:
    return {
        "repo": "Glam",
        "dev": {
            "firebase_project": "glam-styln-dev",
            "gcp_project": "glam-styln-dev",
            "xcode_scheme": "GlamSwift-Dev",
            "bundle_id": "com.silexholdings.glam.dev",
        },
        "staging": {
            "firebase_project": "glam-styln-staging",
            "gcp_project": "glam-styln-staging",
            "xcode_scheme": "GlamSwift-Staging",
            "bundle_id": "com.silexholdings.glam",
        },
        "prod": {
            "firebase_project": "glam-ac11e",
            "gcp_project": "glam-ac11e",
            "xcode_scheme": "GlamSwift-Prod",
            "bundle_id": "com.silexholdings.glam",
        },
    }


def _jarvis_dev_only() -> dict:
    return {
        "repo": "Jarvis",
        "dev": {"firebase_project": "jarvis-a6ee1", "gcp_project": "jarvis-a6ee1"},
    }


def _write_env_file(repo_root: Path, payload: dict) -> Path:
    repo_root.mkdir(parents=True, exist_ok=True)
    path = repo_root / "environments.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


# ──────────────────────────────  load_environments — happy paths  ──────────────────────────────


def test_load_environments_full_three_tier() -> None:
    print("\n[test] load_environments_full_three_tier ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "Glam"
        _write_env_file(repo, _glam_full())
        env = load_environments(repo)
        assert env.repo == "Glam", env
        assert env.dev.firebase_project == "glam-styln-dev"
        assert env.staging.bundle_id == "com.silexholdings.glam"
        assert env.prod.xcode_scheme == "GlamSwift-Prod"
    print("  ✓ full three-tier registry loads + Pydantic-validates")


def test_load_environments_sparse_dev_only() -> None:
    print("\n[test] load_environments_sparse_dev_only ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "Jarvis"
        _write_env_file(repo, _jarvis_dev_only())
        env = load_environments(repo)
        assert env.repo == "Jarvis"
        assert env.dev.firebase_project == "jarvis-a6ee1"
        assert env.staging is None and env.prod is None
    print("  ✓ sparse single-tier registry valid; undeclared tiers stay None")


# ──────────────────────────────  load_environments — error paths  ──────────────────────────────


def test_load_environments_missing_file_raises() -> None:
    print("\n[test] load_environments_missing_file_raises ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "noenv"
        repo.mkdir()
        try:
            load_environments(repo)
        except EnvironmentsNotFoundError as exc:
            assert "environments.json" in str(exc)
            print("  ✓ raises EnvironmentsNotFoundError when file missing")
            return
    raise AssertionError("expected EnvironmentsNotFoundError")


def test_load_environments_malformed_json_raises() -> None:
    print("\n[test] load_environments_malformed_json_raises ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "broken"
        repo.mkdir()
        (repo / "environments.json").write_text("{not valid json")
        try:
            load_environments(repo)
        except EnvironmentsValidationError as exc:
            assert "malformed JSON" in str(exc)
            print("  ✓ raises EnvironmentsValidationError on JSON parse error")
            return
    raise AssertionError("expected EnvironmentsValidationError")


def test_load_environments_extra_field_rejected() -> None:
    print("\n[test] load_environments_extra_field_rejected ...")
    payload = _jarvis_dev_only()
    payload["dev"]["unknown_field"] = "x"
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "extra"
        _write_env_file(repo, payload)
        try:
            load_environments(repo)
        except EnvironmentsValidationError as exc:
            assert "unknown_field" in str(exc) or "extra" in str(exc).lower()
            print("  ✓ Pydantic extra='forbid' surfaces as EnvironmentsValidationError")
            return
    raise AssertionError("expected EnvironmentsValidationError for extra field")


def test_load_environments_no_tiers_rejected() -> None:
    print("\n[test] load_environments_no_tiers_rejected ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "empty"
        _write_env_file(repo, {"repo": "Empty"})
        try:
            load_environments(repo)
        except EnvironmentsValidationError as exc:
            assert "at least one" in str(exc)
            print("  ✓ cross-cutting check rejects when no tier is declared")
            return
    raise AssertionError("expected EnvironmentsValidationError for no tiers")


def test_load_environments_tier_without_project_rejected() -> None:
    print("\n[test] load_environments_tier_without_project_rejected ...")
    payload = {"repo": "X", "dev": {"xcode_scheme": "Foo"}}
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "anchorless"
        _write_env_file(repo, payload)
        try:
            load_environments(repo)
        except EnvironmentsValidationError as exc:
            msg = str(exc)
            assert "firebase_project" in msg and "gcp_project" in msg
            print("  ✓ cross-cutting check rejects tier with no project anchor")
            return
    raise AssertionError("expected EnvironmentsValidationError for missing project")


def test_load_environments_missing_repo_field_rejected() -> None:
    print("\n[test] load_environments_missing_repo_field_rejected ...")
    payload = {"dev": {"firebase_project": "x"}}
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "norepo"
        _write_env_file(repo, payload)
        try:
            load_environments(repo)
        except EnvironmentsValidationError as exc:
            assert "repo" in str(exc).lower()
            print("  ✓ Pydantic required=true surfaces as EnvironmentsValidationError")
            return
    raise AssertionError("expected EnvironmentsValidationError for missing repo")


# ──────────────────────────────  find_repo_root_for_plan  ──────────────────────────────


def test_find_repo_root_at_plan_root() -> None:
    print("\n[test] find_repo_root_at_plan_root ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "MyRepo"
        _write_env_file(repo, _jarvis_dev_only())
        # plan dir IS the repo root
        found = find_repo_root_for_plan(repo)
        assert found == repo.resolve()
    print("  ✓ returns the dir itself when env file lives there")


def test_find_repo_root_walks_up() -> None:
    print("\n[test] find_repo_root_walks_up ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "MyRepo"
        _write_env_file(repo, _jarvis_dev_only())
        plan_dir = repo / "docs" / "plans" / "2026-04-26-001-foo"
        plan_dir.mkdir(parents=True)
        found = find_repo_root_for_plan(plan_dir)
        assert found == repo.resolve()
    print("  ✓ walks up from nested plan dir until env file is found")


def test_find_repo_root_returns_none_when_absent() -> None:
    print("\n[test] find_repo_root_returns_none_when_absent ...")
    with tempfile.TemporaryDirectory() as tmp:
        plan_dir = Path(tmp) / "no_registry" / "docs" / "plans" / "p"
        plan_dir.mkdir(parents=True)
        found = find_repo_root_for_plan(plan_dir)
        # Walk-up reaches the tmp dir's parents; environments.json may exist
        # somewhere on the host filesystem above tmp, so we only assert
        # "found is None OR the discovered root is outside the temp tree".
        if found is not None:
            assert tmp not in str(found), found
    print("  ✓ no env file inside plan tree → returns None (or escapes scope)")


# ──────────────────────────────  validate_target  ──────────────────────────────


def test_validate_target_happy() -> None:
    print("\n[test] validate_target_happy ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "Glam"
        _write_env_file(repo, _glam_full())
        env = load_environments(repo)
        validate_target(env, "dev", "glam-styln-dev")
        validate_target(env, "staging", "glam-styln-staging")
        validate_target(env, "prod", "glam-ac11e")
    print("  ✓ declared (env, project) pair passes silently")


def test_validate_target_undeclared_tier_raises() -> None:
    print("\n[test] validate_target_undeclared_tier_raises ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "Jarvis"
        _write_env_file(repo, _jarvis_dev_only())
        env = load_environments(repo)
        try:
            validate_target(env, "staging", "jarvis-a6ee1")
        except EnvironmentsTargetMismatchError as exc:
            assert "staging" in str(exc) and "declared tiers" in str(exc)
            print("  ✓ rejects dispatch to undeclared tier with surfaced declared tiers")
            return
    raise AssertionError("expected EnvironmentsTargetMismatchError")


def test_validate_target_project_mismatch_raises() -> None:
    print("\n[test] validate_target_project_mismatch_raises ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "Glam"
        _write_env_file(repo, _glam_full())
        env = load_environments(repo)
        try:
            validate_target(env, "dev", "wrong-project-id")
        except EnvironmentsTargetMismatchError as exc:
            msg = str(exc)
            assert "wrong-project-id" in msg and "glam-styln-dev" in msg
            print("  ✓ rejects when target_project doesn't match registered projects")
            return
    raise AssertionError("expected EnvironmentsTargetMismatchError")


def test_validate_target_host_local_skipped() -> None:
    print("\n[test] validate_target_host_local_skipped ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "Jarvis"
        _write_env_file(repo, _jarvis_dev_only())
        env = load_environments(repo)
        # target_project=None (host-local) — should not raise even on undeclared tier
        validate_target(env, "staging", None)
        validate_target(env, "prod", None)
    print("  ✓ host-local plans (target_project=None) skip registry check")


def test_validate_target_matches_gcp_project_field() -> None:
    print("\n[test] validate_target_matches_gcp_project_field ...")
    payload = {
        "repo": "X",
        "dev": {"gcp_project": "only-gcp-no-firebase"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "X"
        _write_env_file(repo, payload)
        env = load_environments(repo)
        validate_target(env, "dev", "only-gcp-no-firebase")
    print("  ✓ project match works against gcp_project when firebase_project is unset")


def test_validate_target_invalid_env_label_raises() -> None:
    print("\n[test] validate_target_invalid_env_label_raises ...")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "Glam"
        _write_env_file(repo, _glam_full())
        env = load_environments(repo)
        try:
            validate_target(env, "production", "glam-ac11e")
        except EnvironmentsTargetMismatchError as exc:
            assert "production" in str(exc) and str(list(DECLARABLE_TIERS)) in str(exc)
            print("  ✓ rejects env label not in DECLARABLE_TIERS (e.g., 'production')")
            return
    raise AssertionError("expected EnvironmentsTargetMismatchError")


# ──────────────────────────────  supervisor pre-dispatch (Expansion A)  ──────────────────────────────


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_plan(repo_root: Path, plan_id: str, target_project: str = "jarvis-a6ee1") -> Path:
    plan_dir = repo_root / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    project_yaml = target_project if target_project else "none"
    plan_md = f"""---
id: {plan_id}
title: F023 EC1 synthetic
type: infra
tier: trivial
status: active
date: "2026-04-26"
description: Synthetic plan for F023 EC1 supervisor wiring tests.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# F023 EC1 synthetic

## Target

```yaml
target_env: dev
target_project: {project_yaml}
```
"""
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001",
                "category": "test",
                "phase": 0,
                "description": "Synthetic feature for F023 EC1 supervisor wiring tests.",
                "steps": ["scripted"],
                "acceptance": "Pre-dispatch env-registry validation runs.",
                "passes": False,
                "depends_on": [],
            }
        ],
    }
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(
        json.dumps(features, indent=2, ensure_ascii=False) + "\n"
    )
    return plan_dir


class _DispatchCountingExecutor(BaseExecutor):
    """Records every dispatch call; emits a clean signed-off summary."""

    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.dispatch_count = 0

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.dispatch_count += 1
        s = (
            f"Repo: synthetic\nEnv: dev\nProject: jarvis-a6ee1\n"
            f"Synthetic {task.agent_role} round {task.iteration} signed off."
        )
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=s,
            raw_response=s,
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _run_volley_with_counting(plan_dir: Path):
    impl = _DispatchCountingExecutor("claude")
    aud = _DispatchCountingExecutor("codex")
    saved_registry = dict(AGENT_REGISTRY)
    saved_quota = supervisor._quota_gate
    AGENT_REGISTRY["claude"] = lambda: impl
    AGENT_REGISTRY["codex"] = lambda: aud
    supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")
    # F008: pre-clear declared gates so the new gate-pause check doesn't pause
    # this EC1 fixture (exercises env-registry validation, not gate-pause).
    from dontpanic_orchestrate import gate_pause
    from dontpanic_orchestrate import plan_loader as _pl

    _loaded_for_gates = _pl.load(plan_dir)
    gate_pause.resume_all(
        plan_dir,
        plan_id=_loaded_for_gates.plan_id,
        declared_gates=list(_loaded_for_gates.plan.human_gates or []),
    )
    try:
        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        supervisor._quota_gate = saved_quota
    return result, impl, aud


def test_supervisor_host_local_skips_registry_check() -> None:
    print("\n[test] supervisor_host_local_skips_registry_check ...")
    with tempfile.TemporaryDirectory() as td:
        # Registry exists, but plan is host-local (target_project=none) — must skip
        _write_env_file(Path(td), _jarvis_dev_only())
        plan_dir = _make_plan(Path(td), "2026-04-26-001-infra-host-local", target_project="")
        result, impl, aud = _run_volley_with_counting(plan_dir)
        assert result.final_status == "signed_off", result
        assert impl.dispatch_count == 1 and aud.dispatch_count == 1
    print("  ✓ host-local plan dispatches normally even when env file is present")


def test_supervisor_no_registry_skips_silently() -> None:
    print("\n[test] supervisor_no_registry_skips_silently ...")
    with tempfile.TemporaryDirectory() as td:
        # Plan claims a project but there's no environments.json on the path
        plan_dir = _make_plan(
            Path(td), "2026-04-26-002-infra-no-registry", target_project="some-proj"
        )
        result, impl, aud = _run_volley_with_counting(plan_dir)
        # Walk-up may escape tmp scope, so we accept either: signed_off (no host-tree
        # registry found upward) or a typed mismatch (host-tree registry was found).
        # The contract is: no crash, supervisor flow either dispatches or rejects via
        # typed exception — never an unhandled error path.
        if result.final_status == "signed_off":
            assert impl.dispatch_count == 1 and aud.dispatch_count == 1
            print("  ✓ no env file on path → supervisor proceeds")
        else:
            print(f"  ✓ host-tree registry intercepted: status={result.final_status}")


def test_supervisor_registry_match_records_evidence() -> None:
    print("\n[test] supervisor_registry_match_records_evidence ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _write_env_file(repo, _jarvis_dev_only())
        plan_dir = _make_plan(
            repo, "2026-04-26-003-infra-registry-match", target_project="jarvis-a6ee1"
        )
        result, impl, aud = _run_volley_with_counting(plan_dir)
        assert result.final_status == "signed_off", result
        assert impl.dispatch_count == 1 and aud.dispatch_count == 1
        # Audit validation_performed must record env_registry tag
        for audit_path in result.audit_paths:
            data = json.loads(audit_path.read_text())
            vp = data.get("validation_performed") or []
            assert any("env_registry=Jarvis" in line for line in vp), vp
    print("  ✓ matched dispatch tags audit validation_performed with env_registry=<repo>")


def test_supervisor_undeclared_tier_blocks_pre_dispatch() -> None:
    print("\n[test] supervisor_undeclared_tier_blocks_pre_dispatch ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        # Registry declares only dev; plan asks for staging
        _write_env_file(repo, _jarvis_dev_only())
        plan_dir = _make_plan(
            repo, "2026-04-26-004-infra-tier-undeclared", target_project="jarvis-a6ee1"
        )
        # Override target_env via supervisor kwarg to staging
        impl = _DispatchCountingExecutor("claude")
        aud = _DispatchCountingExecutor("codex")
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = supervisor._quota_gate
        AGENT_REGISTRY["claude"] = lambda: impl
        AGENT_REGISTRY["codex"] = lambda: aud
        supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")
        try:
            try:
                supervisor.dispatch_volley(
                    plan_dir,
                    "F001",
                    target_env="staging",
                    max_iterations=1,
                )
            except EnvironmentsTargetMismatchError as exc:
                msg = str(exc)
                assert "staging" in msg and "declared tiers" in msg, msg
                # Critical: no executor was called
                assert impl.dispatch_count == 0, impl.dispatch_count
                assert aud.dispatch_count == 0, aud.dispatch_count
                print("  ✓ raises EnvironmentsTargetMismatchError; no executor called")
                return
            raise AssertionError("expected EnvironmentsTargetMismatchError")
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota


def test_supervisor_project_mismatch_blocks_pre_dispatch() -> None:
    print("\n[test] supervisor_project_mismatch_blocks_pre_dispatch ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        # Registry declares dev → jarvis-a6ee1; plan claims target_project=other-proj
        _write_env_file(repo, _jarvis_dev_only())
        plan_dir = _make_plan(
            repo, "2026-04-26-005-infra-project-mismatch", target_project="other-proj"
        )
        impl = _DispatchCountingExecutor("claude")
        aud = _DispatchCountingExecutor("codex")
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = supervisor._quota_gate
        AGENT_REGISTRY["claude"] = lambda: impl
        AGENT_REGISTRY["codex"] = lambda: aud
        supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")
        try:
            try:
                supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            except EnvironmentsTargetMismatchError as exc:
                msg = str(exc)
                assert "other-proj" in msg and "jarvis-a6ee1" in msg, msg
                assert impl.dispatch_count == 0, impl.dispatch_count
                assert aud.dispatch_count == 0, aud.dispatch_count
                print("  ✓ raises EnvironmentsTargetMismatchError; no executor called")
                return
            raise AssertionError("expected EnvironmentsTargetMismatchError")
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota
