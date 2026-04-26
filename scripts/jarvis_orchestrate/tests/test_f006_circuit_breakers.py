"""F006 — 7 loop termination triggers.

Run: PYTHONPATH=scripts python3 -m jarvis_orchestrate.tests.test_f006_circuit_breakers
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
    circuit_breakers as cb,
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


# ──────────────────────────────  pure-function checks  ──────────────────────────────


def test_check_wall_clock() -> None:
    print("\n[test] check_wall_clock ...")
    long_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    tripped, reason = cb.check_wall_clock(long_ago, max_hours=1.0)
    assert tripped and "exceeds wall_clock_hours" in reason
    just_now = dt.datetime.now(dt.timezone.utc)
    assert not cb.check_wall_clock(just_now, max_hours=1.0)[0]
    print("  ✓ wall_clock fires when elapsed > max, passes when fresh")


def test_check_budget_ceiling_reads_quota_state_file() -> None:
    """F006 fix#1: budget_ceiling now reads the F020-populated
    ~/.jarvis/quota_state.json, not a phantom field on audit JSONs."""
    print("\n[test] check_budget_ceiling_reads_quota_state_file ...")
    with tempfile.TemporaryDirectory() as td:
        ad = Path(td) / "audits"
        ad.mkdir()
        # Real-shape audit (no percent_weekly — the bug the fix closes).
        (ad / "claude-implementer-i0.json").write_text(json.dumps({
            "task_id": "t", "audit_id": "t#claude#0",
            "agent": "claude", "agent_role": "implementer", "iteration": 0,
            "started_at": _iso_now(), "completed_at": _iso_now(),
            "audit_status": "needs_changes",
            "quota_consumed": {"tokens_in": 100, "tokens_out": 50, "api_calls": 1},
        }))
        # quota_state.json supplied via the new explicit kwarg
        qs = Path(td) / "quota_state.json"
        qs.write_text(json.dumps({
            "models": {"claude": {"percent_weekly": 80.0, "plan": "x"}}
        }))
        # No caps → no trip
        assert not cb.check_budget_ceiling(sorted(ad.glob("*.json")), None,
                                            quota_state_path=qs)[0]
        # Cap=50 → trip (state says 80%)
        tripped, reason = cb.check_budget_ceiling(
            sorted(ad.glob("*.json")), {"claude": 50.0},
            quota_state_path=qs,
        )
        assert tripped, reason
        assert "claude" in reason and "80" in reason and "quota_state.json" in reason
        # Cap=90 → no trip
        assert not cb.check_budget_ceiling(
            sorted(ad.glob("*.json")), {"claude": 90.0},
            quota_state_path=qs,
        )[0]
        # Agent absent from this volley's audits → no trip even at over-cap state
        empty = Path(td) / "empty"
        empty.mkdir()
        assert not cb.check_budget_ceiling(
            sorted(empty.glob("*.json")), {"claude": 50.0},
            quota_state_path=qs,
        )[0]
    print("  ✓ budget_ceiling reads quota_state.json + scoped to participating agents")


def test_check_no_progress() -> None:
    print("\n[test] check_no_progress ...")
    assert cb.check_no_progress("needs_changes", "needs_changes")[0]
    assert not cb.check_no_progress(None, "needs_changes")[0]
    assert not cb.check_no_progress("needs_changes", "blocked")[0]
    # signed_off / blocked don't count as "stuck"
    assert not cb.check_no_progress("signed_off", "signed_off")[0]
    assert not cb.check_no_progress("blocked", "blocked")[0]
    print("  ✓ no_progress fires on identical non-terminal verdicts only")


def _write_auditor_audit(ad: Path, iteration: int, *, status: str, findings: int) -> Path:
    p = ad / f"codex-auditor-i{iteration}.json"
    p.write_text(json.dumps({
        "task_id": "t", "audit_id": f"t#codex#{iteration}",
        "agent": "codex", "agent_role": "auditor", "iteration": iteration,
        "started_at": _iso_now(), "completed_at": _iso_now(),
        "audit_status": status,
        "findings": [
            {"severity": "low", "category": "style", "issue": f"finding {i}-aaaaaaa"}
            for i in range(findings)
        ],
    }))
    return p


def test_check_diminishing_returns() -> None:
    print("\n[test] check_diminishing_returns ...")
    with tempfile.TemporaryDirectory() as td:
        ad = Path(td)
        # First single audit — not enough rounds
        _write_auditor_audit(ad, 0, status="needs_changes", findings=3)
        assert not cb.check_diminishing_returns(sorted(ad.glob("*.json")))[0]
        # Second audit — same finding count, same status → diminishing
        _write_auditor_audit(ad, 1, status="needs_changes", findings=3)
        tripped, reason = cb.check_diminishing_returns(sorted(ad.glob("*.json")))
        assert tripped and "non-decreasing" in reason
        # Replace last with fewer findings → no trip
        _write_auditor_audit(ad, 1, status="needs_changes", findings=1)
        assert not cb.check_diminishing_returns(sorted(ad.glob("*.json")))[0]
    print("  ✓ diminishing_returns fires on non-decreasing findings across needs_changes rounds")


def test_check_convergence_collapse() -> None:
    print("\n[test] check_convergence_collapse ...")
    with tempfile.TemporaryDirectory() as td:
        ad = Path(td)
        _write_auditor_audit(ad, 0, status="needs_changes", findings=2)
        _write_auditor_audit(ad, 1, status="inconclusive", findings=2)
        _write_auditor_audit(ad, 2, status="needs_changes", findings=2)
        tripped, reason = cb.check_convergence_collapse(sorted(ad.glob("*.json")))
        assert tripped and "oscillate" in reason
        # Same status thrice → not collapse (no_progress fires instead)
        ad2 = Path(td) / "uniform"
        ad2.mkdir()
        for i in range(3):
            _write_auditor_audit(ad2, i, status="needs_changes", findings=2)
        assert not cb.check_convergence_collapse(sorted(ad2.glob("*.json")))[0]
    print("  ✓ convergence_collapse fires on verdict ping-pong, not on uniform stuck")


# ──────────────────────────────  global breaker  ──────────────────────────────


def test_global_breaker_threshold() -> None:
    """conftest's autouse fixture redirects JARVIS_BREAKER_HISTORY_PATH per-test;
    cb._effective_history_path() returns it. No manual monkeypatching needed."""
    print("\n[test] global_breaker_threshold ...")
    history = cb._effective_history_path()
    # Empty → not tripped
    assert not cb.evaluate_global().tripped
    # Two hits → not tripped
    cb.record_global_hit("p1", cb.BreakerKind.ITERATION_CAP)
    cb.record_global_hit("p2", cb.BreakerKind.ITERATION_CAP)
    assert not cb.evaluate_global().tripped
    # Third → tripped
    cb.record_global_hit("p3", cb.BreakerKind.ITERATION_CAP)
    state = cb.evaluate_global()
    assert state.tripped and state.hits_in_window == 3
    # Other breaker kinds don't count toward the threshold
    history.unlink()
    for _ in range(5):
        cb.record_global_hit("p", cb.BreakerKind.NO_PROGRESS)
    assert not cb.evaluate_global().tripped
    print("  ✓ global breaker fires at 3+ iteration_cap hits; other kinds ignored for threshold")


def test_global_breaker_window_pruning() -> None:
    print("\n[test] global_breaker_window_pruning ...")
    history = cb._effective_history_path()
    history.parent.mkdir(parents=True, exist_ok=True)
    stale = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with history.open("w") as f:
        for _ in range(5):
            f.write(json.dumps({
                "plan_id": "old", "kind": "iteration_cap", "at": stale,
            }) + "\n")
    # Even 5 stale hits don't trip the breaker
    assert not cb.evaluate_global().tripped
    # One fresh hit alone doesn't either
    cb.record_global_hit("new", cb.BreakerKind.ITERATION_CAP)
    assert not cb.evaluate_global().tripped
    print("  ✓ entries older than the 24h window don't count")


# ──────────────────────────────  gate-pause integration  ──────────────────────────────


def test_breaker_blocks_dispatch_via_gate_pause() -> None:
    print("\n[test] breaker_blocks_dispatch_via_gate_pause ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        gate_pause.add_breaker(pd, cb.gate_name(cb.BreakerKind.WALL_CLOCK),
                                plan_id="p", reason="elapsed > 1h")
        check = gate_pause.evaluate(pd, ["pre_impl"])
        assert check.paused
        assert "breaker:wall_clock" in check.unmet
        assert "pre_impl" in check.unmet
        # Approve the breaker — only plan-gate left
        gate_pause.approve_gate(pd, "breaker:wall_clock", plan_id="p")
        check2 = gate_pause.evaluate(pd, ["pre_impl"])
        assert check2.unmet == ["pre_impl"]
        # State file: active_breakers cleaned + breaker not in cleared_gates
        state = json.loads(gate_pause.gate_state_path(pd).read_text())
        assert "active_breakers" not in state or not state.get("active_breakers")
        assert all(not c.startswith("breaker:") for c in (state.get("cleared_gates") or []))
        # Re-tripping the same breaker must pause again
        gate_pause.add_breaker(pd, cb.gate_name(cb.BreakerKind.WALL_CLOCK),
                                plan_id="p", reason="re-hit")
        assert "breaker:wall_clock" in gate_pause.evaluate(pd, ["pre_impl"]).unmet
    print("  ✓ breakers union with plan.human_gates, approve clears, re-trip pauses again")


def test_resume_all_clears_breakers() -> None:
    print("\n[test] resume_all_clears_breakers ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        gate_pause.add_breaker(pd, cb.gate_name(cb.BreakerKind.NO_PROGRESS),
                                plan_id="p", reason="x")
        gate_pause.add_breaker(pd, cb.gate_name(cb.BreakerKind.WALL_CLOCK),
                                plan_id="p", reason="y")
        gate_pause.resume_all(pd, plan_id="p", declared_gates=["pre_impl"])
        check = gate_pause.evaluate(pd, ["pre_impl"])
        assert not check.paused, check
    print("  ✓ resume_all clears every active breaker plus declared gates")


# ──────────────────────────────  supervisor end-to-end  ──────────────────────────────


_PLAN_TEMPLATE = """---
id: {plan_id}
title: F006 synthetic
type: infra
tier: trivial
status: active
date: "2026-04-26"
description: Synthetic plan for F006 circuit-breaker tests.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
loop_caps:
  max_iterations: {cap}
  hard_stop: false
  wall_clock_hours: {wall_clock_hours}
