"""F005a synthetic disagreement test.

Uses MockExecutor classes to inject deterministic implementer/auditor responses
without dispatching to real CLIs. Verifies the volley loop:
  1. Iterates when auditor says needs_changes
  2. Terminates when auditor signs off
  3. Honors max_iterations cap
  4. Detects no-progress (verdict unchanged across 2 rounds)
  5. Threads prior auditor's findings into next implementer's prompt context

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_volley_synthetic.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

# Bootstrap import path
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import audit_writer, plan_loader, supervisor  # noqa: E402
from jarvis_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from jarvis_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _ScriptedExecutor(BaseExecutor):
    """Returns a sequence of (audit_status, summary) tuples on successive dispatches.

    The supervisor's audit_writer derives audit_status from result.success +
    findings list. To force a specific status, we inject findings of the right
    severity:
      - "signed_off"    → success + no findings
      - "needs_changes" → success + 1 high-severity finding
      - "blocked"       → success=False (forces blocked)
    """

    def __init__(self, agent: str, script: list[str]) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None  # bypass is_available default
        self._script = list(script)
        self._call_count = 0
        # Track received prompts so the test can verify findings threading
        self.received_prompts: list[str] = []

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        prompt = (task.extra_context or {}).get("prompt_override") or "(no override)"
        self.received_prompts.append(str(prompt))
        idx = self._call_count
        self._call_count += 1
        verdict = self._script[idx] if idx < len(self._script) else self._script[-1]

        if verdict == "blocked":
            return DispatchResult(
                agent=self.agent_name,
                agent_role=task.agent_role,
                iteration=task.iteration,
                started_at=_iso_now(),
                completed_at=_iso_now(),
                success=False,
                summary="",
                error="scripted blocked",
            )

        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=f"[scripted {self.agent_name}/{task.agent_role}] verdict={verdict} (iter={task.iteration})",
            model_version=None,
            raw_response=f"verdict:{verdict}",
            quota_consumed={"tokens_in": 100, "tokens_out": 50},
        )


def _patch_audit_status(plan_dir: Path, executor_scripts: dict[str, list[str]]) -> None:
    """After supervisor writes audits, the audit_writer derives status from findings.
    To force scripted statuses, monkey-patch the auditor's audit JSON post-write."""
    pass  # Handled below via _intercept_build_audit


def _make_test_plan(tmp_dir: Path) -> Path:
    """Create a tiny valid plan dir for testing."""
    plan_id = "2026-04-25-003-infra-volley-synthetic"
    plan_dir = tmp_dir / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)

    plan_md = """---
id: 2026-04-25-003-infra-volley-synthetic
title: Synthetic volley test
type: infra
tier: trivial
status: active
date: "2026-04-25"
description: Synthetic test plan exercising the F005a volley loop with scripted executors.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 3
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# Synthetic volley test

Used by tests/test_volley_synthetic.py — no real CLI dispatch.

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
                "description": "Synthetic feature exercising the volley loop with scripted executors.",
                "steps": ["scripted implementer", "scripted auditor"],
                "acceptance": "Volley loop terminates with the expected status per the script.",
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


def _override_status(plan_dir: Path, target_role: str, target_iteration: int, new_status: str) -> None:
    """Post-process: rewrite a freshly-written audit JSON to the scripted status.
    Schema doesn't enforce validation chain, so this is fine for the synthetic test."""
    audits_dir = plan_dir / "audit"
    for p in audits_dir.glob(f"*-{target_role}-i{target_iteration}.json"):
        data = json.loads(p.read_text())
        data["audit_status"] = new_status
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n")


def _patch_supervisor_to_force_status(verdict_script: list[str]) -> None:
    """Wrap supervisor._run_round to override auditor status post-write."""
    import jarvis_orchestrate.supervisor as sup
    orig = sup._run_round
    counter = {"i": 0}

    def wrapped(*args, **kwargs):
        path = orig(*args, **kwargs)
        role = kwargs.get("role")
        iteration = kwargs.get("iteration")
        if role == "auditor":
            idx = counter["i"]
            counter["i"] += 1
            verdict = verdict_script[idx] if idx < len(verdict_script) else verdict_script[-1]
            data = json.loads(path.read_text())
            data["audit_status"] = verdict
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
            )
        return path

    sup._run_round = wrapped


def _restore_supervisor() -> None:
    import importlib, jarvis_orchestrate.supervisor as sup
    importlib.reload(sup)


def _disable_quota_gate() -> None:
    import jarvis_orchestrate.supervisor as sup
    sup._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed for synthetic test")


