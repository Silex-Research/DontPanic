"""F008 — engagement-surface synthetic e2e + per-module tests.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_f008_engagement_surface.py
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import (  # noqa: E402
    cli,
    gate_pause,
    inbox,
    notify,
    signoff_writer,
    supervisor,
)
from jarvis_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from jarvis_orchestrate.executors.base import BaseExecutor, DispatchResult, DispatchTask  # noqa: E402


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ──────────────────────────────  inbox  ──────────────────────────────


def test_inbox_round_trip() -> None:
    print("\n[test] inbox_round_trip ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        e1 = inbox.append_event(pd, event="volley_start", plan_id="p1", body="iter 0 starting")
        e2 = inbox.append_event(pd, event="gate_hit", plan_id="p1", gate="pre_impl", body="needs approval")
        events = inbox.read_events(pd)
        assert len(events) == 2
        assert events[0].event == "volley_start"
        assert events[1].headers["gate"] == "pre_impl"
        latest = inbox.latest_event(pd, "gate_hit")
        assert latest is not None and latest.headers["gate"] == "pre_impl"
    print("  ✓ append + read round-trips with extra headers preserved")


def test_inbox_tolerant_of_operator_body_edits() -> None:
    print("\n[test] inbox_tolerant_of_operator_body_edits ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        inbox.append_event(pd, event="gate_hit", plan_id="p1", body="original body")
        # Operator opens INBOX.md and adds a note in the body.
        path = inbox.inbox_path(pd)
        content = path.read_text()
        path.write_text(content.replace("original body", "original body\n\n(operator note: investigated, ok)"))
        events = inbox.read_events(pd)
        assert len(events) == 1 and events[0].headers["event"] == "gate_hit"
        assert "operator note" in events[0].body
    print("  ✓ parser ignores operator-added body lines without breaking")


# ──────────────────────────────  notify  ──────────────────────────────


def test_notify_disable_env_short_circuits() -> None:
    print("\n[test] notify_disable_env_short_circuits ...")
    saved = os.environ.get(notify.DISABLE_ENV)
    try:
        os.environ[notify.DISABLE_ENV] = "1"
        assert notify.is_available() is False
        assert notify.notify("title", "msg") is False
    finally:
        if saved is None:
            os.environ.pop(notify.DISABLE_ENV, None)
        else:
            os.environ[notify.DISABLE_ENV] = saved
    print("  ✓ JARVIS_NOTIFY_DISABLE=1 silences notify() without raising")


def test_notify_missing_binary_returns_false() -> None:
    print("\n[test] notify_missing_binary_returns_false ...")
    # When binary absent (this CI machine has none), is_available is False and
    # notify returns False — never raises, even with empty PATH-like env.
    saved_path = os.environ.get("PATH")
    try:
        os.environ["PATH"] = "/nonexistent"
        # Force re-resolution by making the call (function uses shutil.which each time).
        assert notify.is_available() is False
        assert notify.notify("t", "m") is False
    finally:
        if saved_path is not None:
            os.environ["PATH"] = saved_path
    print("  ✓ missing binary path → notify is_available=False, notify()→False")


# ──────────────────────────────  gate_pause  ──────────────────────────────


def test_gate_pause_evaluate_and_clear() -> None:
    print("\n[test] gate_pause_evaluate_and_clear ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        declared = ["pre_impl", "on_escalation"]
        check = gate_pause.evaluate(pd, declared)
        assert check.paused and check.unmet == declared
        assert gate_pause.approve_gate(pd, "pre_impl", plan_id="p")
        assert not gate_pause.approve_gate(pd, "pre_impl", plan_id="p")  # idempotent
        check = gate_pause.evaluate(pd, declared)
        assert check.unmet == ["on_escalation"]
        newly = gate_pause.resume_all(pd, plan_id="p", declared_gates=declared)
        assert newly == ["on_escalation"]
        assert not gate_pause.evaluate(pd, declared).paused
    print("  ✓ approve clears one; resume_all clears the rest; idempotent")


def test_gate_pause_record_pause_writes_history() -> None:
    print("\n[test] gate_pause_record_pause_writes_history ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        gate_pause.record_pause(pd, plan_id="p", pause_gates=["pre_impl"])
        state = json.loads(gate_pause.gate_state_path(pd).read_text())
        actions = [h["action"] for h in state["history"]]
        assert "pause" in actions
        assert state["pause_gates"] == ["pre_impl"]
    print("  ✓ record_pause persists history entry + pause_gates")


# ──────────────────────────────  signoff_writer  ──────────────────────────────


def test_signoff_writer_validates_against_schema() -> None:
    print("\n[test] signoff_writer_validates_against_schema ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        ad = pd / "audit"
        ad.mkdir()
        for ag, role in [("claude", "implementer"), ("codex", "auditor")]:
            (ad / f"{ag}-{role}-i0.json").write_text(json.dumps({
                "task_id": "2026-04-26-100-infra-signoff-smoke",
                "audit_id": f"2026-04-26-100-infra-signoff-smoke#{ag}#0",
                "agent": ag, "agent_role": role, "iteration": 0,
                "started_at": _iso_now(), "completed_at": _iso_now(),
                "audit_status": "signed_off", "summary": "ok",
                "quota_consumed": {"percent_weekly": 1.0},
            }))
        out = signoff_writer.write_signoff(
            plan_id="2026-04-26-100-infra-signoff-smoke",
            tier="trivial",
            iteration=0,
            agents_in_panel=["claude", "codex"],
            audit_paths=sorted(ad.glob("*.json")),
            plan_dir=pd,
            volley_status="signed_off",
        )
        data = json.loads(out.read_text())
        assert data["signoff"] is True
        assert data["next_action"] == "merge"
        assert data["vote_summary"]["signed_off_count"] == 2
        assert all(a.startswith("audit/") for a in data["audits"])
    print("  ✓ signoff.json schema-valid; vote_summary + next_action correct on signed_off")


def test_signoff_writer_blocked_state() -> None:
    print("\n[test] signoff_writer_blocked_state ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        ad = pd / "audit"
        ad.mkdir()
        (ad / "claude-implementer-i0.json").write_text(json.dumps({
            "task_id": "2026-04-26-101-infra-signoff-blocked",
            "audit_id": "2026-04-26-101-infra-signoff-blocked#claude#0",
            "agent": "claude", "agent_role": "implementer", "iteration": 0,
            "started_at": _iso_now(), "completed_at": _iso_now(),
            "audit_status": "blocked", "summary": "blocked",
        }))
        out = signoff_writer.write_signoff(
            plan_id="2026-04-26-101-infra-signoff-blocked",
            tier="local",
            iteration=0,
            agents_in_panel=["claude"],
            audit_paths=sorted(ad.glob("*.json")),
            plan_dir=pd,
            volley_status="blocked",
        )
        data = json.loads(out.read_text())
        assert data["signoff"] is False
        assert data["next_action"] == "blocked_awaiting_human"
    print("  ✓ blocked volley → signoff=false, next_action=blocked_awaiting_human")


# ──────────────────────────────  e2e: pause → approve → resume → signoff  ──────────────────────────────


_PLAN_ID_TEMPLATE = "2026-04-26-{n:03d}-infra-{slug}"


def _make_plan(repo: Path, plan_id: str, *, target_project: str = "none", gates: list[str] | None = None) -> Path:
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    gates_yaml = "\n".join(f"  - {g}" for g in (gates or ["pre_impl"]))
    plan_md = f"""---
