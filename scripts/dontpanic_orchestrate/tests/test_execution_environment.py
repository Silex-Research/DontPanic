"""F023 Step 1 synthetic tests for EC9/EC10.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_execution_environment.py
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.command_guard import CommandRejected, assert_allowed  # noqa: E402
from dontpanic_orchestrate.execution_environment import (  # noqa: E402
    ISOLATED_ENV_FILES,
    ISOLATED_ENV_PATHS,
    ExecutionEnvironment,
)
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)
from dontpanic_orchestrate.executors.claude_cli import ClaudeCLIExecutor  # noqa: E402

FAKE_GCLOUD = """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

config = Path(os.environ["CLOUDSDK_CONFIG"]) / "configurations" / "config_default"
config.parent.mkdir(parents=True, exist_ok=True)
args = sys.argv[1:]

if args[:3] == ["config", "set", "project"] and len(args) == 4:
    config.write_text(f"[core]\\nproject = {args[3]}\\n")
    print(f"updated-file-project={args[3]}")
    raise SystemExit(0)

if args[:3] == ["config", "get-value", "project"]:
    print(os.environ.get("CLOUDSDK_CORE_PROJECT", ""))
    raise SystemExit(0)

print("unsupported fake gcloud invocation", file=sys.stderr)
raise SystemExit(2)
"""

FAKE_CLAUDE = """#!/usr/bin/env python3
import json
import os

