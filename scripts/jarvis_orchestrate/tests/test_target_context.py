"""F023 Step 3 (EC3 + EC4 + EC5 + EC6) — target_context + asymmetric reject + post-hoc command_guard.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_target_context.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import audit_writer, plan_loader, prompts, supervisor  # noqa: E402
from jarvis_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from jarvis_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)

# ──────────────────────────────  fixtures  ──────────────────────────────


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_plan(tmp: Path, plan_id: str, target_project: str = "jarvis-a6ee1") -> Path:
    plan_dir = tmp / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    project_yaml = target_project if target_project else "none"
    plan_md = f"""---
id: {plan_id}
title: F023 step 3 synthetic
type: infra
tier: trivial
status: active
date: "2026-04-26"
description: Synthetic plan for F023 EC3/EC5/EC6 tests.
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

# F023 step 3 synthetic

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
                "description": "Synthetic feature for F023 step 3 tests.",
                "steps": ["scripted"],
                "acceptance": "Volley produces accountable audits.",
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


def _result(role: str, summary: str, agent: str = "claude") -> DispatchResult:
    return DispatchResult(
        agent=agent,
        agent_role=role,
        iteration=0,
        started_at=_iso_now(),
        completed_at=_iso_now(),
        success=True,
        summary=summary,
        raw_response=summary,
        quota_consumed={"tokens_in": 1, "tokens_out": 1},
    )


# ──────────────────────────────  audit_writer.extract_commands_run  ──────────────────────────────


def test_extract_commands_run_picks_up_dollar_lines() -> None:
    print("\n[test] extract_commands_run_picks_up_dollar_lines ...")
    summary = """I deployed the build.
Repo: Jarvis
Env: dev
Project: jarvis-a6ee1

$ gcloud services list --project=jarvis-a6ee1
Looked at the output.
$ firebase deploy --project jarvis-a6ee1 --only hosting
Done.
"""
    cmds = audit_writer.extract_commands_run(summary)
    assert cmds == [
        "gcloud services list --project=jarvis-a6ee1",
        "firebase deploy --project jarvis-a6ee1 --only hosting",
    ], cmds
    print("  ✓ `$ <cmd>` line prefix extracted into commands_run[]")


def test_extract_commands_run_empty_when_no_markers() -> None:
    print("\n[test] extract_commands_run_empty_when_no_markers ...")
    assert audit_writer.extract_commands_run("Just prose, no commands.") == []
    print("  ✓ summary without `$ ` markers returns empty list")


# ──────────────────────────────  audit_writer.build_audit target_context  ──────────────────────────────


def test_build_audit_populates_target_context() -> None:
    print("\n[test] build_audit_populates_target_context ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td), "2026-04-26-008-infra-target-context-build")
        loaded = plan_loader.load(plan_dir)
        result = _result(
            "implementer",
            "Repo: Jarvis\nEnv: dev\nProject: jarvis-a6ee1\n$ gcloud services list --project=jarvis-a6ee1",
        )
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=["test"],
            target_context={"env": "dev", "project": "jarvis-a6ee1"},
        )
        tc = audit["target_context"]
        assert tc["env"] == "dev"
        assert tc["project"] == "jarvis-a6ee1"
        assert tc["commands_run"] == ["gcloud services list --project=jarvis-a6ee1"]
    print("  ✓ build_audit sets target_context.env/project from kwarg + commands_run from summary")


def test_build_audit_target_context_project_null_when_sentinel() -> None:
    print("\n[test] build_audit_target_context_project_null_when_sentinel ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(
            Path(td), "2026-04-26-009-infra-target-context-sentinel", target_project="none"
        )
        loaded = plan_loader.load(plan_dir)
        result = _result("implementer", "Repo: Jarvis\nEnv: dev\nProject: (host-local)")
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=["test"],
            target_context={"env": "dev", "project": None},
        )
        assert audit["target_context"]["project"] is None
    print("  ✓ target_context.project=None preserved through build_audit")


# ──────────────────────────────  supervisor accountability validation  ──────────────────────────────


