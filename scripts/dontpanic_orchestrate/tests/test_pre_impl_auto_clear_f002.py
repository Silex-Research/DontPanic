"""Plan 2026-05-08-003 F002 — narrow `pre_impl` auto-clear tests.

Pins the dispatch-time carve-out for direct operator CLI dispatch in
eligible dev/test contexts. The carve-out must be conservative — D005's
boundaries (no prod/protected, no multi-gate states, no programmatic
dispatch) are the failure modes operators care about.

Acceptance items pinned here:
  (1) eligible dev/test direct dispatch with only pending pre_impl
      proceeds without a separate approve/resume command;
  (2) gate-state event log records the clearance with the
      ``supervisor:auto_clear_pre_impl`` actor;
  (3) INBOX records ``event=auto_cleared_pre_impl`` with command context;
  (4) prod/protected target_env refuses (operator pause path runs);
  (5) multi-gate stage (e.g. pre_impl + pre_merge declared with both
      pending) refuses;
  (6) manual approve/resume paths remain unchanged (covered by the
      existing test_cli_resume + test_lifecycle_staged_gates suites,
      asserted here through default-False direct_dispatch refusal);
  (7) implementer round runs only AFTER the auto-clear decision.
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
        f"{agent}/{role} completed the scripted F002 auto-clear test."
    )


class _ScriptedExecutor(BaseExecutor):
    """Minimal executor mirroring the lifecycle-gate test executor so the
    F002 cases use the same plumbing as F001's lifecycle suite."""

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


def _make_plan(
    tmp_path: Path,
    plan_id: str,
    gates: list[str],
    *,
    target_env: str = "dev",
) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    gates_yaml = "\n".join(f"  - {gate}" for gate in gates)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F002 auto-clear synthetic
type: infra
tier: trivial
status: active
date: "2026-05-08"
description: Synthetic plan for F002 dispatch-time pre_impl auto-clear tests.
agents_required:
  - claude
  - codex
human_gates:
{gates_yaml}
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# F002 auto-clear synthetic

## Target