privacy_tier: internal
links:
  features: ./features.json
---

# F006 synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""


def _make_plan(repo: Path, plan_id: str, *, cap: int = 1, wall_clock_hours: float = 1.0) -> Path:
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_PLAN_TEMPLATE.format(
        plan_id=plan_id, cap=cap, wall_clock_hours=wall_clock_hours,
    ))
    (plan_dir / "features.json").write_text(json.dumps({
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [{
            "id": "F001", "category": "test", "phase": 0,
            "description": "Synthetic feature for F006 tests.",
            "steps": ["scripted"],
            "acceptance": "Volley terminates per breaker.",
            "passes": False, "depends_on": [],
        }],
    }, indent=2) + "\n")
    return plan_dir


class _ScriptedExecutor(BaseExecutor):
    """Returns scripted summaries with an optional findings-count knob (auditor)."""

    def __init__(self, agent: str, *, role: str, summaries: list[str],
                 statuses: list[str] | None = None) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.role = role
        self.summaries = list(summaries)
        self.statuses = list(statuses) if statuses else []
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


def _bypass_quota():
    saved = supervisor._quota_gate
    supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")
    return saved


def _force_auditor_status(force: str):
    """Wrap supervisor._run_round so the auditor returns the forced status."""
    orig = supervisor._run_round

    def maybe_force(*args, **kwargs):
        path = orig(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            data = json.loads(path.read_text())
            data["audit_status"] = force
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return path

    supervisor._run_round = maybe_force
    return orig


def test_supervisor_iteration_cap_pauses_via_breaker() -> None:
    """Global history is isolated per-test by the conftest autouse fixture."""
    print("\n[test] supervisor_iteration_cap_pauses_via_breaker ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-400-infra-f006-cap", cap=0)
        gate_pause.resume_all(plan_dir, plan_id="2026-04-26-400-infra-f006-cap",
                                declared_gates=["pre_impl"])
        impl = _ScriptedExecutor("claude", role="implementer",
                                  summaries=["Synthetic implementer summary."])
        aud = _ScriptedExecutor("codex", role="auditor",
                                 summaries=["Synthetic auditor summary."])
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = _bypass_quota()
        saved_run = _force_auditor_status("needs_changes")
        AGENT_REGISTRY["claude"] = lambda: impl
        AGENT_REGISTRY["codex"] = lambda: aud
        os.environ[notify.DISABLE_ENV] = "1"
        try:
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=0)
            assert result.final_status == "stopped_cap", result
            # Synthetic gate present
            check = gate_pause.evaluate(plan_dir, ["pre_impl"])
            assert "breaker:iteration_cap" in check.unmet
            # INBOX entry recorded
            events = inbox.read_events(plan_dir)
            assert any(e.event == "breaker_tripped" for e in events)
            # Global history bumped
            assert cb.evaluate_global().hits_in_window == 1
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota
            supervisor._run_round = saved_run
            os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ iteration_cap → breaker_tripped INBOX + synthetic gate + global history hit")