def test_implementer_missing_env_declaration_downgraded_to_needs_changes() -> None:
    print("\n[test] implementer_missing_env_declaration_downgraded_to_needs_changes ...")
    audit = {
        "audit_status": "signed_off",
        "agent_role": "implementer",
        "findings": [],
        "summary": "I shipped some code.",
        "target_context": {"env": "dev", "project": "jarvis-a6ee1", "commands_run": []},
    }
    supervisor._apply_target_accountability(
        audit, role="implementer", plan_target_env="dev", plan_target_project="jarvis-a6ee1"
    )
    assert audit["audit_status"] == "needs_changes", audit["audit_status"]
    assert any("Env" in f.get("issue", "") for f in audit["findings"]), audit["findings"]
    print(
        "  ✓ implementer summary missing `Env:` declaration → needs_changes + finding (non-terminal)"
    )


def test_auditor_env_mismatch_forces_blocked() -> None:
    print("\n[test] auditor_env_mismatch_forces_blocked ...")
    audit = {
        "audit_status": "signed_off",
        "agent_role": "auditor",
        "findings": [],
        "summary": "Repo: Jarvis\nEnv: prod\nProject: jarvis-a6ee1\nLooks fine.",
        "target_context": {"env": "dev", "project": "jarvis-a6ee1", "commands_run": []},
    }
    supervisor._apply_target_accountability(
        audit, role="auditor", plan_target_env="dev", plan_target_project="jarvis-a6ee1"
    )
    assert audit["audit_status"] == "blocked", audit["audit_status"]
    assert any("env" in f.get("issue", "").lower() for f in audit["findings"]), audit["findings"]
    print("  ✓ auditor declaring different env than plan target → blocked + stop volley")


def test_clean_implementer_unchanged() -> None:
    print("\n[test] clean_implementer_unchanged ...")
    audit = {
        "audit_status": "signed_off",
        "agent_role": "implementer",
        "findings": [],
        "summary": "Repo: Jarvis\nEnv: dev\nProject: jarvis-a6ee1\nDone.",
        "target_context": {"env": "dev", "project": "jarvis-a6ee1", "commands_run": []},
    }
    supervisor._apply_target_accountability(
        audit, role="implementer", plan_target_env="dev", plan_target_project="jarvis-a6ee1"
    )
    assert audit["audit_status"] == "signed_off", audit["audit_status"]
    assert audit["findings"] == [], audit["findings"]
    print("  ✓ matching declaration with no forbidden commands → audit untouched")


def test_implementer_forbidden_command_downgraded_with_finding() -> None:
    print("\n[test] implementer_forbidden_command_downgraded_with_finding ...")
    audit = {
        "audit_status": "signed_off",
        "agent_role": "implementer",
        "findings": [],
        "summary": "Repo: Jarvis\nEnv: dev\nProject: jarvis-a6ee1\nDone.",
        "target_context": {
            "env": "dev",
            "project": "jarvis-a6ee1",
            "commands_run": ["gcloud config set project wrong-project"],
        },
    }
    supervisor._apply_target_accountability(
        audit, role="implementer", plan_target_env="dev", plan_target_project="jarvis-a6ee1"
    )
    assert audit["audit_status"] == "needs_changes", audit["audit_status"]
    assert any(
        "forbidden" in f.get("issue", "").lower() or "command" in f.get("issue", "").lower()
        for f in audit["findings"]
    ), audit["findings"]
    fin = next(
        f
        for f in audit["findings"]
        if "command" in f.get("issue", "").lower() or "forbidden" in f.get("issue", "").lower()
    )
    assert fin["severity"] in {"high", "critical"}, fin["severity"]
    assert fin["category"] == "security", fin["category"]
    print(
        "  ✓ implementer commands_run with forbidden pattern → needs_changes + high/security finding"
    )


def test_auditor_forbidden_command_blocks_volley() -> None:
    print("\n[test] auditor_forbidden_command_blocks_volley ...")
    audit = {
        "audit_status": "signed_off",
        "agent_role": "auditor",
        "findings": [],
        "summary": "Repo: Jarvis\nEnv: dev\nProject: jarvis-a6ee1\nReviewed.",
        "target_context": {
            "env": "dev",
            "project": "jarvis-a6ee1",
            "commands_run": ["firebase use --add prod"],
        },
    }
    supervisor._apply_target_accountability(
        audit, role="auditor", plan_target_env="dev", plan_target_project="jarvis-a6ee1"
    )
    assert audit["audit_status"] == "blocked", audit["audit_status"]
    print("  ✓ auditor commands_run with forbidden pattern → blocked + stop volley")


