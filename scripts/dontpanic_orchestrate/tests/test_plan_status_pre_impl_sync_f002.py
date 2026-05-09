"""Plan 2026-05-09-002 F002 — plan-status → pre_impl sync tests.

Eight fixture cases covering the post-reconcile sync helper for the
``status: active`` trigger:

  (a) status=active + pre_impl declared + uncleared → sync clears +
      records gate_event + INBOX;
  (b) status=draft + same shape → no-op (unchanged manual flow);
  (c) status=ready_for_audit → no-op (post-impl state);
  (d) status=completed → no-op (post-impl state — completed plans should
      NOT be re-dispatchable through this seam);
  (e) status=active + pre_impl already cleared → idempotent no-op;
  (f) status=active + pre_impl NOT in declared gates → no-op (don't
      invent gates);
  (g) reconcile_gate_state stays documented-pure (purity invariant);
  (h) plan 2026-05-08-003 F002's direct-dispatch path still fires for
      status=draft + direct_dispatch=True (no regression on phase 1).
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
    plan_loader,
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


def _make_plan(
    tmp_path: Path,
    plan_id: str,
    *,
    status: str,
    gates: list[str],
) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    gates_yaml = "\n".join(f"  - {g}" for g in gates) if gates else "  []"
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F002 plan-status sync synthetic
type: infra
tier: trivial
status: {status}
date: "2026-05-09"
description: Synthetic plan for F002 plan-status → pre_impl sync tests.
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

# Synthetic

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


# ───────────────────────── 1. Direct unit tests ─────────────────────────


class TestPlanStatusEnablesImplicitPreImpl:
    @pytest.mark.parametrize(
        "status,expected",
        [
            ("active", True),
            ("draft", False),
            ("ready_for_audit", False),
            ("in_audit", False),
            ("completed", False),
            ("abandoned", False),
            ("blocked", False),
        ],
        ids=[
            "active-yes",
            "draft-no",
            "ready-for-audit-no",
            "in-audit-no",
            "completed-no",
            "abandoned-no",
            "blocked-no",
        ],
    )
    def test_only_active_returns_true(
        self, tmp_path: Path, status: str, expected: bool
    ) -> None:
        plan_id = f"2026-05-09-{990 + len(status) % 9:03d}-fix-status-{status}".replace("_", "-")
        plan_dir = _make_plan(tmp_path, plan_id, status=status, gates=["pre_impl"])
        loaded = plan_loader.load(plan_dir)
        assert plan_loader.plan_status_enables_implicit_pre_impl(loaded) is expected


class TestImplicitClearHelper:
    def test_active_clears_pre_impl_with_distinct_actor(self, tmp_path: Path) -> None:
        plan_id = "2026-05-09-970-fix-active-clears"
        plan_dir = _make_plan(tmp_path, plan_id, status="active", gates=["pre_impl"])

        changed = gate_pause.implicit_clear_pre_impl_for_active_plan(
            plan_dir, plan_id=plan_id, declared_gates=["pre_impl"]
        )
        assert changed is True

        compat = gate_pause.load_gate_state_compat(plan_dir)
        assert "pre_impl" in compat.cleared_gates
        # Distinct actor — distinguishes from operator approve / phase-1 auto-clear.
        events = compat.gate_events
        assert any(
            e.get("gate") == "pre_impl"
            and e.get("cleared_by") == "supervisor:plan_status_active"
            for e in events
        )

    def test_pre_impl_not_declared_is_noop(self, tmp_path: Path) -> None:
        plan_id = "2026-05-09-971-fix-pre-impl-not-declared"
        plan_dir = _make_plan(tmp_path, plan_id, status="active", gates=["pre_merge"])

        changed = gate_pause.implicit_clear_pre_impl_for_active_plan(
            plan_dir, plan_id=plan_id, declared_gates=["pre_merge"]
        )
        assert changed is False

    def test_already_cleared_is_idempotent(self, tmp_path: Path) -> None:
        plan_id = "2026-05-09-972-fix-already-cleared"
        plan_dir = _make_plan(tmp_path, plan_id, status="active", gates=["pre_impl"])
        # Pre-clear via the operator path.
        gate_pause.record_pause(
            plan_dir, plan_id=plan_id, pause_gates=["pre_impl"], stage="pre_impl"
        )
        gate_pause.approve_gate(plan_dir, "pre_impl", plan_id=plan_id)
        before_state = gate_pause.gate_state_path(plan_dir).read_bytes()

        changed = gate_pause.implicit_clear_pre_impl_for_active_plan(
            plan_dir, plan_id=plan_id, declared_gates=["pre_impl"]
        )
        assert changed is False
        # State bytes unchanged on idempotent re-call.
        assert gate_pause.gate_state_path(plan_dir).read_bytes() == before_state


# ───────────────────────── 2. reconcile_gate_state purity ─────────────────────────


class TestReconcilePurity:
    def test_reconcile_does_not_write_state_file(self, tmp_path: Path) -> None:
        """reconcile_gate_state stays documented-pure per plan
        2026-05-08-003 F001 D004. F002 of plan 2026-05-09-002 must not
        change that contract."""
        plan_id = "2026-05-09-973-fix-reconcile-purity"
        plan_dir = _make_plan(tmp_path, plan_id, status="active", gates=["pre_impl"])
        # No gate-state.json exists yet.
        assert not gate_pause.gate_state_path(plan_dir).is_file()

        gate_pause.reconcile_gate_state(
            plan_dir, plan_id=plan_id, declared_gates=["pre_impl"]
        )
        # Still no gate-state.json — reconcile does not create state.
        assert not gate_pause.gate_state_path(plan_dir).is_file()


# ───────────────────────── 3. Supervisor end-to-end ─────────────────────────


class _ScriptedExecutor(BaseExecutor):
    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.dispatched = False

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.dispatched = True
        summary = (
            "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
            "## Target context\nRepo: synthetic\nEnv: dev\nProject: (none)\n\n"
            f"Overall verdict: signed_off.\n{self.agent_name}/{task.agent_role}."
        )
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=summary,
            raw_response=summary,
            error=None,
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _install_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[BaseExecutor, BaseExecutor]:
    impl = _ScriptedExecutor("claude")
    aud = _ScriptedExecutor("codex")
    monkeypatch.setenv(notify.DISABLE_ENV, "1")
    monkeypatch.setitem(AGENT_REGISTRY, "claude", lambda: impl)
    monkeypatch.setitem(AGENT_REGISTRY, "codex", lambda: aud)
    monkeypatch.setattr(
        supervisor,
        "_quota_gate",
        lambda agent: (None, f"[quota] {agent}: bypassed"),
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
            supervisor.circuit_breakers.BudgetCeilingKind.OK, False, ""
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
    return impl, aud


class TestSupervisorWiring:
    def test_active_plan_dispatches_without_separate_approve(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: a plan whose plan.md status is `active` dispatches
        cleanly without a separate `dontpanic approve <plan> pre_impl`
        step. INBOX records `pre_impl_status_synced`."""
        _install_runtime(monkeypatch)
        plan_id = "2026-05-09-980-fix-active-dispatches"
        plan_dir = _make_plan(tmp_path, plan_id, status="active", gates=["pre_impl"])

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

        assert result.final_status == "signed_off", result
        # No pre_impl pause.
        events = inbox.read_events(plan_dir)
        gate_hits = [
            e for e in events if e.event == "gate_hit" and e.headers.get("stage") == "pre_impl"
        ]
        assert not gate_hits, "active plan should not pause on pre_impl"
        sync_events = [e for e in events if e.event == "pre_impl_status_synced"]
        assert len(sync_events) == 1
        assert sync_events[0].headers["status"] == "active"
        assert sync_events[0].headers["feature_id"] == "F001"

    def test_draft_plan_pauses_at_pre_impl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Draft plan keeps the manual flow — no implicit clearance."""
        _install_runtime(monkeypatch)
        plan_id = "2026-05-09-981-fix-draft-pauses"
        plan_dir = _make_plan(tmp_path, plan_id, status="draft", gates=["pre_impl"])

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

        assert result.final_status == "paused_on_gate"
        events = inbox.read_events(plan_dir)
        assert not any(e.event == "pre_impl_status_synced" for e in events)

    @pytest.mark.parametrize(
        "status",
        ["ready_for_audit", "in_audit", "completed", "abandoned", "blocked"],
        ids=[
            "ready-for-audit",
            "in-audit",
            "completed",
            "abandoned",
            "blocked",
        ],
    )
    def test_post_impl_states_do_not_trigger_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
    ) -> None:
        """Post-implementation states must NOT auto-clear pre_impl. A
        completed plan should not be re-dispatchable through this seam."""
        _install_runtime(monkeypatch)
        plan_id = f"2026-05-09-{990 + len(status) % 9:03d}-fix-post-impl-{status}".replace("_", "-")
        plan_dir = _make_plan(tmp_path, plan_id, status=status, gates=["pre_impl"])

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

        assert result.final_status == "paused_on_gate", (
            f"status={status} should keep manual flow"
        )
        events = inbox.read_events(plan_dir)
        assert not any(e.event == "pre_impl_status_synced" for e in events)

    def test_phase_1_direct_dispatch_still_fires_for_draft_plans(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance #5 — the plan 2026-05-08-003 F002 direct-dispatch
        auto-clear path still fires for status=draft + direct_dispatch=True.
        F002 phase-2 doesn't regress phase-1 behavior; the two triggers
        compose without conflict."""
        _install_runtime(monkeypatch)
        plan_id = "2026-05-09-982-fix-phase1-still-fires"
        plan_dir = _make_plan(tmp_path, plan_id, status="draft", gates=["pre_impl"])

        result = supervisor.dispatch_volley(
            plan_dir, "F001", max_iterations=1, direct_dispatch=True
        )

        assert result.final_status == "signed_off", result
        events = inbox.read_events(plan_dir)
        # phase-1 INBOX event, NOT phase-2.
        assert any(e.event == "auto_cleared_pre_impl" for e in events)
        assert not any(e.event == "pre_impl_status_synced" for e in events)

    def test_active_plan_with_pre_impl_not_declared_no_op(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance #6 — active plan that doesn't declare pre_impl is
        a no-op (don't invent gates)."""
        _install_runtime(monkeypatch)
        plan_id = "2026-05-09-983-fix-active-no-pre-impl"
        plan_dir = _make_plan(
            tmp_path, plan_id, status="active", gates=["on_escalation"]
        )
        gate_pause.approve_gate(plan_dir, "on_escalation", plan_id=plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

        assert result.final_status == "signed_off"
        events = inbox.read_events(plan_dir)
        # No sync event because pre_impl wasn't declared.
        assert not any(e.event == "pre_impl_status_synced" for e in events)