```yaml
target_env: {target_env}
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
                        "description": "Synthetic feature.",
                        "steps": ["scripted"],
                        "acceptance": "ok",
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
    """Stub out admission/breaker/notify so dispatch_volley can run end-to-end
    against scripted executors without touching real quota state."""
    monkeypatch.setenv(notify.DISABLE_ENV, "1")
    monkeypatch.setitem(AGENT_REGISTRY, "claude", lambda: impl)
    monkeypatch.setitem(AGENT_REGISTRY, "codex", lambda: aud)
    monkeypatch.setattr(
        supervisor,
        "_quota_gate",
        lambda agent: (None, f"[quota] {agent}: bypassed for F002 test"),
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


# ---------------------------------------------------------------------------
# 1. Direct unit tests on _maybe_auto_clear_pre_impl
# ---------------------------------------------------------------------------


class TestMaybeAutoClearDirect:
    def _loaded_plan(self, tmp_path: Path, plan_id: str, gates: list[str]):
        plan_dir = _make_plan(tmp_path, plan_id, gates)
        from dontpanic_orchestrate import plan_loader

        return plan_loader.load(plan_dir)

    def test_default_direct_dispatch_false_refuses(self, tmp_path: Path) -> None:
        loaded = self._loaded_plan(
            tmp_path, "2026-05-08-920-fix-default-no-auto", ["pre_impl"]
        )
        gate_pause.record_pause(
            loaded.plan_dir, plan_id=loaded.plan_id, pause_gates=["pre_impl"], stage="pre_impl"
        )

        result = supervisor._maybe_auto_clear_pre_impl(
            loaded=loaded,
            declared_gates=list(loaded.plan.human_gates or []),
            direct_dispatch=False,
            effective_env="dev",
            effective_project=None,
            feature_id="F001",
        )

        assert result is None
        assert "pre_impl" not in gate_pause.cleared_gates(loaded.plan_dir)

    def test_prod_env_refuses(self, tmp_path: Path) -> None:
        loaded = self._loaded_plan(
            tmp_path, "2026-05-08-921-fix-prod-refuses", ["pre_impl"]
        )
        gate_pause.record_pause(
            loaded.plan_dir, plan_id=loaded.plan_id, pause_gates=["pre_impl"], stage="pre_impl"
        )

        result = supervisor._maybe_auto_clear_pre_impl(
            loaded=loaded,
            declared_gates=list(loaded.plan.human_gates or []),
            direct_dispatch=True,
            effective_env="prod",
            effective_project="any",
            feature_id="F001",
        )

        assert result is None
        assert "pre_impl" not in gate_pause.cleared_gates(loaded.plan_dir)

    def test_production_alias_also_refuses(self, tmp_path: Path) -> None:
        loaded = self._loaded_plan(
            tmp_path, "2026-05-08-922-fix-production-refuses", ["pre_impl"]
        )
        gate_pause.record_pause(
            loaded.plan_dir, plan_id=loaded.plan_id, pause_gates=["pre_impl"], stage="pre_impl"
        )

        result = supervisor._maybe_auto_clear_pre_impl(
            loaded=loaded,
            declared_gates=list(loaded.plan.human_gates or []),
            direct_dispatch=True,
            effective_env="PRODUCTION",
            effective_project=None,
            feature_id="F001",
        )

        assert result is None

    def test_already_cleared_is_idempotent(self, tmp_path: Path) -> None:
        loaded = self._loaded_plan(
            tmp_path, "2026-05-08-923-fix-already-cleared", ["pre_impl"]
        )
        gate_pause.record_pause(
            loaded.plan_dir, plan_id=loaded.plan_id, pause_gates=["pre_impl"], stage="pre_impl"
        )
        gate_pause.approve_gate(loaded.plan_dir, "pre_impl", plan_id=loaded.plan_id)
        before_history_len = len(
            gate_pause.load_gate_state_compat(loaded.plan_dir).raw.get("history") or []
        )

        result = supervisor._maybe_auto_clear_pre_impl(
            loaded=loaded,
            declared_gates=list(loaded.plan.human_gates or []),
            direct_dispatch=True,
            effective_env="dev",
            effective_project=None,
            feature_id="F001",
        )

        assert result is None
        # No additional history rows, no INBOX event written.
        after_history_len = len(
            gate_pause.load_gate_state_compat(loaded.plan_dir).raw.get("history") or []
        )
        assert after_history_len == before_history_len
        events = inbox.read_events(loaded.plan_dir)
        assert not any(e.event == "auto_cleared_pre_impl" for e in events)

    def test_eligible_dev_clears_and_records(self, tmp_path: Path) -> None:
        loaded = self._loaded_plan(
            tmp_path, "2026-05-08-924-fix-eligible-dev", ["pre_impl"]
        )
        # Mirror the supervisor's pre-call sequence: stage paused, awaiting clearance.
        gate_pause.record_pause(
            loaded.plan_dir, plan_id=loaded.plan_id, pause_gates=["pre_impl"], stage="pre_impl"
        )

        result = supervisor._maybe_auto_clear_pre_impl(
            loaded=loaded,
            declared_gates=list(loaded.plan.human_gates or []),
            direct_dispatch=True,
            effective_env="dev",
            effective_project="my-project",
            feature_id="F001",
        )

        assert result is not None
        assert "direct operator dispatch" in result
        assert "pre_impl" in gate_pause.cleared_gates(loaded.plan_dir)
        # Acceptance #2 — gate event records the supervisor:auto_clear_pre_impl actor.
        compat = gate_pause.load_gate_state_compat(loaded.plan_dir)
        events = compat.gate_events
        assert len(events) >= 1
        last = events[-1]
        assert last["gate"] == "pre_impl"
        assert last["stage"] == "pre_impl"
        assert last["cleared_by"] == "supervisor:auto_clear_pre_impl"
        # Acceptance #3 — INBOX records auto_cleared_pre_impl with target context.
        inbox_events = inbox.read_events(loaded.plan_dir)
        ac_events = [e for e in inbox_events if e.event == "auto_cleared_pre_impl"]
        assert len(ac_events) == 1
        assert ac_events[0].headers["target_env"] == "dev"
        assert ac_events[0].headers["target_project"] == "my-project"
        assert ac_events[0].headers["actor"] == "supervisor:auto_clear_pre_impl"

    def test_multi_gate_pending_refuses(self, tmp_path: Path) -> None:
        """When the plan declares pre_impl AND another lifecycle gate but
        the staged eval shows pre_impl as the only pending pre_impl-stage
        gate (which it always will under the current staging), the
        evaluator returns ['pre_impl'] alone — NOT a multi-element list.
        The owned multi-gate refusal triggers when something OTHER than
        pre_impl ends up in the pre_impl-stage's pending list (defensive
        future-proofing for staging changes)."""
        loaded = self._loaded_plan(
            tmp_path,
            "2026-05-08-925-fix-multi-gate",
            ["pre_impl", "pre_merge"],
        )
        gate_pause.record_pause(
            loaded.plan_dir,
            plan_id=loaded.plan_id,
            pause_gates=["pre_impl"],
            stage="pre_impl",
        )

        # Inject a fake evaluate_human_gates that returns multi-gate pending
        # to cover the policy code path. The supervisor's actual stage map
        # doesn't put both gates in the same stage today — the test pins the
        # policy in case the staging expands.
        original = gate_pause.evaluate_human_gates

        def fake_eval(plan_dir: Path, declared: list[Any], stage: str):
            return gate_pause.GatePauseInfo(
                stage=stage,
                pending=["pre_impl", "pre_merge"],
                declared=["pre_impl", "pre_merge"],
            )

        try:
            gate_pause.evaluate_human_gates = fake_eval  # type: ignore[assignment]
            result = supervisor._maybe_auto_clear_pre_impl(
                loaded=loaded,
                declared_gates=list(loaded.plan.human_gates or []),
                direct_dispatch=True,
                effective_env="dev",
                effective_project=None,
                feature_id="F001",
            )
        finally:
            gate_pause.evaluate_human_gates = original  # type: ignore[assignment]

        assert result is None
        assert "pre_impl" not in gate_pause.cleared_gates(loaded.plan_dir)

    def test_pre_impl_not_declared_refuses(self, tmp_path: Path) -> None:
        loaded = self._loaded_plan(
            tmp_path, "2026-05-08-926-fix-pre-impl-undeclared", ["pre_merge"]
        )
        result = supervisor._maybe_auto_clear_pre_impl(
            loaded=loaded,
            declared_gates=list(loaded.plan.human_gates or []),
            direct_dispatch=True,
            effective_env="dev",
            effective_project=None,
            feature_id="F001",
        )
        assert result is None


# ---------------------------------------------------------------------------
# 2. End-to-end dispatch_volley auto-clear (acceptance #1, #7)
# ---------------------------------------------------------------------------


class TestDispatchVolleySurface:
    def test_direct_dispatch_proceeds_without_separate_approve(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance #1 + #7: direct dispatch on an eligible dev plan
        with only pending pre_impl runs the implementer (and auditor)
        round end-to-end without a separate operator approve/resume."""
        order: list[str] = []
        impl = _ScriptedExecutor("claude", order=order)
        aud = _ScriptedExecutor("codex", order=order)
        _install_runtime(monkeypatch, impl, aud)

        plan_id = "2026-05-08-930-fix-direct-dispatch-clears"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])

        result = supervisor.dispatch_volley(
            plan_dir, "F001", max_iterations=1, direct_dispatch=True
        )

        assert result.final_status == "signed_off", result
        # Acceptance #7 — implementer round dispatched (after auto-clear).
        assert any(o.startswith("dispatch:implementer:") for o in order), order
        # Auto-clear evidence persists.
        assert "pre_impl" in gate_pause.cleared_gates(plan_dir)
        events = inbox.read_events(plan_dir)
        assert any(e.event == "auto_cleared_pre_impl" for e in events)
        # No `gate_hit` event — the supervisor never paused for operator.
        assert not any(e.event == "gate_hit" for e in events)

    def test_default_direct_dispatch_false_pauses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance #6 (parity): non-direct (programmatic / default
        kwarg) dispatch keeps the pause-and-await-operator contract."""
        order: list[str] = []
        impl = _ScriptedExecutor("claude", order=order)
        aud = _ScriptedExecutor("codex", order=order)
        _install_runtime(monkeypatch, impl, aud)

        plan_id = "2026-05-08-931-fix-default-pauses"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

        assert result.final_status == "paused_on_gate"
        assert not impl.dispatches and not aud.dispatches
        events = inbox.read_events(plan_dir)
        assert any(e.event == "gate_hit" for e in events)
        assert not any(e.event == "auto_cleared_pre_impl" for e in events)

    def test_prod_target_env_pauses_even_with_direct_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance #4: prod/protected target_env never auto-clears.

        Plan declares ``target_env: dev`` so the existing EC7
        PROD_REQUIRED_GATES contract doesn't fire at plan-load time, then
        the dispatch override raises the effective target to ``prod`` —
        which is exactly the runtime path F002 must protect."""
        order: list[str] = []
        impl = _ScriptedExecutor("claude", order=order)
        aud = _ScriptedExecutor("codex", order=order)
        _install_runtime(monkeypatch, impl, aud)

        plan_id = "2026-05-08-932-fix-prod-pauses"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])

        result = supervisor.dispatch_volley(
            plan_dir,
            "F001",
            max_iterations=1,
            direct_dispatch=True,
            target_env="prod",
        )

        assert result.final_status == "paused_on_gate"
        assert not impl.dispatches
        events = inbox.read_events(plan_dir)
        gate_hits = [e for e in events if e.event == "gate_hit"]
        assert any(e.headers.get("stage") == "pre_impl" for e in gate_hits)
        assert not any(e.event == "auto_cleared_pre_impl" for e in events)

    def test_pre_merge_still_pauses_after_pre_impl_auto_cleared(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance #5 (the spirit of multi-gate refusal): a plan
        declaring pre_impl AND pre_merge with a successful auditor
        signoff must still pause at pre_merge — auto-clear is narrow to
        pre_impl only and never bleeds into other lifecycle gates."""
        order: list[str] = []
        impl = _ScriptedExecutor("claude", order=order)
        aud = _ScriptedExecutor("codex", order=order)
        _install_runtime(monkeypatch, impl, aud)

        plan_id = "2026-05-08-933-fix-pre-merge-still-pauses"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl", "pre_merge"])

        result = supervisor.dispatch_volley(
            plan_dir, "F001", max_iterations=1, direct_dispatch=True
        )

        assert result.final_status == "paused_on_gate"
        # pre_impl was auto-cleared, implementer/auditor ran, then we paused
        # at pre_merge.
        assert "pre_impl" in gate_pause.cleared_gates(plan_dir)
        assert "pre_merge" not in gate_pause.cleared_gates(plan_dir)
        assert gate_pause.pending_stage(plan_dir) == "pre_merge"
        # No success signoff was written (pre_merge blocks the candidate
        # success path).
        assert not signoff_writer.signoff_path(plan_dir, plan_id).exists()
        events = inbox.read_events(plan_dir)
        ac_events = [e for e in events if e.event == "auto_cleared_pre_impl"]
        assert len(ac_events) == 1
        # And the pre_merge gate_hit fired in the same volley.
        gate_hits = [e for e in events if e.event == "gate_hit"]
        assert any(e.headers.get("stage") == "pre_merge" for e in gate_hits)