def test_target_project_none_skips_project_declaration_check() -> None:
    print("\n[test] target_project_none_skips_project_declaration_check ...")
    audit = {
        "audit_status": "signed_off",
        "agent_role": "implementer",
        "findings": [],
        "summary": "Repo: Jarvis\nEnv: dev\n(no project — host-local plan)",
        "target_context": {"env": "dev", "project": None, "commands_run": []},
    }
    supervisor._apply_target_accountability(
        audit, role="implementer", plan_target_env="dev", plan_target_project=None
    )
    assert audit["audit_status"] == "signed_off", audit["audit_status"]
    print("  ✓ host-local plan (target_project=None) skips project-declaration check")


# ──────────────────────────────  prompt content  ──────────────────────────────


def test_implementer_prompt_includes_target_declaration_rule() -> None:
    print("\n[test] implementer_prompt_includes_target_declaration_rule ...")
    out = prompts.implementer_prompt(
        plan_id="p",
        plan_dir=Path("/tmp/p"),
        feature={"id": "F001", "description": "x", "acceptance": "y", "steps": []},
        iteration=0,
        target_env="dev",
        target_project="jarvis-a6ee1",
    )
    assert "Repo:" in out and "Env:" in out and "Project:" in out, out
    assert "$ " in out, out  # Command-line marker convention documented
    assert "dev" in out and "jarvis-a6ee1" in out, "must inject the actual target"
    print(
        "  ✓ implementer prompt includes {repo, env, project} declaration rule + `$ ` marker convention"
    )


def test_implementer_prompt_lists_forbidden_commands() -> None:
    print("\n[test] implementer_prompt_lists_forbidden_commands ...")
    out = prompts.implementer_prompt(
        plan_id="p",
        plan_dir=Path("/tmp/p"),
        feature={"id": "F001", "description": "x", "acceptance": "y", "steps": []},
        iteration=0,
        target_env="dev",
        target_project="jarvis-a6ee1",
    )
    assert "gcloud config set project" in out, out
    assert "firebase use" in out, out
    assert "kubectl config use-context" in out, out
    print("  ✓ implementer prompt enumerates forbidden command patterns")


def test_auditor_prompt_includes_target_verification_rule() -> None:
    print("\n[test] auditor_prompt_includes_target_verification_rule ...")
    out = prompts.auditor_prompt(
        plan_id="p",
        plan_dir=Path("/tmp/p"),
        feature={"id": "F001", "description": "x", "acceptance": "y", "steps": []},
        iteration=0,
        implementer_audit_path=Path("/tmp/p/audit/claude-implementer-i0.json"),
        target_env="dev",
        target_project="jarvis-a6ee1",
    )
    assert "Env:" in out or "target_env" in out, out
    assert "dev" in out and "jarvis-a6ee1" in out, out
    print("  ✓ auditor prompt verifies target declarations against plan target")


def test_implementer_prompt_handles_target_project_none() -> None:
    print("\n[test] implementer_prompt_handles_target_project_none ...")
    out = prompts.implementer_prompt(
        plan_id="p",
        plan_dir=Path("/tmp/p"),
        feature={"id": "F001", "description": "x", "acceptance": "y", "steps": []},
        iteration=0,
        target_env="dev",
        target_project=None,
    )
    assert "host-local" in out.lower() or "no cloud project" in out.lower() or "(none)" in out, out
    print("  ✓ host-local plan: prompt notes no cloud project rather than injecting fake value")


# ──────────────────────────────  supervisor end-to-end  ──────────────────────────────


class _FixedSummaryExecutor(BaseExecutor):
    """Returns scripted summaries per dispatch (cycles through if exhausted)."""

    def __init__(self, agent: str, summaries: list[str]) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self._summaries = list(summaries)
        self._idx = 0
        self.received_envs: list[dict[str, str]] = []

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.received_envs.append(dict(task.subprocess_env or {}))
        s = self._summaries[self._idx] if self._idx < len(self._summaries) else self._summaries[-1]
        self._idx += 1
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


