"""F007 Slice 2 — admission policy + interactive backoff + class-based bypass.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_f007_quota_admission.py
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import (  # noqa: E402
    cli,
    gate_pause,
    inbox,
    interactive_state,
    notify,
    quota_admission,
    supervisor,
)
from jarvis_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from jarvis_orchestrate.executors.base import BaseExecutor, DispatchResult, DispatchTask  # noqa: E402


# ────────────────────────  test infrastructure  ────────────────────────


def _quota_state_path() -> Path:
    """Resolve the per-test quota_state.json path the conftest fixture set."""
    return Path(os.environ["JARVIS_QUOTA_STATE_PATH"])


def _write_quota_state(claude_pct: float | None) -> None:
    """Mock ~/.jarvis/quota_state.json content for the current test."""
    state = {"models": {}}
    if claude_pct is not None:
        state["models"]["claude"] = {"percent_weekly": claude_pct, "plan": "x"}
    _quota_state_path().parent.mkdir(parents=True, exist_ok=True)
    _quota_state_path().write_text(json.dumps(state))


def _make_plan(repo: Path, plan_id: str, *, tier: str = "trivial") -> Path:
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_md = f"""---
id: {plan_id}
title: F007 admission test
type: infra
tier: {tier}
status: active
date: "2026-04-26"
description: Synthetic plan for F007 admission policy tests.
agents_required:
  - claude
  - codex
human_gates: []
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# F007 admission test

## Target