id: {plan_id}
title: F008 e2e synthetic
type: infra
tier: trivial
status: active
date: "2026-04-26"
description: Synthetic plan for F008 engagement-surface e2e tests.
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

# F008 e2e synthetic

## Target

```yaml
target_env: dev
target_project: {target_project}
```
"""
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001", "category": "test", "phase": 0,
                "description": "Synthetic feature for F008 e2e.",
                "steps": ["scripted"],
                "acceptance": "Engagement surface fires.",
                "passes": False, "depends_on": [],
            }
        ],
    }
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(json.dumps(features, indent=2) + "\n")
    return plan_dir


class _CountingExecutor(BaseExecutor):
    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.dispatches: list[DispatchTask] = []

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.dispatches.append(task)
        s = (
            f"Repo: synthetic\nEnv: dev\nProject: (none)\n"
            f"Synthetic {task.agent_role} round {task.iteration}; signed off."
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


def _bypass_quota():
    saved = supervisor._quota_gate
    supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")
    return saved


def test_e2e_pause_then_approve_then_resume() -> None:
    print("\n[test] e2e_pause_then_approve_then_resume ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-200-infra-e2e-pause", gates=["pre_impl", "on_escalation"])
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = _bypass_quota()
        AGENT_REGISTRY["claude"] = lambda: impl
        AGENT_REGISTRY["codex"] = lambda: aud
        # Disable real notifier in tests.
        os.environ[notify.DISABLE_ENV] = "1"
        try:
            # Step 1: first dispatch must pause without calling executors.
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert result.final_status == "paused_on_gate", result
            assert len(impl.dispatches) == 0 and len(aud.dispatches) == 0
            events = inbox.read_events(plan_dir)
            assert any(e.event == "gate_hit" for e in events), [e.event for e in events]
            state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
            assert "pause_gates" in state and "pre_impl" in state["pause_gates"]
            print("  ✓ first dispatch paused; no executor called; INBOX gate_hit + state file written")

            # Step 2: operator approves one gate via CLI; supervisor should still pause.
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["approve", str(plan_dir), "pre_impl"])
            assert rc == 0
            result2 = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert result2.final_status == "paused_on_gate", result2
            assert len(impl.dispatches) == 0
            print("  ✓ partial approve still pauses on remaining gate")

            # Step 3: operator resumes all → next dispatch enters volley + signs off.
            with redirect_stdout(buf):
                rc = cli.main(["resume", str(plan_dir)])
            assert rc == 0
            result3 = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert result3.final_status == "signed_off", result3
            assert len(impl.dispatches) == 1 and len(aud.dispatches) == 1

            # Step 4: signoff.json was written and validates.
            sp = signoff_writer.signoff_path(plan_dir, "2026-04-26-200-infra-e2e-pause")
            assert sp.is_file(), sp
            data = json.loads(sp.read_text())
            assert data["signoff"] is True and data["next_action"] == "merge"
            print("  ✓ resume_all → executors run; signoff.json written and signed=true")

            # Step 5: INBOX events include the full progression.
            events = inbox.read_events(plan_dir)
            event_types = [e.event for e in events]
            for required in ("gate_hit", "gate_cleared", "resumed", "volley_start", "volley_terminal"):
                assert required in event_types, (required, event_types)
            print("  ✓ INBOX captures gate_hit, gate_cleared, resumed, volley_start, volley_terminal")
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota
            os.environ.pop(notify.DISABLE_ENV, None)


# ──────────────────────────────  AC-honesty fixes (D073-amend)  ──────────────────────────────


def test_cli_approve_no_false_warning_for_declared_gate() -> None:
    """Fix#1: CLI approve must not warn when gate IS in plan.human_gates."""
    print("\n[test] cli_approve_no_false_warning_for_declared_gate ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-300-infra-cli-approve-warn", gates=["pre_impl"])
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        from contextlib import redirect_stderr
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = cli.main(["approve", str(plan_dir), "pre_impl"])
        assert rc == 0
        assert "WARNING" not in buf_err.getvalue(), buf_err.getvalue()
        # Sanity: an undeclared gate still warns
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            cli.main(["approve", str(plan_dir), "totally_made_up_gate"])
        assert "WARNING" in buf_err.getvalue()
    print("  ✓ declared gate → no warning; undeclared gate → warning")


