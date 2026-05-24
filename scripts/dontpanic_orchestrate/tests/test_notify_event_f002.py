"""Plan 2026-05-24-004 F002 — NotifyEvent extension + new emit-site tests.

Coverage:
- TestNotifyEventExtension — new dataclass fields (inbox_event, 8 first-class
  fields, technical_metadata, evidence_uri alias) with defaults + invariants.
- TestEvidenceUriAlias — action_link/evidence_uri stay in lock-step;
  constructor accepts either name; conflicting values raise.
- TestExistingEmitSitesStillValid — the existing 6 emit sites continue to
  build valid NotifyEvent instances (escalation invariant preserved).
- TestNewEmitSitesShape — the six new dispatch sites fire with the expected
  payload (inbox_event / severity / first-class fields / technical_metadata).
- TestInboxBeforeDispatch — for every new dispatch site, the paired
  inbox.append_event() call precedes notify_event.dispatch_event().
- TestSinkRenderingDoesNotRegress — existing sinks consume events that omit
  the new fields without raising.
"""

from __future__ import annotations

import datetime as dt
import inspect
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    architecture_regen_hook,
    auditor_taxonomy,
    inbox,
    notify,
    notify_discord,
    notify_event,
    supervisor,
)
from dontpanic_orchestrate import circuit_breakers as cb  # noqa: E402
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)


PLACEHOLDER_URL = "https://example.invalid/webhook/123/abc"


# ───────────────────────── 1. Dataclass extension ─────────────────────────


class TestNotifyEventExtension:
    def test_all_new_fields_default_to_none_or_empty_dict(self) -> None:
        ev = notify_event.NotifyEvent(
            kind="volley_start",
            severity="info",
            plan_id="p1",
            feature_id="F002",
            body="x",
        )
        assert ev.inbox_event is None
        assert ev.subtype is None
        assert ev.breaker_kind is None
        assert ev.iteration_count is None
        assert ev.feature_display_name is None
        assert ev.aggregate_class is None
        assert ev.blocking is None
        assert ev.target_env is None
        assert ev.target_project is None
        assert ev.technical_metadata == {}

    def test_new_fields_round_trip(self) -> None:
        ev = notify_event.NotifyEvent(
            kind="volley_terminal",
            severity="action_required",
            plan_id="p1",
            feature_id="F002",
            body="x",
            evidence_uri="/tmp/signoff.json",
            inbox_event="volley_terminal",
            subtype="stopped_no_progress",
            breaker_kind="no_progress",
            iteration_count=3,
            feature_display_name="Pretty Name",
            aggregate_class="implementation_defect",
            blocking=True,
            target_env="dev",
            target_project="my-proj",
            technical_metadata={
                "final_status": "stopped_no_progress",
                "rounds": 2,
                "ok": True,
                "missing": None,
            },
        )
        assert ev.inbox_event == "volley_terminal"
        assert ev.subtype == "stopped_no_progress"
        assert ev.breaker_kind == "no_progress"
        assert ev.iteration_count == 3
        assert ev.feature_display_name == "Pretty Name"
        assert ev.aggregate_class == "implementation_defect"
        assert ev.blocking is True
        assert ev.target_env == "dev"
        assert ev.target_project == "my-proj"
        assert ev.technical_metadata == {
            "final_status": "stopped_no_progress",
            "rounds": 2,
            "ok": True,
            "missing": None,
        }

    def test_technical_metadata_default_factory_is_independent_per_instance(
        self,
    ) -> None:
        a = notify_event.NotifyEvent(
            kind="signoff", severity="info", plan_id="p", feature_id=None, body="x"
        )
        b = notify_event.NotifyEvent(
            kind="signoff", severity="info", plan_id="p", feature_id=None, body="x"
        )
        # The dict on each instance is its own object — mutating one doesn't
        # leak into the other (default_factory invariant).
        assert a.technical_metadata is not b.technical_metadata

    def test_existing_escalation_invariant_preserved(self) -> None:
        with pytest.raises(ValueError, match="action_link"):
            notify_event.NotifyEvent(
                kind="breaker_tripped",
                severity="escalation",
                plan_id="p",
                feature_id="F002",
                body="x",
            )

    def test_escalation_with_evidence_uri_only_passes(self) -> None:
        ev = notify_event.NotifyEvent(
            kind="breaker_tripped",
            severity="escalation",
            plan_id="p",
            feature_id="F002",
            body="x",
            evidence_uri="/tmp/INBOX.md",
        )
        # evidence_uri is the alias path — escalation invariant must accept it.
        assert ev.action_link == "/tmp/INBOX.md"