```yaml
target_env: dev
target_project: none
```
"""
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(json.dumps({
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [{
            "id": "F001", "category": "test", "phase": 0,
            "description": "Synthetic feature for F007 admission tests.",
            "steps": ["scripted"],
            "acceptance": "admission gates trip on quota threshold and interactive backoff.",
            "passes": False, "depends_on": [],
        }],
    }, indent=2) + "\n")
    return plan_dir


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _ScriptedExecutor(BaseExecutor):
    def __init__(self, agent: str, *, role: str, summaries: list[str]) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.role = role
        self.summaries = list(summaries)
        self.idx = 0

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        i = self.idx
        self.idx += 1
        s = self.summaries[i] if i < len(self.summaries) else self.summaries[-1]
        return DispatchResult(
            agent=self.agent_name, agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(), completed_at=_iso_now(),
            success=True, summary=s, raw_response=s,
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _bypass_quota_gate():
    """Prevent supervisor._quota_gate from short-circuiting on the per-test
    quota_state.json mocks (we want to drive admission specifically)."""
    orig = supervisor._quota_gate
    supervisor._quota_gate = lambda agent: (None, "[quota-bypass-test]")
    return orig


def _force_auditor_signed_off():
    """Wrap supervisor._run_round so auditor-role audits are signed_off — used
    by bypass tests that need dispatch to actually run-through (not pause)."""
    orig = supervisor._run_round

    def maybe_force(*args, **kwargs):
        path = orig(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            data = json.loads(path.read_text())
            data["audit_status"] = "signed_off"
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return path

    supervisor._run_round = maybe_force
    return orig


# ──────────────────────────────  pure unit tests  ──────────────────────────────


def test_classify_dispatch_precedence() -> None:
    """mode_override (interactive|autonomous) > env > plan.tier=p0 > autonomous"""
    print("\n[test] classify_dispatch_precedence ...")
    # Default → autonomous
    assert quota_admission.classify_dispatch(None) == quota_admission.DispatchClass.AUTONOMOUS
    assert quota_admission.classify_dispatch("trivial") == quota_admission.DispatchClass.AUTONOMOUS
    # plan.tier == p0 → P0
    assert quota_admission.classify_dispatch("p0") == quota_admission.DispatchClass.P0
    # mode_override beats tier
    assert quota_admission.classify_dispatch("p0", mode_override="interactive") == quota_admission.DispatchClass.INTERACTIVE
    # JARVIS_RUN_MODE beats tier (when no mode_override)
    os.environ["JARVIS_RUN_MODE"] = "interactive"
    try:
        assert quota_admission.classify_dispatch("trivial") == quota_admission.DispatchClass.INTERACTIVE
    finally:
        os.environ.pop("JARVIS_RUN_MODE", None)
    # mode_override beats env
    os.environ["JARVIS_RUN_MODE"] = "interactive"
    try:
        assert quota_admission.classify_dispatch(None, mode_override="autonomous") == quota_admission.DispatchClass.AUTONOMOUS
    finally:
        os.environ.pop("JARVIS_RUN_MODE", None)
    print("  ✓ precedence: mode_override > env > plan.tier=p0 > autonomous")


def test_p0_is_plan_derived_only_not_overridable() -> None:
    """D075-amend2: p0 is plan-derived only. mode_override='p0' and
    JARVIS_RUN_MODE=p0 are ignored — they would silently expand the
    emergency-lane bypass surface to non-P0 plans."""
    print("\n[test] p0_is_plan_derived_only_not_overridable ...")
    # mode_override='p0' on a non-P0 plan must NOT promote.
    assert quota_admission.classify_dispatch(
        "trivial", mode_override="p0"
    ) == quota_admission.DispatchClass.AUTONOMOUS
    # Same via env.
    os.environ["JARVIS_RUN_MODE"] = "p0"
    try:
        assert quota_admission.classify_dispatch(
            "trivial"
        ) == quota_admission.DispatchClass.AUTONOMOUS
    finally:
        os.environ.pop("JARVIS_RUN_MODE", None)
    # And the override doesn't even shadow plan-derived P0 (irrelevant
    # value drops through to the next rule).
    os.environ["JARVIS_RUN_MODE"] = "p0"
    try:
        assert quota_admission.classify_dispatch(
            "p0"
        ) == quota_admission.DispatchClass.P0
    finally:
        os.environ.pop("JARVIS_RUN_MODE", None)
    # Plain plan-derived P0 still works (the legitimate path).
    assert quota_admission.classify_dispatch("p0") == quota_admission.DispatchClass.P0
    print("  ✓ p0 is plan-derived only; CLI/env 'p0' values are ignored")


def test_cli_mode_argparse_rejects_p0() -> None:
    """The CLI argparse choices must reject --mode p0 with a non-zero exit
    code (argparse exits 2 on choice violations). Belt-and-suspenders with
    classify_dispatch's library-level guard."""
    print("\n[test] cli_mode_argparse_rejects_p0 ...")
    import contextlib
    from jarvis_orchestrate import cli as cli_mod
    buf_err = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td), "2026-04-26-525-infra-f007-no-p0-cli")
        with contextlib.redirect_stderr(buf_err):
            try:
                rc = cli_mod.main([str(plan_dir), "--mode", "p0", "--volley"])
            except SystemExit as exc:
                rc = exc.code
        # argparse choice rejection → exit 2
        assert rc == 2, rc
        assert "invalid choice" in buf_err.getvalue() or "'p0'" in buf_err.getvalue(), buf_err.getvalue()
    print("  ✓ argparse choices reject --mode p0 at the CLI boundary")


def test_evaluate_quota_threshold_default_70() -> None:
    print("\n[test] evaluate_quota_threshold_default_70 ...")
    _write_quota_state(claude_pct=75.0)
    result = quota_admission.evaluate_quota_threshold(["claude", "codex"])
    assert result.over_threshold and result.offending_agent == "claude"
    assert result.observed_pct == 75.0 and result.threshold == 70.0
    # under threshold → no trip
    _write_quota_state(claude_pct=60.0)
    assert not quota_admission.evaluate_quota_threshold(["claude", "codex"]).over_threshold
    # No quota state → no trip
    _quota_state_path().unlink()
    assert not quota_admission.evaluate_quota_threshold(["claude"]).over_threshold
    print("  ✓ default 70% threshold + missing-state safety")