print(json.dumps({
    "result": os.environ.get("JARVIS_TARGET_PROJECT", ""),
    "usage": {},
    "modelUsage": {}
}))
"""


def _make_fake_gcloud(tmp: Path) -> Path:
    path = tmp / "gcloud"
    path.write_text(FAKE_GCLOUD)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _make_fake_claude(tmp: Path) -> Path:
    path = tmp / "claude"
    path.write_text(FAKE_CLAUDE)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _read_config_project(config_path: Path) -> str:
    for line in config_path.read_text().splitlines():
        if line.startswith("project = "):
            return line.split(" = ", 1)[1]
    return ""


def _run_mutating_fake_gcloud(
    fake_gcloud: Path,
    target_project: str,
) -> tuple[str, str, str]:
    with ExecutionEnvironment(
        plan_id=f"plan-{target_project}",
        target_env="dev",
        target_project=target_project,
        cleanup=True,
    ) as env:
        proc = subprocess.run(
            [
                str(fake_gcloud),
                "config",
                "set",
                "project",
                f"other-{target_project}",
            ],
            capture_output=True,
            env=env.subprocess_env({"PATH": os.environ.get("PATH", "")}),
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr

        proc = subprocess.run(
            [str(fake_gcloud), "config", "get-value", "project"],
            capture_output=True,
            env=env.subprocess_env({"PATH": os.environ.get("PATH", "")}),
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr

        config_project = _read_config_project(
            Path(env.overlay()["CLOUDSDK_CONFIG"]) / "configurations" / "config_default"
        )
        return target_project, proc.stdout.strip(), config_project


def test_parallel_envs_isolate_gcloud_mutations() -> None:
    print("\n[test] parallel_envs_isolate_gcloud_mutations ...")
    with tempfile.TemporaryDirectory() as td:
        fake_gcloud = _make_fake_gcloud(Path(td))
        targets = ["jarvis-dev-a", "jarvis-dev-b"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda p: _run_mutating_fake_gcloud(fake_gcloud, p), targets))

    for target_project, effective_project, config_project in results:
        assert effective_project == target_project, (target_project, effective_project)
        assert config_project == f"other-{target_project}", (target_project, config_project)
    assert {r[2] for r in results} == {"other-jarvis-dev-a", "other-jarvis-dev-b"}
    print("  ✓ two parallel CLOUDSDK_CONFIG namespaces stayed independent")
    print("  ✓ CLOUDSDK_CORE_PROJECT pinned effective project per target")


def test_command_guard_forbidden_rejections() -> None:
    print("\n[test] command_guard_forbidden_rejections ...")
    forbidden = [
        "gcloud config set project prod",
        "gcloud config configurations activate prod",
        "firebase use --add prod",
        "kubectl config use-context prod",
        "gh auth switch",
        "npm config set registry https://registry.example.invalid",
        "yarn config set registry https://registry.example.invalid",
        "pnpm config set registry https://registry.example.invalid",
        "git config --global user.email ops@example.com",
        "docker context use prod",
    ]
    for command in forbidden:
        try:
            assert_allowed(command)
        except CommandRejected:
            continue
        raise AssertionError(f"expected rejection for {command!r}")

    allowed = [
        "gcloud services list --project=<firebase-project-id>",
        "firebase deploy --project <firebase-project-id>",
        "kubectl get pods --context dev",
        "gh pr view 1",
        "npm install --no-save",
        "git config --local user.email ops@example.com",
        "docker --context dev ps",
    ]
    for command in allowed:
        assert_allowed(command)
    assert_allowed(
        "gcloud config configurations activate dev",
        env={"CLOUDSDK_CONFIG": "/tmp/isolated"},
    )
    print("  ✓ forbidden global-state mutations rejected")
    print("  ✓ explicit/project-local command shapes accepted")


def test_soft_env_var_coverage() -> None:
    print("\n[test] soft_env_var_coverage ...")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "exec-env"
        with ExecutionEnvironment(
            plan_id="plan-soft-coverage",
            target_env="staging",
            target_project="jarvis-staging",
            root=root,
            cleanup=False,
        ) as env:
            overlay = env.overlay()

        expected = (
            set(ISOLATED_ENV_PATHS)
            | set(ISOLATED_ENV_FILES)
            | {
                "CLOUDSDK_CORE_PROJECT",
                "FIREBASE_PROJECT",
                "GCLOUD_PROJECT",
                "GOOGLE_CLOUD_PROJECT",
                "JARVIS_EXECUTION_ENV_ROOT",
                "JARVIS_TARGET_ENV",
                "JARVIS_TARGET_PROJECT",
            }
        )
        missing = expected - set(overlay)
        assert not missing, f"missing env keys: {sorted(missing)}"
        assert overlay["JARVIS_TARGET_ENV"] == "staging"
        assert overlay["JARVIS_TARGET_PROJECT"] == "jarvis-staging"
        for key in ISOLATED_ENV_PATHS:
            assert Path(overlay[key]).is_dir(), key
            assert str(Path(overlay[key])).startswith(str(root)), key
        for key in ISOLATED_ENV_FILES:
            assert Path(overlay[key]).is_file(), key
            assert str(Path(overlay[key])).startswith(str(root)), key
    print("  ✓ EC10 env namespace keys present")
    print("  ✓ target project/env keys are injected without relying on ambient shell state")


def test_executor_subprocess_receives_isolated_env() -> None:
    print("\n[test] executor_subprocess_receives_isolated_env ...")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        fake_claude = _make_fake_claude(tmp)
        with ExecutionEnvironment(
            plan_id="plan-executor-env",
            target_env="dev",
            target_project="jarvis-executor-test",
            root=tmp / "exec-env",
            cleanup=False,
        ) as env:
            task = DispatchTask(
                plan_id="plan-executor-env",
                plan_dir=tmp,
                feature_id="F023",
                feature_description="Synthetic executor env propagation test.",
                feature_acceptance="Fake Claude receives JARVIS_TARGET_PROJECT.",
                feature_steps=[],
                agent_role="implementer",
                subprocess_env=env.subprocess_env({"PATH": os.environ.get("PATH", "")}),
            )
            result = ClaudeCLIExecutor(binary=str(fake_claude)).dispatch(task)

    assert result.success, result.error
    assert result.summary == "jarvis-executor-test", result.summary
    print("  ✓ executor subprocess env wiring carries ExecutionEnvironment overlay")


class _EnvCapturingExecutor(BaseExecutor):
    """Scripted executor that records each dispatched task's subprocess_env."""

    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.captured_envs: list[dict[str, str]] = []

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.captured_envs.append(dict(task.subprocess_env or {}))
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=now,
            completed_at=now,
            success=True,
            summary=f"[env-capturing {self.agent_name}/{task.agent_role}] iter={task.iteration}",
            raw_response="captured",
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _make_volley_test_plan(tmp_dir: Path) -> Path:
    plan_id = "2026-04-25-004-infra-supervisor-env-wiring"
    plan_dir = tmp_dir / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    plan_md = f"""---
id: {plan_id}
title: F023 Step 1 supervisor env wiring synthetic
type: infra
tier: trivial
status: active
date: "2026-04-25"
description: Synthetic plan exercising dispatch_volley with ExecutionEnvironment wiring.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# F023 Step 1 supervisor env wiring synthetic

## Target

```yaml
target_env: dev
target_project: none
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
                "description": "Verify supervisor dispatch_volley threads ExecutionEnvironment through to subprocess_env.",
                "steps": ["scripted implementer", "scripted auditor"],
                "acceptance": "Volley runs once and the auditor signs off.",
                "passes": False,
                "depends_on": [],
            }
        ],
    }
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(
        json.dumps(features, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    )
    return plan_dir


def test_supervisor_volley_threads_isolated_env_to_executors() -> None:
    """Supervisor-path proof: dispatch_volley creates an ExecutionEnvironment
    and every executor subprocess receives the isolation overlay + an audit
    that records execution_env_root for operator visibility."""
    print("\n[test] supervisor_volley_threads_isolated_env_to_executors ...")

    from dontpanic_orchestrate import supervisor as sup
    from dontpanic_orchestrate.executors import AGENT_REGISTRY

    impl = _EnvCapturingExecutor("claude")
    aud = _EnvCapturingExecutor("codex")
    saved_registry = dict(AGENT_REGISTRY)
    saved_quota_gate = sup._quota_gate
    AGENT_REGISTRY["claude"] = lambda: impl
    AGENT_REGISTRY["codex"] = lambda: aud
    sup._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")

    try:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_volley_test_plan(Path(td))

            # Force the auditor to sign off after one round so the volley terminates fast.
            orig_run_round = sup._run_round

            def force_signoff(*args, **kwargs):
                path = orig_run_round(*args, **kwargs)
                if kwargs.get("role") == "auditor":
                    data = json.loads(path.read_text())
                    data["audit_status"] = "signed_off"
                    path.write_text(
                        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
                    )
                return path

            sup._run_round = force_signoff
            try:
                result = sup.dispatch_volley(
                    plan_dir,
                    "F001",
                    max_iterations=1,
                    target_env="dev",
                    target_project="jarvis-supervisor-test",
                )
            finally:
                sup._run_round = orig_run_round

            assert result.final_status == "signed_off", result.final_status
            assert len(impl.captured_envs) == 1, impl.captured_envs
            assert len(aud.captured_envs) == 1, aud.captured_envs

            for env in (*impl.captured_envs, *aud.captured_envs):
                assert "JARVIS_EXECUTION_ENV_ROOT" in env, sorted(env)
                assert env["JARVIS_TARGET_ENV"] == "dev", env.get("JARVIS_TARGET_ENV")
                assert env["JARVIS_TARGET_PROJECT"] == "jarvis-supervisor-test"
                assert env["CLOUDSDK_CORE_PROJECT"] == "jarvis-supervisor-test"
                for key in ISOLATED_ENV_PATHS:
                    assert env.get(key, "").startswith(env["JARVIS_EXECUTION_ENV_ROOT"]), key
                for key in ISOLATED_ENV_FILES:
                    assert env.get(key, "").startswith(env["JARVIS_EXECUTION_ENV_ROOT"]), key

            # All four rounds shared one env root (cleanup-on-volley-terminate contract).
            roots = {
                env["JARVIS_EXECUTION_ENV_ROOT"]
                for env in (*impl.captured_envs, *aud.captured_envs)
            }
            assert len(roots) == 1, roots
            shared_root = next(iter(roots))

            # Audit JSONs include the env root for operator visibility.
            audit_blobs = [json.loads(p.read_text()) for p in result.audit_paths]
            for audit in audit_blobs:
                joined = " ".join(audit.get("validation_performed") or [])
                assert shared_root in joined, joined
                assert "target_env=dev" in joined, joined
                assert "target_project=jarvis-supervisor-test" in joined, joined

            # Cleanup-on-terminate: the env root is removed after the volley returns.
            assert not Path(shared_root).exists(), shared_root

        print("  ✓ supervisor opens one ExecutionEnvironment per volley")
        print("  ✓ all rounds share the isolated env root and target overlay")
        print("  ✓ audit validation_performed records env root + target labels")
        print("  ✓ env root cleaned up on volley terminate")
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        sup._quota_gate = saved_quota_gate