# ───────────────────────── 2. evidence_uri / action_link alias ─────────────────────────


class TestEvidenceUriAlias:
    def test_evidence_uri_populates_action_link(self) -> None:
        ev = notify_event.NotifyEvent(
            kind="gate_paused",
            severity="action_required",
            plan_id="p",
            feature_id="F002",
            body="x",
            evidence_uri="/tmp/INBOX.md",
        )
        assert ev.action_link == "/tmp/INBOX.md"
        assert ev.evidence_uri == "/tmp/INBOX.md"

    def test_action_link_populates_evidence_uri(self) -> None:
        ev = notify_event.NotifyEvent(
            kind="gate_paused",
            severity="action_required",
            plan_id="p",
            feature_id="F002",
            body="x",
            action_link="/tmp/INBOX.md",
        )
        assert ev.action_link == "/tmp/INBOX.md"
        assert ev.evidence_uri == "/tmp/INBOX.md"

    def test_both_with_same_value_is_idempotent(self) -> None:
        ev = notify_event.NotifyEvent(
            kind="gate_paused",
            severity="action_required",
            plan_id="p",
            feature_id="F002",
            body="x",
            action_link="/tmp/INBOX.md",
            evidence_uri="/tmp/INBOX.md",
        )
        assert ev.action_link == ev.evidence_uri == "/tmp/INBOX.md"

    def test_both_with_different_values_raises(self) -> None:
        with pytest.raises(ValueError, match="aliases"):
            notify_event.NotifyEvent(
                kind="gate_paused",
                severity="action_required",
                plan_id="p",
                feature_id="F002",
                body="x",
                action_link="/tmp/A.md",
                evidence_uri="/tmp/B.md",
            )

    def test_neither_set_keeps_both_none(self) -> None:
        ev = notify_event.NotifyEvent(
            kind="volley_start",
            severity="info",
            plan_id="p",
            feature_id="F002",
            body="x",
        )
        assert ev.action_link is None
        assert ev.evidence_uri is None


# ───────────────────────── 3. Existing emit sites still valid ─────────────────────────


class TestExistingEmitSitesStillValid:
    """Build events with the SAME shape the post-F002 emit sites use and
    confirm they construct without violating any invariant."""

    def test_breaker_tripped_event_constructs(self) -> None:
        ev = notify_event.NotifyEvent(
            kind="breaker_tripped",
            severity="escalation",
            plan_id="p",
            feature_id="F002",
            body="**Breaker** `no_progress` — reason",
            evidence_uri="/tmp/INBOX.md",
            timestamp=dt.datetime.now(dt.timezone.utc),
            inbox_event="breaker_tripped",
            breaker_kind="no_progress",
        )
        assert ev.inbox_event == "breaker_tripped"
        assert ev.breaker_kind == "no_progress"
        assert ev.action_link == "/tmp/INBOX.md"

    def test_gate_paused_event_carries_inbox_event_gate_hit(self) -> None:
        ev = notify_event.NotifyEvent(
            kind="gate_paused",
            severity="action_required",
            plan_id="p",
            feature_id="F002",
            body="**Gate pause** (pre_merge)",
            evidence_uri="/tmp/INBOX.md",
            timestamp=dt.datetime.now(dt.timezone.utc),
            inbox_event="gate_hit",
            subtype="pre_merge",
            target_env="dev",
            target_project=None,
        )
        assert ev.inbox_event == "gate_hit"
        assert ev.subtype == "pre_merge"
        assert ev.target_env == "dev"

    def test_volley_terminal_event_carries_technical_metadata(self) -> None:
        ev = notify_event.NotifyEvent(
            kind="volley_terminal",
            severity="action_required",
            plan_id="p",
            feature_id="F002",
            body="**stopped_no_progress** — reason\nrounds: 2",
            evidence_uri="/tmp/signoff.json",
            timestamp=dt.datetime.now(dt.timezone.utc),
            inbox_event="volley_terminal",
            iteration_count=2,
            technical_metadata={
                "final_status": "stopped_no_progress",
                "rounds": 2,
            },
        )
        assert ev.technical_metadata["final_status"] == "stopped_no_progress"
        assert ev.technical_metadata["rounds"] == 2