def test_evaluate_quota_threshold_env_override() -> None:
    print("\n[test] evaluate_quota_threshold_env_override ...")
    _write_quota_state(claude_pct=55.0)
    os.environ["JARVIS_QUOTA_DEFER_THRESHOLD"] = "50.0"
    try:
        r = quota_admission.evaluate_quota_threshold(["claude"])
        assert r.over_threshold and r.threshold == 50.0
    finally:
        os.environ.pop("JARVIS_QUOTA_DEFER_THRESHOLD", None)
    print("  ✓ JARVIS_QUOTA_DEFER_THRESHOLD honored")


def test_evaluate_interactive_backoff_window() -> None:
    print("\n[test] evaluate_interactive_backoff_window ...")
    # No touch → not in backoff
    assert not quota_admission.evaluate_interactive_backoff(["claude"]).within_backoff
    # Recent touch → within
    interactive_state.touch("claude")
    r = quota_admission.evaluate_interactive_backoff(["claude"])
    assert r.within_backoff and r.minutes_remaining is not None
    # Older touch (40 min ago, default 30-min window) → out of window
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=40)
    interactive_state.touch("claude", at=old)
    r2 = quota_admission.evaluate_interactive_backoff(["claude"])
    assert not r2.within_backoff
    # Claude not in agents → no trip even with fresh touch
    interactive_state.touch("claude")
    r3 = quota_admission.evaluate_interactive_backoff(["codex", "gemini"])
    assert not r3.within_backoff
    print("  ✓ backoff window honored + claude-only scope")


# ──────────────────────────────  AC scenarios  ──────────────────────────────


def _setup_volley(repo: Path, plan_id: str, *, tier: str = "trivial") -> Path:
    plan_dir = _make_plan(repo, plan_id, tier=tier)
    impl = _ScriptedExecutor("claude", role="implementer", summaries=["impl"])
    aud = _ScriptedExecutor("codex", role="auditor", summaries=["aud"])
    AGENT_REGISTRY["claude"] = lambda: impl
    AGENT_REGISTRY["codex"] = lambda: aud
    return plan_dir


def test_ac_1_autonomous_at_75_pct_defers() -> None:
    """AC #1: Mock quota_state.json claude=75% → autonomous plan returns
    paused_on_gate with defer:quota_threshold."""
    print("\n[test] ac_1_autonomous_at_75_pct_defers ...")
    _write_quota_state(75.0)
    saved_registry = dict(AGENT_REGISTRY)
    saved_quota = _bypass_quota_gate()
    os.environ[notify.DISABLE_ENV] = "1"
    try:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _setup_volley(Path(td), "2026-04-26-500-infra-f007-quota")
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert result.final_status == "paused_on_gate", result
            assert "defer:quota_threshold" in result.reason, result.reason
            assert "defer:quota_threshold" in gate_pause.active_defers(plan_dir)
            events = inbox.read_events(plan_dir)
            assert any(e.event == "defer_tripped" for e in events)
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        supervisor._quota_gate = saved_quota
        os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ autonomous + 75% claude → defer:quota_threshold")


def test_ac_2_p0_bypasses_quota_threshold() -> None:
    """AC #2 + clarification: p0 plans bypass the 70% defer threshold."""
    print("\n[test] ac_2_p0_bypasses_quota_threshold ...")
    _write_quota_state(75.0)
    saved_registry = dict(AGENT_REGISTRY)
    saved_quota = _bypass_quota_gate()
    saved_run = _force_auditor_signed_off()
    os.environ[notify.DISABLE_ENV] = "1"
    try:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _setup_volley(Path(td), "2026-04-26-501-infra-f007-p0", tier="p0")
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            # p0 bypasses the gate; it dispatches normally.
            assert result.final_status != "paused_on_gate", result
            assert "defer:quota_threshold" not in gate_pause.active_defers(plan_dir)
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        supervisor._quota_gate = saved_quota
        supervisor._run_round = saved_run
        os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ tier=p0 bypasses quota threshold")