def test_supervisor_global_breaker_hard_stops() -> None:
    print("\n[test] supervisor_global_breaker_hard_stops ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-401-infra-f006-global")
        gate_pause.resume_all(plan_dir, plan_id="2026-04-26-401-infra-f006-global",
                                declared_gates=["pre_impl"])
        # Pre-load 3 iteration_cap hits
        for i in range(3):
            cb.record_global_hit(f"p{i}", cb.BreakerKind.ITERATION_CAP)
        impl = _ScriptedExecutor("claude", role="implementer", summaries=["x"])
        aud = _ScriptedExecutor("codex", role="auditor", summaries=["x"])
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = _bypass_quota()
        AGENT_REGISTRY["claude"] = lambda: impl
        AGENT_REGISTRY["codex"] = lambda: aud
        os.environ[notify.DISABLE_ENV] = "1"
        try:
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert result.final_status == "stopped_global_breaker", result
            # Critical: no executor was called (hard stop before dispatch loop)
            assert impl.idx == 0 and aud.idx == 0
            events = inbox.read_events(plan_dir)
            tripped = [e for e in events if e.event == "breaker_tripped"]
            assert tripped and tripped[-1].headers.get("breaker_kind") == "global_circuit_breaker"
            assert tripped[-1].headers.get("approval_required") == "false"
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota
            os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ global breaker hard-stops dispatch — no executors called, no clearance offered")


