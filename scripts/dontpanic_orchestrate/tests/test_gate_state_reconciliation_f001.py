"""Plan 2026-05-08-003 F001 — fail-loud gate-state reconciliation tests.

Covers the three owned contradiction cases (undeclared gate name,
incompatible pending_stage, stale active_defer) and the legacy-compat
``cleared_gates``-only path that must continue to read cleanly.

Acceptance items pinned here:
  (1) contradictory cases raise GateStateReconciliationError;
  (2) the error names plan_id, gate, stage, persisted_state_path, remediation;
  (3) ``gate-state.json`` bytes are unchanged on failure;
  (4) legacy ``cleared_gates``-only state remains compatible;
  (5) dispatch + CLI approve + CLI resume surfaces all raise/refuse via the
      same reconciliation classification consistently;
  (6) INBOX records ``event=gate_state_reconciliation_failed`` for operator
      visibility (supervisor + CLI).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    cli,
    gate_pause,
    inbox,
    notify,
    quota_admission,
    supervisor,
)


# ---------------------------------------------------------------------------
# Shared fixture builders
# ---------------------------------------------------------------------------


def _make_plan(
    tmp_path: Path,
    plan_id: str,
    gates: list[str],
) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    gates_yaml = "\n".join(f"  - {gate}" for gate in gates)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F001 reconciliation synthetic
type: infra
tier: trivial
status: active
date: "2026-05-08"
description: Synthetic plan for fail-loud gate-state reconciliation tests.
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

# F001 reconciliation synthetic

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


def _write_state(plan_dir: Path, payload: dict[str, Any]) -> Path:
    """Write a hand-crafted gate-state.json for fixture tests. Returns the
    path so callers can read bytes for byte-stability assertions."""
    state_path = gate_pause.gate_state_path(plan_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, indent=2) + "\n")
    return state_path


# ---------------------------------------------------------------------------
# 1. Direct unit tests on gate_pause.reconcile_gate_state
# ---------------------------------------------------------------------------


class TestReconcileDirect:
    def test_legacy_cleared_gates_only_state_passes(self, tmp_path: Path) -> None:
        """Acceptance #4: legacy ``cleared_gates``-only state remains
        compatible. No pause_gates / pending_stage / gate_events fields."""
        plan_id = "2026-05-08-901-fix-legacy-compat"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl", "pre_merge"])
        _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": ["pre_impl"],
                "history": [],
            },
        )

        compat = gate_pause.reconcile_gate_state(
            plan_dir,
            plan_id=plan_id,
            declared_gates=["pre_impl", "pre_merge"],
        )

        assert compat.cleared_gates == ["pre_impl"]
        assert compat.pending_stage is None
        assert compat.gate_events == []

    def test_no_state_file_passes(self, tmp_path: Path) -> None:
        plan_id = "2026-05-08-902-fix-no-state-file"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])

        compat = gate_pause.reconcile_gate_state(
            plan_dir,
            plan_id=plan_id,
            declared_gates=["pre_impl"],
        )

        assert compat.cleared_gates == []
        assert compat.pending_stage is None

    def test_undeclared_gate_in_cleared_gates_raises(self, tmp_path: Path) -> None:
        plan_id = "2026-05-08-903-fix-undeclared-cleared"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        state_path = _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": ["pre_impl", "on_escalation"],
                "history": [],
            },
        )
        before = state_path.read_bytes()

        with pytest.raises(gate_pause.GateStateReconciliationError) as excinfo:
            gate_pause.reconcile_gate_state(
                plan_dir,
                plan_id=plan_id,
                declared_gates=["pre_impl"],
            )
        err = excinfo.value
        assert err.kind == gate_pause.GateStateReconciliationError.KIND_UNDECLARED_GATE
        assert err.gate == "on_escalation"
        assert err.plan_id == plan_id
        assert err.persisted_state_path == state_path
        assert "on_escalation" in err.remediation
        # Acceptance #3: bytes unchanged on failure.
        assert state_path.read_bytes() == before

    def test_undeclared_gate_in_pause_gates_raises(self, tmp_path: Path) -> None:
        plan_id = "2026-05-08-904-fix-undeclared-pause"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        state_path = _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": [],
                "pause_gates": ["tier_promotion"],
                "paused_at": "2026-05-08T00:00:00Z",
                "history": [],
            },
        )
        before = state_path.read_bytes()

        with pytest.raises(gate_pause.GateStateReconciliationError) as excinfo:
            gate_pause.reconcile_gate_state(
                plan_dir,
                plan_id=plan_id,
                declared_gates=["pre_impl"],
            )
        err = excinfo.value
        assert err.kind == gate_pause.GateStateReconciliationError.KIND_UNDECLARED_GATE
        assert err.gate == "tier_promotion"
        assert state_path.read_bytes() == before

    def test_synthetic_breaker_name_in_pause_gates_passes(self, tmp_path: Path) -> None:
        """Synthetic breaker:* gates are valid in persisted state without
        being declared in plan.human_gates — they live on the supervisor's
        transient lifecycle."""
        plan_id = "2026-05-08-905-fix-synthetic-allowed"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": ["pre_impl"],
                "pause_gates": ["breaker:no_progress"],
                "active_breakers": ["breaker:no_progress"],
                "history": [],
            },
        )

        # Should not raise — breaker:* is a recognized synthetic prefix.
        gate_pause.reconcile_gate_state(
            plan_dir,
            plan_id=plan_id,
            declared_gates=["pre_impl"],
        )

    def test_unknown_pending_stage_raises(self, tmp_path: Path) -> None:
        plan_id = "2026-05-08-906-fix-bad-stage"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        state_path = _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": [],
                "pending_stage": "post_impl",
                "history": [],
            },
        )
        before = state_path.read_bytes()

        with pytest.raises(gate_pause.GateStateReconciliationError) as excinfo:
            gate_pause.reconcile_gate_state(
                plan_dir,
                plan_id=plan_id,
                declared_gates=["pre_impl"],
            )
        err = excinfo.value
        assert err.kind == gate_pause.GateStateReconciliationError.KIND_INCOMPATIBLE_STAGE
        assert err.stage == "post_impl"
        assert state_path.read_bytes() == before

    def test_pending_stage_with_non_declared_gate_raises(self, tmp_path: Path) -> None:
        """``pending_stage=pre_merge`` but plan only declares ``pre_impl``:
        the recorded stage maps to a gate the plan never asked for."""
        plan_id = "2026-05-08-907-fix-stage-mismatch"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        state_path = _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": [],
                "pending_stage": "pre_merge",
                "history": [],
            },
        )
        before = state_path.read_bytes()

        with pytest.raises(gate_pause.GateStateReconciliationError) as excinfo:
            gate_pause.reconcile_gate_state(
                plan_dir,
                plan_id=plan_id,
                declared_gates=["pre_impl"],
            )
        err = excinfo.value
        assert err.kind == gate_pause.GateStateReconciliationError.KIND_INCOMPATIBLE_STAGE
        assert err.stage == "pre_merge"
        assert state_path.read_bytes() == before

    def test_stale_active_defer_raises(self, tmp_path: Path) -> None:
        plan_id = "2026-05-08-908-fix-stale-defer"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        state_path = _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": [],
                "active_defers": ["defer:nonsense_kind"],
                "history": [],
            },
        )
        before = state_path.read_bytes()

        with pytest.raises(gate_pause.GateStateReconciliationError) as excinfo:
            gate_pause.reconcile_gate_state(
                plan_dir,
                plan_id=plan_id,
                declared_gates=["pre_impl"],
            )
        err = excinfo.value
        assert err.kind == gate_pause.GateStateReconciliationError.KIND_STALE_ACTIVE_DEFER
        assert err.gate == "defer:nonsense_kind"
        assert state_path.read_bytes() == before

    def test_known_active_defer_passes(self, tmp_path: Path) -> None:
        plan_id = "2026-05-08-909-fix-known-defer"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        valid = quota_admission.gate_name(quota_admission.DeferKind.QUOTA_THRESHOLD)
        _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": [],
                "active_defers": [valid],
                "history": [],
            },
        )

        gate_pause.reconcile_gate_state(
            plan_dir,
            plan_id=plan_id,
            declared_gates=["pre_impl"],
        )


# ---------------------------------------------------------------------------
# 2. Supervisor surface — dispatch_volley fails loud + INBOX event
# ---------------------------------------------------------------------------


class TestSupervisorSurface:
    def test_dispatch_volley_raises_and_writes_inbox(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance #5 + #6: the supervisor surface refuses through the
        same reconciliation category; INBOX records the classification."""
        monkeypatch.setenv(notify.DISABLE_ENV, "1")
        plan_id = "2026-05-08-910-fix-supervisor-fail"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        state_path = _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": ["on_escalation"],
                "history": [],
            },
        )
        before = state_path.read_bytes()

        with pytest.raises(gate_pause.GateStateReconciliationError) as excinfo:
            supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
        err = excinfo.value
        assert err.kind == gate_pause.GateStateReconciliationError.KIND_UNDECLARED_GATE
        assert err.gate == "on_escalation"
        # Acceptance #3: file untouched.
        assert state_path.read_bytes() == before

        # Acceptance #6: INBOX has the classified event.
        events = inbox.read_events(plan_dir)
        recon_events = [e for e in events if e.event == "gate_state_reconciliation_failed"]
        assert len(recon_events) == 1
        assert recon_events[0].headers["kind"] == err.kind
        assert recon_events[0].headers["gate"] == "on_escalation"

    def test_dispatch_single_agent_raises_and_writes_inbox(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(notify.DISABLE_ENV, "1")
        plan_id = "2026-05-08-911-fix-supervisor-single"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        state_path = _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": [],
                "pending_stage": "post_impl",
                "history": [],
            },
        )
        before = state_path.read_bytes()

        with pytest.raises(gate_pause.GateStateReconciliationError) as excinfo:
            supervisor.dispatch_single_agent(plan_dir, "F001")
        err = excinfo.value
        assert err.kind == gate_pause.GateStateReconciliationError.KIND_INCOMPATIBLE_STAGE
        assert state_path.read_bytes() == before

        events = inbox.read_events(plan_dir)
        recon_events = [e for e in events if e.event == "gate_state_reconciliation_failed"]
        assert len(recon_events) == 1
        assert recon_events[0].headers["stage"] == "post_impl"