def test_ac_3_interactive_mode_bypasses_quota_threshold() -> None:
    """AC #3 + clarification: --mode interactive bypasses both gates."""
    print("\n[test] ac_3_interactive_mode_bypasses_quota_threshold ...")
    _write_quota_state(75.0)
    saved_registry = dict(AGENT_REGISTRY)
    saved_quota = _bypass_quota_gate()
    saved_run = _force_auditor_signed_off()
    os.environ[notify.DISABLE_ENV] = "1"
    try:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _setup_volley(Path(td), "2026-04-26-502-infra-f007-int")
            result = supervisor.dispatch_volley(
                plan_dir, "F001", max_iterations=1, mode="interactive"
            )
            assert result.final_status != "paused_on_gate", result
            assert "defer:quota_threshold" not in gate_pause.active_defers(plan_dir)
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        supervisor._quota_gate = saved_quota
        supervisor._run_round = saved_run
        os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ mode=interactive bypasses both admission gates")


def test_ac_4_interactive_backoff_15min_ago_defers() -> None:
    """AC #4: claude-touch 15 min ago + Claude in agents_required + autonomous
    → paused_on_gate with defer:interactive_backoff."""
    print("\n[test] ac_4_interactive_backoff_15min_ago_defers ...")
    # No quota issue
    _write_quota_state(50.0)
    # Touch 15 min ago
    fifteen_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=15)
    interactive_state.touch("claude", at=fifteen_ago)
    saved_registry = dict(AGENT_REGISTRY)
    saved_quota = _bypass_quota_gate()
    os.environ[notify.DISABLE_ENV] = "1"
    try:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _setup_volley(Path(td), "2026-04-26-503-infra-f007-back")
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert result.final_status == "paused_on_gate", result
            assert "defer:interactive_backoff" in result.reason, result.reason
            active = gate_pause.active_defers(plan_dir)
            assert "defer:interactive_backoff" in active
            # Quota gate should NOT have tripped (50% < 70%)
            assert "defer:quota_threshold" not in active
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        supervisor._quota_gate = saved_quota
        os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ 15-min touch → defer:interactive_backoff (alone, not quota_threshold)")


def test_ac_5_p0_and_interactive_bypass_backoff() -> None:
    """AC #5: same touch state → p0 dispatches; interactive dispatches."""
    print("\n[test] ac_5_p0_and_interactive_bypass_backoff ...")
    _write_quota_state(50.0)
    fifteen_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=15)
    interactive_state.touch("claude", at=fifteen_ago)
    saved_registry = dict(AGENT_REGISTRY)
    saved_quota = _bypass_quota_gate()
    saved_run = _force_auditor_signed_off()
    os.environ[notify.DISABLE_ENV] = "1"
    try:
        with tempfile.TemporaryDirectory() as td:
            plan_dir_p0 = _setup_volley(Path(td), "2026-04-26-504-infra-f007-p0bp", tier="p0")
            r_p0 = supervisor.dispatch_volley(plan_dir_p0, "F001", max_iterations=1)
            assert r_p0.final_status != "paused_on_gate", r_p0
            assert "defer:interactive_backoff" not in gate_pause.active_defers(plan_dir_p0)

            plan_dir_int = _setup_volley(Path(td), "2026-04-26-505-infra-f007-intbp")
            r_int = supervisor.dispatch_volley(
                plan_dir_int, "F001", max_iterations=1, mode="interactive"
            )
            assert r_int.final_status != "paused_on_gate", r_int
            assert "defer:interactive_backoff" not in gate_pause.active_defers(plan_dir_int)
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        supervisor._quota_gate = saved_quota
        supervisor._run_round = saved_run
        os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ p0 + interactive both bypass interactive_backoff")