def _register_scripted(impl_calls: int, aud_calls: int) -> tuple[_ScriptedExecutor, _ScriptedExecutor]:
    impl = _ScriptedExecutor("claude", ["ok"] * impl_calls)
    aud = _ScriptedExecutor("codex", ["ok"] * aud_calls)
    AGENT_REGISTRY["claude"] = lambda i=impl: i  # type: ignore[assignment]
    AGENT_REGISTRY["codex"] = lambda a=aud: a    # type: ignore[assignment]
    return impl, aud


# ────────────────────────────  test cases  ────────────────────────────


def test_iterates_then_signs_off() -> None:
    """Auditor: needs_changes → signed_off. Loop should run 2 rounds."""
    print("\n[test] iterates_then_signs_off ...")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plan_dir = _make_test_plan(tmp)

        impl, aud = _register_scripted(impl_calls=2, aud_calls=2)
        _disable_quota_gate()
        _patch_supervisor_to_force_status(["needs_changes", "signed_off"])

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)
        assert result.final_status == "signed_off", f"got {result.final_status}"
        assert result.rounds == 2, f"expected 2 rounds, got {result.rounds}"
        assert len(result.audit_paths) == 4, f"expected 4 audit files, got {len(result.audit_paths)}"

        # Round 1's implementer prompt should reference round 0's auditor path
        round1_impl_prompt = impl.received_prompts[1]
        assert "auditor produced findings" in round1_impl_prompt or "Prior round" in round1_impl_prompt, \
            "round 1 implementer prompt should thread prior auditor findings"

        print(f"  ✓ final_status={result.final_status}, rounds={result.rounds}, audits={len(result.audit_paths)}")
        print(f"  ✓ findings threaded into round 1 implementer prompt")


def test_no_progress_termination() -> None:
    """Auditor returns needs_changes twice in a row → trips no_progress OR
    diminishing_returns. F006 added diminishing_returns which fires first when
    the auditor's finding count is non-decreasing across needs_changes rounds
    (the synthetic fixture's constant-shape audits match this); both are
    valid F006 stop kinds for the same situation."""
    print("\n[test] no_progress_termination ...")
    _restore_supervisor()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plan_dir = _make_test_plan(tmp)

        impl, aud = _register_scripted(impl_calls=3, aud_calls=3)
        _disable_quota_gate()
        _patch_supervisor_to_force_status(["needs_changes", "needs_changes", "signed_off"])

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)
        assert result.final_status in {"stopped_no_progress", "stopped_diminishing_returns"}, \
            f"got {result.final_status}"
        assert result.rounds == 2, f"expected 2 rounds before stop trip, got {result.rounds}"
        print(f"  ✓ final_status={result.final_status}, rounds={result.rounds}")


def test_iteration_cap_termination() -> None:
    """Auditor flips needs/signed/needs (no two-in-a-row), cap=1 → stops at cap."""
    print("\n[test] iteration_cap_termination ...")
    _restore_supervisor()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plan_dir = _make_test_plan(tmp)

        impl, aud = _register_scripted(impl_calls=2, aud_calls=2)
        _disable_quota_gate()
        # cap=1 means 2 rounds (iter=0 + iter=1) max. Force needs_changes both.
        # But since both rounds will be needs_changes, no-progress will fire FIRST at iter=1.
        # To test pure cap, alternate: needs_changes (i0), inconclusive (i1) — different verdicts.
        _patch_supervisor_to_force_status(["needs_changes", "inconclusive"])

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
        assert result.final_status == "stopped_cap", f"got {result.final_status}"
        print(f"  ✓ final_status={result.final_status}, rounds={result.rounds}")


def test_auditor_prose_extracts_status_and_findings() -> None:
    """Real auditor prose must drive audit_status; otherwise live volleys false-signoff."""
    print("\n[test] auditor_prose_extracts_status_and_findings ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_test_plan(Path(td))
        loaded = plan_loader.load(plan_dir)
        result = DispatchResult(
            agent="codex",
            agent_role="auditor",
            iteration=0,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=(
                "Overall verdict: needs_changes. "
                "FINDING (high, test_coverage): Missing regression coverage for the volley no-progress path."
            ),
        )
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=["synthetic auditor prose parser"],
        )
        assert audit["audit_status"] == "needs_changes", audit
        assert audit["findings"][0]["severity"] == "high", audit
        assert audit["findings"][0]["category"] == "test_coverage", audit
        print("  ✓ auditor prose produces needs_changes + structured finding")


def main() -> int:
    test_iterates_then_signs_off()
    test_no_progress_termination()
    test_iteration_cap_termination()
    test_auditor_prose_extracts_status_and_findings()
    print("\n✓ all 4 synthetic volley tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