# ---------------------------------------------------------------------------
# 3. CLI surface — approve / resume refuse with exit 2 + INBOX
# ---------------------------------------------------------------------------


class TestCLISurface:
    def test_cli_approve_refuses_on_contradiction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(notify.DISABLE_ENV, "1")
        # _resolve_plan_dir falls back to a literal path when the arg matches
        # an existing dir — pass the absolute plan_dir directly so CLI
        # resolution doesn't depend on cwd / project registry state.
        plan_id = "2026-05-08-912-fix-cli-approve"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        state_path = _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": [],
                "active_defers": ["defer:bogus"],
                "history": [],
            },
        )
        before = state_path.read_bytes()

        rc = cli._approve_main([str(plan_dir), "pre_impl"])
        assert rc == 2
        assert state_path.read_bytes() == before
        events = inbox.read_events(plan_dir)
        recon_events = [e for e in events if e.event == "gate_state_reconciliation_failed"]
        assert len(recon_events) == 1
        assert (
            recon_events[0].headers["kind"]
            == gate_pause.GateStateReconciliationError.KIND_STALE_ACTIVE_DEFER
        )
        assert recon_events[0].headers["cli"] == "approve"

    def test_cli_resume_gate_refuses_on_contradiction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(notify.DISABLE_ENV, "1")
        plan_id = "2026-05-08-913-fix-cli-resume-gate"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        state_path = _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": ["unknown_gate"],
                "history": [],
            },
        )
        before = state_path.read_bytes()

        rc = cli._resume_main([str(plan_dir), "--gate", "pre_impl"])
        assert rc == 2
        assert state_path.read_bytes() == before
        events = inbox.read_events(plan_dir)
        recon_events = [e for e in events if e.event == "gate_state_reconciliation_failed"]
        assert len(recon_events) == 1
        assert (
            recon_events[0].headers["kind"]
            == gate_pause.GateStateReconciliationError.KIND_UNDECLARED_GATE
        )
        assert recon_events[0].headers["cli"] == "resume"

    def test_cli_resume_all_refuses_on_contradiction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(notify.DISABLE_ENV, "1")
        plan_id = "2026-05-08-914-fix-cli-resume-all"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        state_path = _write_state(
            plan_dir,
            {
                "plan_id": plan_id,
                "cleared_gates": [],
                "pending_stage": "post_impl",
                "history": [],
            },
        )
        before = state_path.read_bytes()

        rc = cli._resume_main([str(plan_dir), "--all"])
        assert rc == 2
        assert state_path.read_bytes() == before
        events = inbox.read_events(plan_dir)
        recon_events = [e for e in events if e.event == "gate_state_reconciliation_failed"]
        assert len(recon_events) == 1
        assert (
            recon_events[0].headers["kind"]
            == gate_pause.GateStateReconciliationError.KIND_INCOMPATIBLE_STAGE
        )

    def test_cli_approve_proceeds_when_state_consistent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sanity check: a clean legacy state allows approve to succeed end-
        to-end. Guards against the reconcile helper accidentally rejecting
        compatible inputs."""
        monkeypatch.setenv(notify.DISABLE_ENV, "1")
        plan_id = "2026-05-08-915-fix-cli-approve-clean"
        plan_dir = _make_plan(tmp_path, plan_id, ["pre_impl"])
        # Persist a pause so the lifecycle-staged-gate enforcement in
        # _approve_main accepts the clearance.
        gate_pause.record_pause(
            plan_dir, plan_id=plan_id, pause_gates=["pre_impl"], stage="pre_impl"
        )

        rc = cli._approve_main([str(plan_dir), "pre_impl"])
        assert rc == 0
        events = inbox.read_events(plan_dir)
        recon_events = [e for e in events if e.event == "gate_state_reconciliation_failed"]
        assert recon_events == []