def test_ac_6_auto_clear_on_condition_resolved() -> None:
    """AC #6: After threshold drops or 30 min elapsed, the same plan dispatches
    on the next run without operator action — defer:* auto-clears."""
    print("\n[test] ac_6_auto_clear_on_condition_resolved ...")
    saved_registry = dict(AGENT_REGISTRY)
    saved_quota = _bypass_quota_gate()
    saved_run = _force_auditor_signed_off()
    os.environ[notify.DISABLE_ENV] = "1"
    try:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _setup_volley(Path(td), "2026-04-26-506-infra-f007-clear")

            # Run 1: 75% → defer
            _write_quota_state(75.0)
            r1 = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert r1.final_status == "paused_on_gate"
            assert "defer:quota_threshold" in gate_pause.active_defers(plan_dir)

            # Drop quota below threshold
            _write_quota_state(50.0)
            r2 = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            # Reconcile auto-removed defer:quota_threshold; dispatch proceeds.
            assert r2.final_status != "paused_on_gate", r2
            assert "defer:quota_threshold" not in gate_pause.active_defers(plan_dir)
            # INBOX has a defer_cleared event for the auto-clear.
            events = inbox.read_events(plan_dir)
            assert any(e.event == "defer_cleared" for e in events)
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        supervisor._quota_gate = saved_quota
        supervisor._run_round = saved_run
        os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ defer auto-clears on next dispatch when condition no longer true")


# ──────────────────────────────  lifecycle / approve  ──────────────────────────────


def test_approve_breaker_idempotent_extends_to_defer() -> None:
    """approve_gate's idempotency contract holds for defer:* gates too."""
    print("\n[test] approve_breaker_idempotent_extends_to_defer ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-510-infra-f007-idem")
        plan_id = "2026-04-26-510-infra-f007-idem"
        gate_pause.add_defer(plan_dir, "defer:quota_threshold", plan_id=plan_id)
        first = gate_pause.approve_gate(plan_dir, "defer:quota_threshold", plan_id=plan_id)
        assert first is True
        second = gate_pause.approve_gate(plan_dir, "defer:quota_threshold", plan_id=plan_id)
        assert second is False, "second approve of cleared defer must be a no-op"
        # Approving an unknown defer name with no prior trip is also a no-op.
        third = gate_pause.approve_gate(plan_dir, "defer:never_active", plan_id=plan_id)
        assert third is False
        # State integrity: only one approve in history for the cleared gate.
        state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
        approves = [
            h for h in state.get("history", [])
            if h.get("action") == "approve" and h.get("gate") == "defer:quota_threshold"
        ]
        assert len(approves) == 1
    print("  ✓ defer:* gates honor the approve_gate idempotency contract")


def test_resume_all_clears_active_defers() -> None:
    """`jarvis resume <plan>` pops every active defer in addition to breakers
    and plan-declared gates."""
    print("\n[test] resume_all_clears_active_defers ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-511-infra-f007-resume")
        plan_id = "2026-04-26-511-infra-f007-resume"
        gate_pause.add_defer(plan_dir, "defer:quota_threshold", plan_id=plan_id)
        gate_pause.add_defer(plan_dir, "defer:interactive_backoff", plan_id=plan_id)
        cleared = gate_pause.resume_all(plan_dir, plan_id=plan_id, declared_gates=[])
        assert "defer:quota_threshold" in cleared
        assert "defer:interactive_backoff" in cleared
        assert gate_pause.active_defers(plan_dir) == []
    print("  ✓ resume_all pops every active defer alongside breakers")


def test_cli_claude_touch_writes_state_and_admission_sees_it() -> None:
    """The `jarvis-orchestrate claude-touch` CLI writes
    ~/.jarvis/interactive_state.json and the admission evaluator picks it
    up immediately."""
    print("\n[test] cli_claude_touch_writes_state_and_admission_sees_it ...")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["claude-touch"])
    assert rc == 0
    assert "recorded human Claude request at " in buf.getvalue()
    last = interactive_state.last_human_request_at("claude")
    assert last is not None
    r = quota_admission.evaluate_interactive_backoff(["claude"])
    assert r.within_backoff
    print("  ✓ claude-touch CLI populates interactive_state and admission picks it up")