def _run_volley(
    plan_dir: Path, impl_summary: str, aud_summary: str, force_status: str | None = None
):
    impl = _FixedSummaryExecutor("claude", [impl_summary])
    aud = _FixedSummaryExecutor("codex", [aud_summary])
    saved_registry = dict(AGENT_REGISTRY)
    saved_quota_gate = supervisor._quota_gate
    AGENT_REGISTRY["claude"] = lambda: impl
    AGENT_REGISTRY["codex"] = lambda: aud
    supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")

    orig_run_round = supervisor._run_round

    def maybe_force(*args, **kwargs):
        path = orig_run_round(*args, **kwargs)
        if force_status and kwargs.get("role") == "auditor":
            data = json.loads(path.read_text())
            # Only overwrite if the natural pipeline didn't already produce a more severe state
            if data.get("audit_status") == "signed_off":
                data["audit_status"] = force_status
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return path

    supervisor._run_round = maybe_force
    # F008: pre-clear declared gates so this Step-3 fixture doesn't pause on
    # the new engagement-surface gate-pause check.
    from jarvis_orchestrate import gate_pause
    from jarvis_orchestrate import plan_loader as _pl

    _loaded_for_gates = _pl.load(plan_dir)
    gate_pause.resume_all(
        plan_dir,
        plan_id=_loaded_for_gates.plan_id,
        declared_gates=list(_loaded_for_gates.plan.human_gates or []),
    )
    try:
        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    finally:
        supervisor._run_round = orig_run_round
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        supervisor._quota_gate = saved_quota_gate
    return result, impl, aud


def test_supervisor_volley_implementer_mismatch_continues_to_auditor() -> None:
    """Implementer declares wrong env → audit downgraded to needs_changes, but auditor still runs."""
    print("\n[test] supervisor_volley_implementer_mismatch_continues_to_auditor ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td), "2026-04-26-010-infra-impl-mismatch-continues")
        impl_bad = "Repo: Jarvis\nEnv: prod\nProject: jarvis-a6ee1\nI shipped to prod."
        aud_clean = "Repo: Jarvis\nEnv: dev\nProject: jarvis-a6ee1\nReviewed; signed off."
        result, impl, aud = _run_volley(plan_dir, impl_bad, aud_clean)
        assert len(result.audit_paths) >= 2, "auditor must have run after implementer mismatch"
        impl_audit = json.loads(result.audit_paths[0].read_text())
        assert impl_audit["audit_status"] == "needs_changes", impl_audit["audit_status"]
        assert any("env" in f.get("issue", "").lower() for f in impl_audit.get("findings") or [])
    print("  ✓ implementer env mismatch produces needs_changes + finding, auditor still dispatched")


def test_supervisor_volley_auditor_mismatch_blocks() -> None:
    """Auditor declares wrong env → audit_status=blocked, volley terminates blocked."""
    print("\n[test] supervisor_volley_auditor_mismatch_blocks ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td), "2026-04-26-011-infra-aud-mismatch-blocks")
        impl_clean = "Repo: Jarvis\nEnv: dev\nProject: jarvis-a6ee1\nDone."
        aud_bad = "Repo: Jarvis\nEnv: prod\nProject: jarvis-a6ee1\nLooks fine."
        result, impl, aud = _run_volley(plan_dir, impl_clean, aud_bad)
        assert result.final_status == "blocked", result.final_status
        aud_audit = json.loads(result.audit_paths[-1].read_text())
        assert aud_audit["audit_status"] == "blocked"
    print("  ✓ auditor env mismatch forces blocked + stops volley")


def test_supervisor_volley_audit_includes_target_context() -> None:
    """Every audit produced by a volley includes a target_context populated from plan target."""
    print("\n[test] supervisor_volley_audit_includes_target_context ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td), "2026-04-26-012-infra-tc-emitted")
        impl_ok = "Repo: Jarvis\nEnv: dev\nProject: jarvis-a6ee1\n$ gcloud services list --project=jarvis-a6ee1"
        aud_ok = "Repo: Jarvis\nEnv: dev\nProject: jarvis-a6ee1\nReviewed."
        result, impl, aud = _run_volley(plan_dir, impl_ok, aud_ok, force_status="signed_off")
        assert result.final_status == "signed_off", result.final_status
        for path in result.audit_paths:
            data = json.loads(path.read_text())
            tc = data.get("target_context") or {}
            assert tc.get("env") == "dev", tc
            assert tc.get("project") == "jarvis-a6ee1", tc
        # Implementer audit should have parsed the gcloud command
        impl_audit = json.loads(result.audit_paths[0].read_text())
        assert "gcloud services list --project=jarvis-a6ee1" in (
            (impl_audit.get("target_context") or {}).get("commands_run") or []
        )
    print("  ✓ supervisor populates target_context in every audit; commands_run parsed from prose")