def test_signoff_writer_stopped_cap_maps_to_remediate() -> None:
    """Fix#2: stopped_cap (what supervisor actually emits) must map to remediate."""
    print("\n[test] signoff_writer_stopped_cap_maps_to_remediate ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        ad = pd / "audit"
        ad.mkdir()
        (ad / "claude-implementer-i0.json").write_text(json.dumps({
            "task_id": "2026-04-26-301-infra-cap-mapping",
            "audit_id": "2026-04-26-301-infra-cap-mapping#claude#0",
            "agent": "claude", "agent_role": "implementer", "iteration": 0,
            "started_at": _iso_now(), "completed_at": _iso_now(),
            "audit_status": "needs_changes", "summary": "...",
        }))
        out = signoff_writer.write_signoff(
            plan_id="2026-04-26-301-infra-cap-mapping",
            tier="trivial", iteration=0,
            agents_in_panel=["claude"],
            audit_paths=sorted(ad.glob("*.json")),
            plan_dir=pd,
            volley_status="stopped_cap",
        )
        data = json.loads(out.read_text())
        assert data["next_action"] == "remediate", data
    print("  ✓ stopped_cap → next_action=remediate")


def test_approve_clears_pause_marker_when_all_resolved() -> None:
    """Fix#3: paused_at + pause_gates fields must be cleared once unmet set drops to []."""
    print("\n[test] approve_clears_pause_marker_when_all_resolved ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        gate_pause.record_pause(pd, plan_id="p", pause_gates=["pre_impl"])
        # Approve the only pause gate.
        gate_pause.approve_gate(pd, "pre_impl", plan_id="p")
        state = json.loads(gate_pause.gate_state_path(pd).read_text())
        assert "paused_at" not in state, state
        assert "pause_gates" not in state, state
    print("  ✓ approving the last pause gate clears paused_at + pause_gates")


def test_resume_clears_pause_marker_when_all_resolved() -> None:
    """Fix#3 (resume_all variant)."""
    print("\n[test] resume_clears_pause_marker_when_all_resolved ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        gate_pause.record_pause(pd, plan_id="p", pause_gates=["pre_impl", "on_escalation"])
        gate_pause.resume_all(pd, plan_id="p", declared_gates=["pre_impl", "on_escalation"])
        state = json.loads(gate_pause.gate_state_path(pd).read_text())
        assert "paused_at" not in state and "pause_gates" not in state, state
    print("  ✓ resume_all over all pause gates clears the marker")


def test_partial_approve_keeps_pause_marker() -> None:
    """Fix#3: marker must persist until ALL pause_gates are cleared."""
    print("\n[test] partial_approve_keeps_pause_marker ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        gate_pause.record_pause(pd, plan_id="p", pause_gates=["pre_impl", "on_escalation"])
        gate_pause.approve_gate(pd, "pre_impl", plan_id="p")
        state = json.loads(gate_pause.gate_state_path(pd).read_text())
        assert "pause_gates" in state and "on_escalation" in state["pause_gates"]
    print("  ✓ partial clear keeps pause marker pending the rest")


def test_quota_warn_inbox_event_fires_at_soft_threshold() -> None:
    """Fix#4: supervisor emits INBOX quota_warn when pct ≥ SOFT_THRESHOLD_PERCENT."""
    print("\n[test] quota_warn_inbox_event_fires_at_soft_threshold ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-302-infra-quota-warn-event", gates=["pre_impl"])
        # Pre-clear gates so volley enters the loop and the quota check fires.
        gate_pause.resume_all(plan_dir, plan_id="2026-04-26-302-infra-quota-warn-event",
                              declared_gates=["pre_impl"])
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = supervisor._quota_gate
        AGENT_REGISTRY["claude"] = lambda: impl
        AGENT_REGISTRY["codex"] = lambda: aud
        # Stub _quota_gate to return a soft-warn percentage.
        supervisor._quota_gate = lambda agent: (95.0, f"[quota] {agent}: 95.0% (stubbed)")
        os.environ[notify.DISABLE_ENV] = "1"
        try:
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert result.final_status == "signed_off", result
            events = inbox.read_events(plan_dir)
            warns = [e for e in events if e.event == "quota_warn"]
            assert len(warns) >= 2, [e.event for e in events]  # impl + aud
            agents_warned = {w.headers.get("agent") for w in warns}
            assert agents_warned == {"claude", "codex"}, agents_warned
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota
            os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ both agent quota gates above threshold emit INBOX quota_warn")


def test_error_inbox_event_fires_on_executor_failure() -> None:
    """Fix#4: supervisor emits INBOX error when executor returns success=False."""
    print("\n[test] error_inbox_event_fires_on_executor_failure ...")

    class _FailingExecutor(BaseExecutor):
        def __init__(self, agent: str) -> None:
            super().__init__()
            self.agent_name = agent
            self.cli_binary = None
        def is_available(self) -> bool:
            return True
        def dispatch(self, task: DispatchTask) -> DispatchResult:
            return DispatchResult(
                agent=self.agent_name, agent_role=task.agent_role,
                iteration=task.iteration,
                started_at=_iso_now(), completed_at=_iso_now(),
                success=False, summary="", raw_response="",
                error="synthetic CLI failure",
            )

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-303-infra-error-event", gates=["pre_impl"])
        gate_pause.resume_all(plan_dir, plan_id="2026-04-26-303-infra-error-event",
                              declared_gates=["pre_impl"])
        impl = _FailingExecutor("claude")
        aud = _CountingExecutor("codex")
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = _bypass_quota()
        AGENT_REGISTRY["claude"] = lambda: impl
        AGENT_REGISTRY["codex"] = lambda: aud
        os.environ[notify.DISABLE_ENV] = "1"
        try:
            supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            events = inbox.read_events(plan_dir)
            errors = [e for e in events if e.event == "error"]
            assert len(errors) >= 1, [e.event for e in events]
            assert errors[0].headers.get("agent") == "claude"
            assert "synthetic CLI failure" in errors[0].body
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota
            os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ failed executor dispatch emits INBOX error with agent + cause")


# ──────────────────────────────  driver  ──────────────────────────────


def main() -> int:
    test_inbox_round_trip()
    test_inbox_tolerant_of_operator_body_edits()
    test_notify_disable_env_short_circuits()
    test_notify_missing_binary_returns_false()
    test_gate_pause_evaluate_and_clear()
    test_gate_pause_record_pause_writes_history()
    test_signoff_writer_validates_against_schema()
    test_signoff_writer_blocked_state()
    test_e2e_pause_then_approve_then_resume()
    test_cli_approve_no_false_warning_for_declared_gate()
    test_signoff_writer_stopped_cap_maps_to_remediate()
    test_approve_clears_pause_marker_when_all_resolved()
    test_resume_clears_pause_marker_when_all_resolved()
    test_partial_approve_keeps_pause_marker()
    test_quota_warn_inbox_event_fires_at_soft_threshold()
    test_error_inbox_event_fires_on_executor_failure()
    print("\n✓ F008 engagement-surface tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