# ───────────────────────── 4. New emit-site dispatch shape ─────────────────────────


def _capture_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[notify_event.NotifyEvent]:
    captured: list[notify_event.NotifyEvent] = []

    def fake_dispatch(ev: notify_event.NotifyEvent, **_: Any) -> dict[str, bool]:
        captured.append(ev)
        return {"terminal": False, "discord": False}

    monkeypatch.setattr(notify_event, "dispatch_event", fake_dispatch)
    # Also patch the binding used inside supervisor.py
    monkeypatch.setattr(supervisor.notify_event, "dispatch_event", fake_dispatch)
    monkeypatch.setattr(
        architecture_regen_hook.notify_event, "dispatch_event", fake_dispatch
    )
    return captured


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _ScriptedExecutor(BaseExecutor):
    """Small real-executor seam for supervisor branch tests.

    It lets ``dispatch_volley()`` run normally through the production branch
    that constructs ``NotifyEvent`` while keeping network/process execution
    out of the test.
    """

    def __init__(self, agent: str, role: str, auditor_verdict: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.role = role
        self.auditor_verdict = auditor_verdict
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.calls += 1
        if self.role == "auditor":
            summary = (
                "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "## Target context\nRepo: synthetic\nEnv: dev\nProject: (none)\n\n"
                f"**Verdict: {self.auditor_verdict}**\n\n"
                "Auditor enumerated findings — see structured envelope."
            )
        else:
            summary = (
                "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "## Target context\nRepo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "[F002] Implementer landed the change."
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


def _make_dispatch_plan(tmp_path: Path, plan_id: str) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F002 NotifyEvent dispatch synthetic
type: infra
tier: trivial
status: draft
date: "2026-05-24"
description: Synthetic plan for F002 NotifyEvent dispatch tests.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 4
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# F002 NotifyEvent dispatch synthetic

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
                        "id": "F002",
                        "category": "test",
                        "phase": 0,
                        "description": "Synthetic feature for NotifyEvent F002.",
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


def _install_dispatch_runtime(
    monkeypatch: pytest.MonkeyPatch, *, auditor_verdict: str
) -> tuple[_ScriptedExecutor, _ScriptedExecutor]:
    impl = _ScriptedExecutor("claude", "implementer", auditor_verdict)
    aud = _ScriptedExecutor("codex", "auditor", auditor_verdict)
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
        supervisor.circuit_breakers,
        "check_diminishing_returns",
        lambda *args, **kwargs: (False, ""),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_convergence_collapse",
        lambda *args, **kwargs: (False, ""),
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
    monkeypatch.setattr(notify, "notify", lambda *args, **kwargs: True)
    return impl, aud


def _inject_auditor_envelopes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    audit_status: str,
    findings_per_round: list[list[dict[str, Any]]],
) -> None:
    original = supervisor._run_round
    counter = {"n": 0}

    def wrapped(*args: Any, **kwargs: Any) -> Path:
        path = original(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            data = json.loads(path.read_text())
            idx = counter["n"]
            counter["n"] += 1
            if idx < len(findings_per_round):
                data["findings"] = findings_per_round[idx]
            data["audit_status"] = audit_status
            path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    monkeypatch.setattr(supervisor, "_run_round", wrapped)


ENV_FINDING = {
    "severity": "high",
    "category": "test_coverage",
    "issue": "Could not run pytest because the sandbox refused the test runner.",
    "evidence": "harness blocker — sandbox cannot spawn pytest.",
}

DEFECT_FINDING = {
    "severity": "high",
    "category": "correctness",
    "feature_id": "F002",
    "issue": "Implementation drops the required metadata kwarg.",
    "evidence": "diff shows the NotifyEvent constructor missing the field.",
}


def _events_of_kind(
    captured: list[notify_event.NotifyEvent], kind: str
) -> list[notify_event.NotifyEvent]:
    return [ev for ev in captured if ev.kind == kind]


class TestNewEmitSitesShape:
    """Each new emit site should fire a NotifyEvent with the expected
    kind+inbox_event pairing and the documented metadata."""

    def test_breaker_tripped_carries_breaker_kind(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured = _capture_dispatch(monkeypatch)
        monkeypatch.setattr(inbox, "append_event", lambda *a, **k: None)
        monkeypatch.setattr(notify, "notify", lambda *a, **k: True)
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        supervisor._trip_breaker(
            plan_dir, "p1", "F002", cb.BreakerKind.NO_PROGRESS, "reason"
        )
        assert len(captured) == 1
        ev = captured[0]
        assert ev.kind == "breaker_tripped"
        assert ev.inbox_event == "breaker_tripped"
        assert ev.breaker_kind == "no_progress"
        assert ev.severity == "escalation"
        assert ev.evidence_uri == str(plan_dir / "INBOX.md")

    def test_gate_paused_carries_gate_hit_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured = _capture_dispatch(monkeypatch)
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        supervisor._emit_gate_paused_discord(
            plan_dir,
            "p1",
            "F002",
            pending_gates=["pre_merge"],
            stage="pre_merge",
            target_env="dev",
            target_project=None,
        )
        assert len(captured) == 1
        ev = captured[0]
        assert ev.kind == "gate_paused"
        assert ev.inbox_event == "gate_hit"
        assert ev.subtype == "pre_merge"
        assert ev.target_env == "dev"
        assert ev.target_project is None
        assert ev.severity == "action_required"

    def test_gate_state_reconciliation_failed_dispatches_escalation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured = _capture_dispatch(monkeypatch)
        from dontpanic_orchestrate import gate_pause

        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        monkeypatch.setattr(inbox, "append_event", lambda *a, **k: None)
        monkeypatch.setattr(notify, "notify", lambda *a, **k: True)

        persisted = plan_dir / "gate-state.json"
        persisted.write_text("{}")
        exc_inst = gate_pause.GateStateReconciliationError(
            kind=gate_pause.GateStateReconciliationError.KIND_UNDECLARED_GATE,
            plan_id="p1",
            gate="pre_merge",
            stage=None,
            persisted_state_path=persisted,
            remediation="see INBOX",
        )

        def boom(*a: Any, **k: Any) -> None:
            raise exc_inst

        monkeypatch.setattr(gate_pause, "reconcile_gate_state", boom)
        monkeypatch.setattr(
            gate_pause, "format_reconciliation_inbox_body", lambda exc: "body"
        )

        with pytest.raises(gate_pause.GateStateReconciliationError):
            supervisor._reconcile_gate_state_or_raise(
                plan_dir,
                plan_id="p1",
                declared_gates=[],
                feature_id="F002",
            )

        assert len(captured) == 1
        ev = captured[0]
        assert ev.kind == "gate_state_reconciliation_failed"
        assert ev.inbox_event == "gate_state_reconciliation_failed"
        assert ev.severity == "escalation"
        assert ev.subtype == gate_pause.GateStateReconciliationError.KIND_UNDECLARED_GATE
        assert ev.evidence_uri == str(persisted)
        assert ev.technical_metadata["gate"] == "pre_merge"
        assert ev.technical_metadata["persisted_state_path"] == str(persisted)

    def test_verdict_mismatch_shape_matches_supervisor_dispatch(self) -> None:
        """Mirrors the kwargs supervisor.py uses at the verdict_mismatch
        dispatch site so the constructor invariants exercise the same shape.

        Inline dispatch in dispatch_volley() isn't drivable from a unit test
        without setting up a full volley pipeline; the INBOX-first ordering is
        covered separately by ``test_supervisor_source_inbox_precedes_dispatch``.
        """
        ev = notify_event.NotifyEvent(
            kind="verdict_mismatch",
            severity=notify_event.SEVERITY_ACTION_REQUIRED,
            plan_id="p1",
            feature_id="F002",
            body="**Verdict mismatch** — narrative=`signed_off` vs structured=`needs_changes` (iter 1).",
            evidence_uri="/tmp/audit-F002-i1.json",
            timestamp=dt.datetime.now(dt.timezone.utc),
            inbox_event="verdict_mismatch",
            subtype="needs_changes",
            iteration_count=1,
            feature_display_name="Pretty F002",
            technical_metadata={
                "narrative_verdict": "signed_off",
                "structured_status": "needs_changes",
                "audit_path": "/tmp/audit-F002-i1.json",
                "iteration": 1,
            },
        )
        assert ev.kind == "verdict_mismatch"
        assert ev.inbox_event == "verdict_mismatch"
        assert ev.severity == "action_required"
        assert ev.subtype == "needs_changes"
        assert ev.iteration_count == 1
        assert ev.evidence_uri == "/tmp/audit-F002-i1.json"
        assert ev.technical_metadata["narrative_verdict"] == "signed_off"
        assert ev.technical_metadata["structured_status"] == "needs_changes"
        assert ev.technical_metadata["audit_path"] == "/tmp/audit-F002-i1.json"
        assert ev.technical_metadata["iteration"] == 1

    def test_verdict_blocked_reconciled_shape_matches_supervisor_dispatch(
        self,
    ) -> None:
        ev = notify_event.NotifyEvent(
            kind="verdict_blocked_reconciled",
            severity=notify_event.SEVERITY_ACTION_REQUIRED,
            plan_id="p1",
            feature_id="F002",
            body="**Verdict reconciled** — auditor said `blocked` but findings classify as `environmental_reproduction_failure` (blocking=False). Promoted to `stopped_environmental_blocker`.",
            evidence_uri="/tmp/plan/INBOX.md",
            timestamp=dt.datetime.now(dt.timezone.utc),
            inbox_event="verdict_blocked_reconciled",
            aggregate_class="environmental_reproduction_failure",
            blocking=False,
            iteration_count=2,
            feature_display_name="Pretty F002",
            technical_metadata={"original_verdict": "blocked"},
        )
        assert ev.kind == "verdict_blocked_reconciled"
        assert ev.inbox_event == "verdict_blocked_reconciled"
        assert ev.severity == "action_required"
        assert ev.aggregate_class == "environmental_reproduction_failure"
        assert ev.blocking is False
        assert ev.iteration_count == 2
        assert ev.evidence_uri == "/tmp/plan/INBOX.md"
        assert ev.technical_metadata["original_verdict"] == "blocked"

    def test_environmental_blocker_short_circuit_shape_matches_supervisor_dispatch(
        self,
    ) -> None:
        ev = notify_event.NotifyEvent(
            kind="environmental_blocker_short_circuit",
            severity=notify_event.SEVERITY_ACTION_REQUIRED,
            plan_id="p1",
            feature_id="F002",
            body="**Environmental blocker** — all round 2 findings classify as `environmental_reproduction_failure`. Volley terminating without another paid implementer round.",
            evidence_uri="/tmp/plan/INBOX.md",
            timestamp=dt.datetime.now(dt.timezone.utc),
            inbox_event="environmental_blocker_short_circuit",
            aggregate_class="environmental_reproduction_failure",
            blocking=False,
            iteration_count=2,
            feature_display_name="Pretty F002",
        )
        assert ev.kind == "environmental_blocker_short_circuit"
        assert ev.inbox_event == "environmental_blocker_short_circuit"
        assert ev.severity == "action_required"
        assert ev.aggregate_class == "environmental_reproduction_failure"
        assert ev.blocking is False
        assert ev.iteration_count == 2
        assert ev.evidence_uri == "/tmp/plan/INBOX.md"

    def test_no_progress_classification_shape_matches_supervisor_dispatch(
        self,
    ) -> None:
        ev = notify_event.NotifyEvent(
            kind="no_progress_classification",
            severity=notify_event.SEVERITY_ACTION_REQUIRED,
            plan_id="p1",
            feature_id="F002",
            body="**No-progress taxonomy** — aggregate=`implementation_defect` (blocking=True). Recommended: remediate",
            evidence_uri="/tmp/plan/INBOX.md",
            timestamp=dt.datetime.now(dt.timezone.utc),
            inbox_event="no_progress_classification",
            aggregate_class="implementation_defect",
            blocking=True,
            feature_display_name="Pretty F002",
        )
        assert ev.kind == "no_progress_classification"
        assert ev.inbox_event == "no_progress_classification"
        assert ev.severity == "action_required"
        assert ev.aggregate_class == "implementation_defect"
        assert ev.blocking is True
        assert ev.evidence_uri == "/tmp/plan/INBOX.md"

    def test_verdict_mismatch_dispatches_from_production_branch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured = _capture_dispatch(monkeypatch)
        _install_dispatch_runtime(monkeypatch, auditor_verdict="signed_off")
        _inject_auditor_envelopes(
            monkeypatch,
            audit_status="needs_changes",
            findings_per_round=[[DEFECT_FINDING]],
        )
        plan_dir = _make_dispatch_plan(
            tmp_path, "2026-05-24-902-feat-notify-event-f002-mismatch"
        )

        with pytest.raises(auditor_taxonomy.VerdictMismatchError):
            supervisor.dispatch_volley(plan_dir, "F002", max_iterations=1)

        events = _events_of_kind(captured, "verdict_mismatch")
        assert len(events) == 1
        ev = events[0]
        assert ev.inbox_event == "verdict_mismatch"
        assert ev.severity == notify_event.SEVERITY_ACTION_REQUIRED
        assert ev.subtype == "needs_changes"
        assert ev.iteration_count == 0
        assert ev.feature_display_name == "Synthetic feature for NotifyEvent F002."
        assert ev.technical_metadata["narrative_verdict"] == "signed_off"
        assert ev.technical_metadata["structured_status"] == "needs_changes"
        assert ev.technical_metadata["audit_path"] == ev.evidence_uri

    def test_verdict_blocked_reconciled_dispatches_from_production_branch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured = _capture_dispatch(monkeypatch)
        _install_dispatch_runtime(monkeypatch, auditor_verdict="blocked")
        _inject_auditor_envelopes(
            monkeypatch,
            audit_status="blocked",
            findings_per_round=[[ENV_FINDING]],
        )
        plan_dir = _make_dispatch_plan(
            tmp_path, "2026-05-24-903-feat-notify-event-f002-reconciled"
        )

        result = supervisor.dispatch_volley(plan_dir, "F002", max_iterations=2)

        assert result.final_status == "stopped_environmental_blocker"
        events = _events_of_kind(captured, "verdict_blocked_reconciled")
        assert len(events) == 1
        ev = events[0]
        assert ev.inbox_event == "verdict_blocked_reconciled"
        assert ev.aggregate_class == "environmental_reproduction_failure"
        assert ev.blocking is False
        assert ev.iteration_count == 1
        assert ev.evidence_uri == str(plan_dir / "INBOX.md")
        assert ev.technical_metadata["original_verdict"] == "blocked"

    def test_environmental_blocker_short_circuit_dispatches_from_production_branch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured = _capture_dispatch(monkeypatch)
        _install_dispatch_runtime(monkeypatch, auditor_verdict="needs_changes")
        _inject_auditor_envelopes(
            monkeypatch,
            audit_status="needs_changes",
            findings_per_round=[[ENV_FINDING]],
        )
        plan_dir = _make_dispatch_plan(
            tmp_path, "2026-05-24-904-feat-notify-event-f002-env"
        )

        result = supervisor.dispatch_volley(plan_dir, "F002", max_iterations=2)

        assert result.final_status == "stopped_environmental_blocker"
        events = _events_of_kind(captured, "environmental_blocker_short_circuit")
        assert len(events) == 1
        ev = events[0]
        assert ev.inbox_event == "environmental_blocker_short_circuit"
        assert ev.aggregate_class == "environmental_reproduction_failure"
        assert ev.blocking is False
        assert ev.iteration_count == 1
        assert ev.evidence_uri == str(plan_dir / "INBOX.md")

    def test_no_progress_classification_dispatches_from_production_branch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured = _capture_dispatch(monkeypatch)
        _install_dispatch_runtime(monkeypatch, auditor_verdict="needs_changes")
        _inject_auditor_envelopes(
            monkeypatch,
            audit_status="needs_changes",
            findings_per_round=[[DEFECT_FINDING], [DEFECT_FINDING]],
        )
        plan_dir = _make_dispatch_plan(
            tmp_path, "2026-05-24-905-feat-notify-event-f002-no-progress"
        )

        result = supervisor.dispatch_volley(plan_dir, "F002", max_iterations=3)

        assert result.final_status == "stopped_no_progress"
        events = _events_of_kind(captured, "no_progress_classification")
        assert len(events) == 1
        ev = events[0]
        assert ev.inbox_event == "no_progress_classification"
        assert ev.aggregate_class == "implementation_defect"
        assert ev.blocking is True
        assert ev.evidence_uri == str(plan_dir / "INBOX.md")

    def test_architecture_regen_failed_dispatches_info(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured = _capture_dispatch(monkeypatch)
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        repo_root = tmp_path / "repo"
        (repo_root / ".git").mkdir(parents=True)

        # Force the hook into the failure branch.
        monkeypatch.setattr(
            architecture_regen_hook,
            "_git_committed_files",
            lambda _: ["scripts/dontpanic_orchestrate/notify_event.py"],
        )

        def boom_regen(*a: Any, **k: Any) -> Path:
            raise RuntimeError("regen exploded")

        monkeypatch.setattr(architecture_regen_hook.architecture, "regen", boom_regen)
        monkeypatch.setattr(inbox, "append_event", lambda *a, **k: None)

        result = architecture_regen_hook.maybe_regen_after_commit(
            plan_dir=plan_dir,
            plan_id="p1",
            feature_id="F002",
            commit_policy_mode="child_commit",
            repo_root=repo_root,
            feature_display_name="Pretty F002",
        )
        assert result is None  # hook degrades gracefully
        assert len(captured) == 1
        ev = captured[0]
        assert ev.kind == "architecture_regen_failed"
        assert ev.inbox_event == "architecture_regen_failed"
        assert ev.severity == "info"
        assert ev.feature_display_name == "Pretty F002"
        assert ev.evidence_uri == str(plan_dir / "INBOX.md")
        assert ev.technical_metadata["error_type"] == "RuntimeError"
        assert (
            ev.technical_metadata["matched_files"]
            == "scripts/dontpanic_orchestrate/notify_event.py"
        )

    def test_architecture_regen_failed_skips_dispatch_when_inbox_append_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured = _capture_dispatch(monkeypatch)
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        repo_root = tmp_path / "repo"
        (repo_root / ".git").mkdir(parents=True)
        monkeypatch.setattr(
            architecture_regen_hook,
            "_git_committed_files",
            lambda _: ["scripts/dontpanic_orchestrate/notify_event.py"],
        )

        def boom_regen(*a: Any, **k: Any) -> Path:
            raise RuntimeError("regen exploded")

        def boom_inbox(*a: Any, **k: Any) -> None:
            raise OSError("INBOX unavailable")

        monkeypatch.setattr(architecture_regen_hook.architecture, "regen", boom_regen)
        monkeypatch.setattr(inbox, "append_event", boom_inbox)

        result = architecture_regen_hook.maybe_regen_after_commit(
            plan_dir=plan_dir,
            plan_id="p1",
            feature_id="F002",
            commit_policy_mode="child_commit",
            repo_root=repo_root,
            feature_display_name="Pretty F002",
        )

        assert result is None
        assert _events_of_kind(captured, "architecture_regen_failed") == []


# ───────────────────────── 5. INBOX-first ordering ─────────────────────────


class TestInboxBeforeDispatch:
    """Plan invariant per D018: INBOX write precedes notify_event.dispatch_event
    at every new emit site."""

    def test_gate_state_reconciliation_failed_inbox_first(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dontpanic_orchestrate import gate_pause

        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()

        calls: list[str] = []
        monkeypatch.setattr(
            inbox, "append_event", lambda *a, **k: calls.append("inbox") or None
        )
        monkeypatch.setattr(notify, "notify", lambda *a, **k: True)

        def fake_dispatch(*a: Any, **k: Any) -> dict[str, bool]:
            calls.append("dispatch_event")
            return {"terminal": False, "discord": False}

        monkeypatch.setattr(supervisor.notify_event, "dispatch_event", fake_dispatch)

        persisted = plan_dir / "gate-state.json"
        persisted.write_text("{}")
        exc_inst = gate_pause.GateStateReconciliationError(
            kind=gate_pause.GateStateReconciliationError.KIND_INCOMPATIBLE_STAGE,
            plan_id="p1",
            gate=None,
            stage="pre_merge",
            persisted_state_path=persisted,
            remediation="see INBOX",
        )

        def boom(*a: Any, **k: Any) -> None:
            raise exc_inst

        monkeypatch.setattr(gate_pause, "reconcile_gate_state", boom)
        monkeypatch.setattr(
            gate_pause, "format_reconciliation_inbox_body", lambda exc: "body"
        )

        with pytest.raises(gate_pause.GateStateReconciliationError):
            supervisor._reconcile_gate_state_or_raise(
                plan_dir, plan_id="p1", declared_gates=[], feature_id="F002"
            )
        assert calls.index("inbox") < calls.index("dispatch_event"), calls

    @pytest.mark.parametrize(
        "inbox_event_name",
        [
            "verdict_mismatch",
            "verdict_blocked_reconciled",
            "environmental_blocker_short_circuit",
            "no_progress_classification",
        ],
    )
    def test_supervisor_source_inbox_precedes_dispatch(
        self, inbox_event_name: str
    ) -> None:
        """For the four inline dispatch sites in dispatch_volley() that aren't
        drivable from a unit test without standing up the full volley
        pipeline, prove the twin-channel ordering invariant by source
        inspection: every ``NotifyEvent(... inbox_event="X" ...)`` constructor
        must be preceded in the same module by a sibling
        ``inbox.append_event(... event="X" ...)`` call.

        Plain string search (not regex) — the production constructors
        contain nested ``body=(...)`` parentheses that defeat a bounded
        regex. Each of the four marker strings is unique in supervisor.py
        and only appears at its paired dispatch site, so substring offsets
        are sufficient evidence.

        This catches drift where someone reorders the calls (or drops the
        INBOX write entirely) without retesting end-to-end.
        """
        src = inspect.getsource(supervisor)
        inbox_marker = f'event="{inbox_event_name}"'
        notify_marker = f'inbox_event="{inbox_event_name}"'
        inbox_pos = src.find(inbox_marker)
        notify_pos = src.find(notify_marker)
        assert inbox_pos != -1, (
            f"missing inbox.append_event(event={inbox_event_name!r}) in supervisor"
        )
        assert notify_pos != -1, (
            f"missing NotifyEvent(inbox_event={inbox_event_name!r}) in supervisor"
        )
        # Twin-channel pairing per D018: INBOX append_event() is the
        # truth-of-record and must precede its NotifyEvent dispatch.
        assert inbox_pos < notify_pos, (
            f"INBOX append_event must precede NotifyEvent dispatch for "
            f"{inbox_event_name!r}; got inbox@{inbox_pos} vs notify@{notify_pos}"
        )

    def test_architecture_regen_failed_inbox_first(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        repo_root = tmp_path / "repo"
        (repo_root / ".git").mkdir(parents=True)
        calls: list[str] = []
        monkeypatch.setattr(
            inbox, "append_event", lambda *a, **k: calls.append("inbox") or None
        )
        monkeypatch.setattr(
            architecture_regen_hook,
            "_git_committed_files",
            lambda _: ["scripts/dontpanic_orchestrate/notify_event.py"],
        )

        def boom_regen(*a: Any, **k: Any) -> Path:
            raise RuntimeError("regen exploded")

        monkeypatch.setattr(architecture_regen_hook.architecture, "regen", boom_regen)

        def fake_dispatch(*a: Any, **k: Any) -> dict[str, bool]:
            calls.append("dispatch_event")
            return {"terminal": False, "discord": False}

        monkeypatch.setattr(
            architecture_regen_hook.notify_event, "dispatch_event", fake_dispatch
        )
        architecture_regen_hook.maybe_regen_after_commit(
            plan_dir=plan_dir,
            plan_id="p1",
            feature_id="F002",
            commit_policy_mode="child_commit",
            repo_root=repo_root,
            feature_display_name=None,
        )
        assert "inbox" in calls and "dispatch_event" in calls
        assert calls.index("inbox") < calls.index("dispatch_event"), calls


# ───────────────────────── 6. Existing sinks tolerate new fields ─────────────────────────


class TestSinkRenderingDoesNotRegress:
    """A minimal-shape event (no new fields populated) must still render via
    both the discord sink and the terminal-notifier shim without raising."""

    def test_discord_sink_ignores_unset_new_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 204
            ev = notify_event.NotifyEvent(
                kind="signoff",
                severity="info",
                plan_id="p",
                feature_id="F002",
                body="x",
            )
            # Round-trip through the sink — no exception, returns True.
            assert notify_discord.notify(ev) is True

    def test_terminal_shim_ignores_unset_new_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: dict[str, Any] = {}

        def capture(*args: Any, **kwargs: Any) -> bool:
            called["args"] = args
            called["kwargs"] = kwargs
            return True

        monkeypatch.setattr(notify, "notify", capture)
        ev = notify_event.NotifyEvent(
            kind="signoff",
            severity="info",
            plan_id="p",
            feature_id="F002",
            body="x",
        )
        assert notify.notify_event(ev) is True
        assert called["args"][0] == "Jarvis [p]"

    def test_discord_sink_renders_populated_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 204
            ev = notify_event.NotifyEvent(
                kind="verdict_mismatch",
                severity="action_required",
                plan_id="p",
                feature_id="F002",
                body="x",
                evidence_uri="/tmp/audit.json",
                inbox_event="verdict_mismatch",
                subtype="needs_changes",
                iteration_count=1,
                technical_metadata={
                    "narrative_verdict": "signed_off",
                    "structured_status": "needs_changes",
                    "iteration": 1,
                },
            )
            assert notify_discord.notify(ev) is True