def test_cli_approve_recognizes_defer_names_no_warning() -> None:
    """jarvis approve <plan> defer:<kind> must not warn that the name isn't
    in plan.human_gates."""
    print("\n[test] cli_approve_recognizes_defer_names_no_warning ...")
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td), "2026-04-26-512-infra-f007-cli-app")
        gate_pause.add_defer(
            plan_dir, "defer:quota_threshold",
            plan_id="2026-04-26-512-infra-f007-cli-app",
        )
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = cli.main(["approve", str(plan_dir), "defer:quota_threshold"])
        assert rc == 0
        assert "WARNING" not in buf_err.getvalue(), buf_err.getvalue()
        assert "defer:quota_threshold" not in gate_pause.active_defers(plan_dir)
    print("  ✓ CLI approve recognizes defer:* names + no false-warning")


# ──────────────────────────────  D075-amend fixes  ──────────────────────────────


def test_pause_marker_clears_when_only_defer_was_pending() -> None:
    """D075-amend Fix#1: approving a defer:* whose name is the only pending
    pause_gate must drop the stale paused_at + pause_gates fields. Same for
    breakers — _maybe_clear_pause_marker now considers transient state, not
    just cleared_gates."""
    print("\n[test] pause_marker_clears_when_only_defer_was_pending ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td), "2026-04-26-520-infra-f007-pause-mark")
        plan_id = "2026-04-26-520-infra-f007-pause-mark"
        gate_pause.add_defer(plan_dir, "defer:quota_threshold", plan_id=plan_id)
        # Simulate the supervisor recording a pause on this defer.
        gate_pause.record_pause(
            plan_dir, plan_id=plan_id, pause_gates=["defer:quota_threshold"]
        )
        state_path = gate_pause.gate_state_path(plan_dir)
        before = json.loads(state_path.read_text())
        assert "paused_at" in before and before.get("pause_gates") == ["defer:quota_threshold"]
        # Approve clears the defer; the marker should drop because every
        # pending gate is now resolved (defer:* not in active_defers).
        gate_pause.approve_gate(plan_dir, "defer:quota_threshold", plan_id=plan_id)
        after = json.loads(state_path.read_text())
        assert "paused_at" not in after, after
        assert "pause_gates" not in after, after
    print("  ✓ approve clears stale pause marker for transient gates")


def test_pause_marker_clears_via_reconcile_auto_remove() -> None:
    """D075-amend Fix#1b: reconcile_defers auto-clearing the last pending
    defer must also drop the stale pause marker (without operator action)."""
    print("\n[test] pause_marker_clears_via_reconcile_auto_remove ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td), "2026-04-26-521-infra-f007-rec-mark")
        plan_id = "2026-04-26-521-infra-f007-rec-mark"
        gate_pause.add_defer(plan_dir, "defer:quota_threshold", plan_id=plan_id)
        gate_pause.record_pause(
            plan_dir, plan_id=plan_id, pause_gates=["defer:quota_threshold"]
        )
        state_path = gate_pause.gate_state_path(plan_dir)
        assert "paused_at" in json.loads(state_path.read_text())
        # Simulate next dispatch: condition cleared, reconcile drops the defer.
        gate_pause.reconcile_defers(plan_dir, set(), plan_id=plan_id)
        after = json.loads(state_path.read_text())
        assert gate_pause.active_defers(plan_dir) == []
        assert "paused_at" not in after
        assert "pause_gates" not in after
    print("  ✓ auto-reconcile clears stale pause marker on its own")


def test_dispatch_single_agent_pauses_on_quota_threshold() -> None:
    """D075-amend Fix#2: F007 admission applies to dispatch_single_agent too —
    not volley-only. Mock claude=75% → PausedOnGate; --mode interactive bypass."""
    print("\n[test] dispatch_single_agent_pauses_on_quota_threshold ...")
    _write_quota_state(75.0)
    saved_quota = _bypass_quota_gate()
    saved_registry = dict(AGENT_REGISTRY)
    impl = _ScriptedExecutor("claude", role="implementer", summaries=["x"])
    AGENT_REGISTRY["claude"] = lambda: impl
    os.environ[notify.DISABLE_ENV] = "1"
    try:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _setup_volley(Path(td), "2026-04-26-522-infra-f007-single")
            try:
                supervisor.dispatch_single_agent(plan_dir, "F001")
                raise AssertionError("expected PausedOnGate, got success")
            except supervisor.PausedOnGate as exc:
                assert "defer:quota_threshold" in str(exc), exc
            assert "defer:quota_threshold" in gate_pause.active_defers(plan_dir)
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        supervisor._quota_gate = saved_quota
        os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ dispatch_single_agent honors F007 admission")


def test_cli_approve_remaining_unmet_includes_active_defers() -> None:
    """D075-amend Fix#3: jarvis approve's '[approve] remaining unmet gates'
    line must reflect every active transient gate too — not just unmet
    plan-declared gates. Otherwise operator can be told '(none)' remain
    while another defer:*/breaker:* is still active."""
    print("\n[test] cli_approve_remaining_unmet_includes_active_defers ...")
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td), "2026-04-26-523-infra-f007-rem")
        plan_id = "2026-04-26-523-infra-f007-rem"
        gate_pause.add_defer(plan_dir, "defer:quota_threshold", plan_id=plan_id)
        gate_pause.add_defer(plan_dir, "defer:interactive_backoff", plan_id=plan_id)
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = cli.main(["approve", str(plan_dir), "defer:quota_threshold"])
        assert rc == 0
        out = buf_out.getvalue()
        # Approving quota_threshold; backoff defer is still active and must
        # appear in the remaining-unmet line (not "(none)").
        assert "defer:interactive_backoff" in out, out
        assert "(none)" not in out, out
    print("  ✓ remaining-unmet output reflects active defers + breakers")