# ──────────────────────────────  AC-honesty fixes (D074-amend)  ──────────────────────────────


def test_global_breaker_evaluates_before_executor_resolution() -> None:
    """Fix#2: global breaker must trip BEFORE _resolve_executor; an empty
    AGENT_REGISTRY with a tripped global breaker should produce
    stopped_global_breaker, not KeyError."""
    print("\n[test] global_breaker_evaluates_before_executor_resolution ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-410-infra-f006-order")
        gate_pause.resume_all(plan_dir, plan_id="2026-04-26-410-infra-f006-order",
                                declared_gates=["pre_impl"])
        for _ in range(3):
            cb.record_global_hit("p", cb.BreakerKind.ITERATION_CAP)
        # Critically: clear AGENT_REGISTRY so executor resolution would KeyError
        # if reached before the global breaker check.
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = _bypass_quota()
        AGENT_REGISTRY.clear()
        os.environ[notify.DISABLE_ENV] = "1"
        try:
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert result.final_status == "stopped_global_breaker", result
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota
            os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ tripped global breaker halts dispatch before executor resolution")


def test_cli_approve_breaker_no_false_warning() -> None:
    """Fix#3a: jarvis approve <plan-id> breaker:<kind> must not warn that the
    name isn't in plan.human_gates."""
    print("\n[test] cli_approve_breaker_no_false_warning ...")
    from jarvis_orchestrate import cli
    from contextlib import redirect_stderr
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-411-infra-f006-cli-approve")
        # Trip the breaker so it's in active_breakers (gives the CLI two
        # parallel paths to recognize the name as valid: known BreakerKind +
        # currently active).
        gate_pause.add_breaker(plan_dir, "breaker:wall_clock", plan_id="2026-04-26-411-infra-f006-cli-approve")
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = cli.main(["approve", str(plan_dir), "breaker:wall_clock"])
        assert rc == 0
        assert "WARNING" not in buf_err.getvalue(), buf_err.getvalue()
        # Sanity: a totally bogus name still warns.
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            cli.main(["approve", str(plan_dir), "breaker:totally_made_up_kind"])
        # That name IS in BreakerKind only if the kind name matches; "totally_made_up_kind"
        # doesn't, so it should warn. Active_breakers also doesn't have it.
        assert "WARNING" in buf_err.getvalue() or "totally_made_up_kind" in buf_err.getvalue()
    print("  ✓ CLI approve recognizes breaker:* as a valid declared name; bogus names still warn")


