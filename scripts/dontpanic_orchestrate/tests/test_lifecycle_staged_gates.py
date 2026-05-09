"""Plan 2026-05-04-002 F001 — lifecycle-staged human-gate tests.

These tests pin the behavior that was missing from the volley output:
``pre_impl`` and ``pre_merge`` are no longer upfront gates. They fire at their
canonical lifecycle points, while breaker/defer gates keep their existing
timing.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    gate_pause,
    inbox,
    notify,
    signoff_writer,
    supervisor,
)
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _summary(agent: str, role: str, status: str = "signed_off") -> str:
    return (
        "Repo: synthetic\n"
        "Env: dev\n"
        "Project: (none)\n\n"
        "## Target context\n"
        "Repo: synthetic\n"
        "Env: dev\n"
        "Project: (none)\n\n"
        f"Overall verdict: {status}.\n"
        f"{agent}/{role} completed the scripted lifecycle-gate test."
    )


class _ScriptedExecutor(BaseExecutor):
    def __init__(
        self,
        agent: str,
        *,
        order: list[str],
        success: bool = True,
        status: str = "signed_off",
    ) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.order = order
        self.success = success
        self.status = status
        self.dispatches: list[DispatchTask] = []

    def is_available(self) -> bool:
        self.order.append(f"available:{self.agent_name}")
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.order.append(f"dispatch:{task.agent_role}:{task.iteration}")
        self.dispatches.append(task)
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=self.success,
            summary=_summary(self.agent_name, task.agent_role, self.status),
            raw_response=_summary(self.agent_name, task.agent_role, self.status),
            error=None if self.success else "scripted timeout-like failure",
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _make_plan(tmp_path: Path, plan_id: str, gates: list[str], max_iterations: int = 1) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    gates_yaml = "\n".join(f"  - {gate}" for gate in gates)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: Lifecycle staged gates synthetic
type: infra
tier: trivial
status: active
date: "2026-05-04"
description: Synthetic plan for lifecycle-staged human-gate tests.
agents_required:
  - claude
  - codex
human_gates:
{gates_yaml}
loop_caps:
  max_iterations: {max_iterations}
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# Lifecycle staged gates synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "test",
                        "phase": 0,
                        "description": "Synthetic lifecycle-gate feature.",
                        "steps": ["scripted"],
                        "acceptance": "Lifecycle gates fire at the right stages.",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return plan_dir


def _install_runtime(
    monkeypatch: pytest.MonkeyPatch, impl: BaseExecutor, aud: BaseExecutor
) -> None:
    monkeypatch.setenv(notify.DISABLE_ENV, "1")
    monkeypatch.setitem(AGENT_REGISTRY, "claude", lambda: impl)
    monkeypatch.setitem(AGENT_REGISTRY, "codex", lambda: aud)
    monkeypatch.setattr(
        supervisor,
        "_quota_gate",
        lambda agent: (None, f"[quota] {agent}: bypassed for lifecycle test"),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "evaluate_global",
        lambda: supervisor.circuit_breakers.GlobalBreakerState(False, 0),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_wall_clock",
        lambda *args, **kwargs: (False, ""),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_budget_ceiling",
        lambda *args, **kwargs: supervisor.circuit_breakers.BudgetCeilingResult(
            supervisor.circuit_breakers.BudgetCeilingKind.OK,
            False,
            "",
        ),
    )
    monkeypatch.setattr(
        supervisor.quota_admission,
        "evaluate",
        lambda *args, **kwargs: supervisor.quota_admission.AdmissionCheck(
            supervisor.quota_admission.DispatchClass.AUTONOMOUS,
            supervisor.quota_admission.QuotaCheck(False, None, None, 90.0),
            supervisor.quota_admission.InteractiveCheck(False, None),
            frozenset(),
        ),
    )


from dontpanic_orchestrate.tests.conftest import _rewrite_summary_verdict  # noqa: E402


def _force_auditor_status(monkeypatch: pytest.MonkeyPatch, statuses: list[str]) -> None:
    original = supervisor._run_round
    counter = {"i": 0}

    def wrapped(*args: Any, **kwargs: Any) -> Path:
        path = original(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            idx = counter["i"]
            counter["i"] += 1
            status = statuses[idx] if idx < len(statuses) else statuses[-1]
            data = json.loads(path.read_text())
            data["audit_status"] = status
            # Plan 2026-05-09-002 F001 — keep summary's narrative verdict
            # consistent with the overridden structured field; otherwise the
            # supervisor's verdict-mismatch detector fires on what is just
            # test-fixture drift between the executor's static `_summary`
            # and the wrapper's status override.
            data["summary"] = _rewrite_summary_verdict(data.get("summary", ""), status)
            path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    monkeypatch.setattr(supervisor, "_run_round", wrapped)


def _preclear_stage(plan_dir: Path, plan_id: str, stage: str) -> None:
    gate_pause.record_pause(plan_dir, plan_id=plan_id, pause_gates=[stage], stage=stage)
    assert gate_pause.approve_gate(plan_dir, stage, plan_id=plan_id)


def test_pre_impl_pauses_after_executor_resolution_before_implementer_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    impl = _ScriptedExecutor("claude", order=order)
    aud = _ScriptedExecutor("codex", order=order)
    _install_runtime(monkeypatch, impl, aud)
    plan_dir = _make_plan(tmp_path, "2026-05-04-901-infra-pre-impl-order", ["pre_impl"])

    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert result.final_status == "paused_on_gate", result
    assert order == ["available:claude", "available:codex"], order
    assert not impl.dispatches and not aud.dispatches
    state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
    assert state["pending_stage"] == "pre_impl"
    assert state["pause_gates"] == ["pre_impl"]


def test_clearing_pre_impl_allows_implementation_then_pre_merge_pauses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    impl = _ScriptedExecutor("claude", order=order)
    aud = _ScriptedExecutor("codex", order=order)
    _install_runtime(monkeypatch, impl, aud)
    plan_id = "2026-05-04-902-infra-pre-merge-after-audit"
    plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl", "pre_merge"])

    first = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert first.final_status == "paused_on_gate"
    assert gate_pause.pending_stage(plan_dir) == "pre_impl"
    assert gate_pause.approve_gate(plan_dir, "pre_impl", plan_id=plan_id)

    second = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert second.final_status == "paused_on_gate", second
    assert len(impl.dispatches) == 1 and len(aud.dispatches) == 1
    assert gate_pause.pending_stage(plan_dir) == "pre_merge"
    assert not signoff_writer.signoff_path(plan_dir, plan_id).exists()
    stages = [e.headers.get("stage") for e in inbox.read_events(plan_dir) if e.event == "gate_hit"]
    assert stages[-2:] == ["pre_impl", "pre_merge"], stages


def test_pre_merge_cleared_success_path_writes_signoff_after_stage_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    impl = _ScriptedExecutor("claude", order=order)
    aud = _ScriptedExecutor("codex", order=order)
    _install_runtime(monkeypatch, impl, aud)
    plan_id = "2026-05-04-903-infra-pre-merge-success"
    plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl", "pre_merge"])
    _preclear_stage(plan_dir, plan_id, "pre_impl")
    _preclear_stage(plan_dir, plan_id, "pre_merge")

    calls: list[str] = []
    original_eval = gate_pause.evaluate_human_gates
    original_signoff = signoff_writer.write_signoff

    def eval_wrapper(*args: Any, **kwargs: Any):
        if kwargs.get("stage") == "pre_merge":
            calls.append("eval_pre_merge")
        return original_eval(*args, **kwargs)

    def signoff_wrapper(*args: Any, **kwargs: Any):
        calls.append("write_signoff")
        return original_signoff(*args, **kwargs)

    monkeypatch.setattr(gate_pause, "evaluate_human_gates", eval_wrapper)
    monkeypatch.setattr(signoff_writer, "write_signoff", signoff_wrapper)

    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert result.final_status == "signed_off", result
    assert calls == ["write_signoff"], calls
    assert signoff_writer.signoff_path(plan_dir, plan_id).is_file()


@pytest.mark.parametrize(
    ("name", "auditor_statuses", "impl_success", "patch_breaker"),
    [
        ("needs_changes", ["needs_changes"], True, None),
        ("blocked", ["blocked"], True, None),
        ("stopped_no_progress", ["needs_changes", "needs_changes"], True, "no_progress"),
        (
            "stopped_diminishing_returns",
            ["needs_changes", "needs_changes"],
            True,
            "diminishing_returns",
        ),
        ("timeout_like_blocked", ["blocked"], False, None),
    ],
)
def test_pre_merge_does_not_fire_on_non_success_terminals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    auditor_statuses: list[str],
    impl_success: bool,
    patch_breaker: str | None,
) -> None:
    order: list[str] = []
    impl = _ScriptedExecutor("claude", order=order, success=impl_success)
    aud = _ScriptedExecutor("codex", order=order)
    _install_runtime(monkeypatch, impl, aud)
    plan_id = f"2026-05-04-904-infra-{name.replace('_', '-')}"
    plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl", "pre_merge"], max_iterations=1)
    _preclear_stage(plan_dir, plan_id, "pre_impl")
    _force_auditor_status(monkeypatch, auditor_statuses)

    if patch_breaker == "no_progress":
        monkeypatch.setattr(
            supervisor.circuit_breakers,
            "check_diminishing_returns",
            lambda *args, **kwargs: (False, ""),
        )
    if patch_breaker == "diminishing_returns":
        monkeypatch.setattr(
            supervisor.circuit_breakers,
            "check_diminishing_returns",
            lambda audit_paths: (
                len(audit_paths) >= 4,
                "synthetic diminishing returns",
            ),
        )

    pre_merge_calls: list[str] = []
    original_eval = gate_pause.evaluate_human_gates

    def eval_wrapper(*args: Any, **kwargs: Any):
        if kwargs.get("stage") == "pre_merge":
            pre_merge_calls.append("pre_merge")
        return original_eval(*args, **kwargs)

    monkeypatch.setattr(gate_pause, "evaluate_human_gates", eval_wrapper)

    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert result.final_status != "signed_off", result
    assert pre_merge_calls == []
    assert result.audit_paths, "failure evidence should still be written"
    assert all(path.is_file() for path in result.audit_paths)


def test_legacy_upfront_cleared_gate_state_is_treated_as_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    impl = _ScriptedExecutor("claude", order=order)
    aud = _ScriptedExecutor("codex", order=order)
    _install_runtime(monkeypatch, impl, aud)
    plan_id = "2026-05-04-905-infra-legacy-state"
    plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl", "pre_merge"])
    gate_pause.gate_state_path(plan_dir).parent.mkdir(parents=True)
    gate_pause.gate_state_path(plan_dir).write_text(
        json.dumps(
            {
                "plan_id": plan_id,
                "cleared_gates": {"pre_impl": True, "pre_merge": True},
                "history": [{"action": "legacy_clear"}],
            },
            indent=2,
        )
        + "\n"
    )

    compat = gate_pause.load_gate_state_compat(plan_dir)
    assert compat.cleared_gates == ["pre_impl", "pre_merge"]
    assert compat.pending_stage is None
    assert compat.gate_events == []

    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert result.final_status == "signed_off", result
    assert len(impl.dispatches) == 1 and len(aud.dispatches) == 1


def test_new_gate_state_shape_round_trips_pending_and_gate_events(tmp_path: Path) -> None:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    gate_pause.record_pause(plan_dir, plan_id="p", pause_gates=["pre_impl"], stage="pre_impl")
    pending = gate_pause.load_gate_state_compat(plan_dir)
    assert pending.pending_stage == "pre_impl"
    assert pending.gate_events == []

    assert gate_pause.approve_gate(plan_dir, "pre_impl", plan_id="p")
    cleared = gate_pause.load_gate_state_compat(plan_dir)
    assert cleared.pending_stage is None
    assert cleared.cleared_gates == ["pre_impl"]
    assert cleared.gate_events == [
        {
            "gate": "pre_impl",
            "stage": "pre_impl",
            "cleared_at": cleared.gate_events[0]["cleared_at"],
            "cleared_by": "operator",
        }
    ]
    assert gate_pause.is_stage_completed(plan_dir, "pre_impl")


def test_resume_all_clears_current_stage_only(tmp_path: Path) -> None:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    gate_pause.record_pause(plan_dir, plan_id="p", pause_gates=["pre_impl"], stage="pre_impl")
    cleared = gate_pause.resume_all(
        plan_dir,
        plan_id="p",
        declared_gates=["pre_impl", "pre_merge"],
    )

    assert cleared == ["pre_impl"]
    state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
    assert state["cleared_gates"] == ["pre_impl"]
    assert "pre_merge" not in state["cleared_gates"]


def test_breaker_gate_timing_remains_upfront_and_unstaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    impl = _ScriptedExecutor("claude", order=order)
    aud = _ScriptedExecutor("codex", order=order)
    _install_runtime(monkeypatch, impl, aud)
    plan_id = "2026-05-04-906-infra-breaker-upfront"
    plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl", "pre_merge"])
    gate_pause.add_breaker(
        plan_dir,
        "breaker:wall_clock",
        plan_id=plan_id,
        reason="synthetic breaker",
    )

    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert result.final_status == "paused_on_gate", result
    assert "breaker:wall_clock" in result.reason
    assert gate_pause.pending_stage(plan_dir) is None
    assert order == []


def test_stage_completion_skips_re_evaluation_on_later_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    impl = _ScriptedExecutor("claude", order=order)
    aud = _ScriptedExecutor("codex", order=order)
    _install_runtime(monkeypatch, impl, aud)
    plan_id = "2026-05-04-907-infra-stage-idempotency"
    plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl", "pre_merge"])
    _preclear_stage(plan_dir, plan_id, "pre_impl")
    _preclear_stage(plan_dir, plan_id, "pre_merge")

    calls: list[str] = []
    original_eval = gate_pause.evaluate_human_gates

    def eval_wrapper(*args: Any, **kwargs: Any):
        calls.append(str(kwargs.get("stage")))
        return original_eval(*args, **kwargs)

    monkeypatch.setattr(gate_pause, "evaluate_human_gates", eval_wrapper)

    first = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    second = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert first.final_status == "signed_off", first
    assert second.final_status == "signed_off", second
    assert calls == []