def test_e2e_interactive_backoff_expires_auto_clear() -> None:
    """D075-amend Fix#4: AC #6 second leg — touch claude beyond the backoff
    window → autonomous plan dispatches without operator action; defer:
    interactive_backoff auto-clears via reconcile."""
    print("\n[test] e2e_interactive_backoff_expires_auto_clear ...")
    _write_quota_state(50.0)
    saved_registry = dict(AGENT_REGISTRY)
    saved_quota = _bypass_quota_gate()
    saved_run = _force_auditor_signed_off()
    os.environ[notify.DISABLE_ENV] = "1"
    try:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _setup_volley(Path(td), "2026-04-26-524-infra-f007-bo-ac")

            # Run 1: touch 15 min ago → defer
            fifteen_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=15)
            interactive_state.touch("claude", at=fifteen_ago)
            r1 = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert r1.final_status == "paused_on_gate"
            assert "defer:interactive_backoff" in gate_pause.active_defers(plan_dir)

            # Run 2: touch is now 35 min old (past 30 min default window)
            past_window = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=35)
            interactive_state.touch("claude", at=past_window)
            r2 = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            # Reconcile auto-removed defer:interactive_backoff; dispatch proceeds.
            assert r2.final_status != "paused_on_gate", r2
            assert "defer:interactive_backoff" not in gate_pause.active_defers(plan_dir)
            events = inbox.read_events(plan_dir)
            cleared = [
                e for e in events
                if e.event == "defer_cleared"
                and e.headers.get("defer_gate") == "defer:interactive_backoff"
            ]
            assert cleared, "expected a defer_cleared event for interactive_backoff"
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved_registry)
        supervisor._quota_gate = saved_quota
        supervisor._run_round = saved_run
        os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ interactive backoff auto-clears once the touch ages past the window")