def test_cli_resume_clears_active_breakers_with_no_human_gates() -> None:
    """Fix#3b: jarvis resume must continue past the no-declared-gates short-circuit
    when active_breakers is non-empty."""
    print("\n[test] cli_resume_clears_active_breakers_with_no_human_gates ...")
    from jarvis_orchestrate import cli
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        # Plan with empty human_gates list
        plan_id = "2026-04-26-412-infra-f006-resume-no-gates"
        plan_dir = repo / "docs" / "plans" / plan_id
        plan_dir.mkdir(parents=True)
        plan_md = f"""---
id: {plan_id}
title: F006 fix synthetic
type: infra
tier: trivial
status: active
date: "2026-04-26"
description: Synthetic plan for fix#3b — no human_gates, only breakers.
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

# F006 fix synthetic

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
                "description": "Synthetic feature for F006 fix#3b.",
                "steps": ["scripted"],
                "acceptance": "resume clears active breakers.",
                "passes": False, "depends_on": [],
            }],
        }, indent=2) + "\n")
        # Trip a breaker but leave human_gates empty
        gate_pause.add_breaker(plan_dir, "breaker:wall_clock", plan_id=plan_id)
        assert "breaker:wall_clock" in gate_pause.active_breakers(plan_dir)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["resume", str(plan_dir)])
        assert rc == 0
        # After resume, active breakers must be cleared
        assert "breaker:wall_clock" not in gate_pause.active_breakers(plan_dir), \
            gate_pause.active_breakers(plan_dir)
    print("  ✓ resume clears active breakers even when plan declares no human_gates")


# ──────────────────────────────  driver  ──────────────────────────────


def main() -> int:
    test_check_wall_clock()
    test_check_budget_ceiling_reads_quota_state_file()
    test_check_no_progress()
    test_check_diminishing_returns()
    test_check_convergence_collapse()
    test_global_breaker_threshold()
    test_global_breaker_window_pruning()
    test_breaker_blocks_dispatch_via_gate_pause()
    test_resume_all_clears_breakers()
    test_supervisor_iteration_cap_pauses_via_breaker()
    test_supervisor_global_breaker_hard_stops()
    test_global_breaker_evaluates_before_executor_resolution()
    test_cli_approve_breaker_no_false_warning()
    test_cli_resume_clears_active_breakers_with_no_human_gates()
    print("\n✓ F006 circuit-breaker tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
