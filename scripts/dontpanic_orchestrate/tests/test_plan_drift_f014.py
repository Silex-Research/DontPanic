"""F014 — plan-drift reconciliation: single-agent guard + blocking-drift ack.

Plan 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 F014.

F009 wired the drift reconciliation into the VOLLEY path. F014 closes the two
gaps codex flagged on F009:

  * #4 — the single-agent dispatch path (``supervisor.dispatch_single_agent``)
    must be guarded by the SAME baseline + ``check_and_reconcile`` so no paid
    single-agent call proceeds on stale plan context.
  * #5 — BLOCKING_POLICY scope/policy drift must be a REAL human-acknowledgement
    workflow: the run pauses and a durable marker survives re-dispatch until an
    operator runs ``dontpanic approve <plan> drift:<class>`` — not merely a
    ``requires_human`` label that a plain re-dispatch silently launders.

Plus F009 AC6 — CLI + dashboard surface exactly ONE reconciliation action.

These tests drive the supervisor with counting executors so "the paid call did
not happen" is an assertion on the executor, not a proxy.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import importlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    cli,
    operator_console,
    plan_drift,
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


class _CountingExecutor(BaseExecutor):
    """Scripted executor that records each dispatch (so an un-made paid call is
    an assertion on ``.calls``), optionally running a side-effect on dispatch."""

    def __init__(self, agent: str, on_dispatch=None) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.calls: list[str] = []
        self._on_dispatch = on_dispatch

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.calls.append(task.agent_role)
        if self._on_dispatch is not None:
            self._on_dispatch(task)
        summary = (
            "## Target context\nRepo: Jarvis\nEnv: dev\nProject: (none)\n"
            "Command: 1 (see structured target_context.commands_run)\n\n"
            f"[F001] scripted {self.agent_name}/{task.agent_role}.\n\n$ pytest -q"
        )
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=summary,
            model_version=None,
            raw_response=summary,
            quota_consumed={"tokens_in": 100, "tokens_out": 50},
        )


def _make_plan(tmp_dir: Path, *, with_scope: bool = False) -> Path:
    plan_id = "2026-05-30-014-infra-drift-single-agent-demo"
    plan_dir = tmp_dir / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    # A top-level scope field (``protected_paths``) is BLOCKING_POLICY drift when
    # changed — and, unlike child_charter.allowed_paths, needs no parent plan on
    # disk, so a post-ack resume can run to completion without nested-orch guards.
    scope_block = "protected_paths:\n  - docs/**\n" if with_scope else ""
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: Single-agent drift demonstration
type: infra
tier: trivial
status: active
date: "2026-05-30"
description: Synthetic plan proving the single-agent path is drift-guarded (F014).
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
{scope_block}links:
  features: ./features.json
---

# Single-agent drift demonstration

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
                        "description": "Synthetic feature for the single-agent drift demo.",
                        "steps": ["scripted implementer"],
                        "acceptance": "Single-agent dispatch pauses on stale plan context.",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    (plan_dir / "decisions.jsonl").write_text(
        json.dumps({"id": "D001", "title": "seed", "body": "x"}) + "\n"
    )
    return plan_dir


def _register(impl: _CountingExecutor, aud: _CountingExecutor) -> None:
    AGENT_REGISTRY["claude"] = lambda i=impl: i  # type: ignore[assignment]
    AGENT_REGISTRY["codex"] = lambda a=aud: a  # type: ignore[assignment]


def _disable_quota_gate() -> None:
    supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")


def _bump_acceptance(plan_dir: Path) -> None:
    feats = json.loads((plan_dir / "features.json").read_text())
    feats["features"][0]["acceptance"] = "REWRITTEN by another interactive agent"
    (plan_dir / "features.json").write_text(json.dumps(feats, indent=2))


@pytest.fixture(autouse=True)
def _restore_supervisor_after():
    yield
    importlib.reload(supervisor)


# ─────────────────────────── pure ack-marker layer ─────────────────────────


def _blocking_report() -> plan_drift.DriftReport:
    return plan_drift.DriftReport(
        drift_class=plan_drift.DriftClass.BLOCKING_POLICY,
        changed_files=("plan.md",),
        changes=(
            plan_drift.ChangeNote(
                dimension="allowed_paths",
                drift_class=plan_drift.DriftClass.BLOCKING_POLICY,
                summary="allowed_paths narrowed mid-run",
            ),
        ),
        stage=plan_drift.STAGE_DISPATCH,
    )


def test_record_and_read_ack_marker_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        plan_dir = Path(td)
        assert plan_drift.is_blocking_ack_pending(plan_dir) is False
        plan_drift.record_blocking_ack_required(
            plan_dir, plan_id="P", feature_id="F001", report=_blocking_report()
        )
        assert plan_drift.is_blocking_ack_pending(plan_dir) is True
        marker = plan_drift.read_ack_marker(plan_dir)
        assert marker["drift_class"] == "blocking_policy"
        assert marker["acknowledged"] is False
        assert marker["ack_command"] == "dontpanic approve P drift:blocking_policy"


def test_record_ack_marker_is_idempotent_for_same_class():
    """AC6: re-detecting the same blocking band does not stack a second marker —
    the operator sees ONE pending reconciliation action."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = Path(td)
        p1 = plan_drift.record_blocking_ack_required(
            plan_dir, plan_id="P", feature_id="F001", report=_blocking_report()
        )
        first = plan_drift.read_ack_marker(plan_dir)
        p2 = plan_drift.record_blocking_ack_required(
            plan_dir, plan_id="P", feature_id="F001", report=_blocking_report()
        )
        second = plan_drift.read_ack_marker(plan_dir)
        assert p1 == p2
        # recorded_at unchanged → the marker was not rewritten on re-detect.
        assert first["recorded_at"] == second["recorded_at"]


def test_acknowledge_clears_marker():
    with tempfile.TemporaryDirectory() as td:
        plan_dir = Path(td)
        plan_drift.record_blocking_ack_required(
            plan_dir, plan_id="P", feature_id="F001", report=_blocking_report()
        )
        cleared = plan_drift.acknowledge_blocking_drift(
            plan_dir, plan_id="P", drift_class="blocking_policy"
        )
        assert cleared["acknowledged"] is True
        assert plan_drift.is_blocking_ack_pending(plan_dir) is False
        assert plan_drift.read_ack_marker(plan_dir) is None


def test_acknowledge_accepts_prefixed_class_token():
    with tempfile.TemporaryDirectory() as td:
        plan_dir = Path(td)
        plan_drift.record_blocking_ack_required(
            plan_dir, plan_id="P", feature_id="F001", report=_blocking_report()
        )
        plan_drift.acknowledge_blocking_drift(
            plan_dir, plan_id="P", drift_class="drift:blocking_policy"
        )
        assert plan_drift.is_blocking_ack_pending(plan_dir) is False


def test_acknowledge_no_marker_raises():
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(plan_drift.DriftAckError):
            plan_drift.acknowledge_blocking_drift(Path(td), plan_id="P")


def test_acknowledge_class_mismatch_raises():
    with tempfile.TemporaryDirectory() as td:
        plan_dir = Path(td)
        plan_drift.record_blocking_ack_required(
            plan_dir, plan_id="P", feature_id="F001", report=_blocking_report()
        )
        with pytest.raises(plan_drift.DriftAckError):
            plan_drift.acknowledge_blocking_drift(
                plan_dir, plan_id="P", drift_class="context_refresh"
            )
        # The marker is untouched — a mismatched ack must not silently clear it.
        assert plan_drift.is_blocking_ack_pending(plan_dir) is True


def test_blocking_ack_pause_reason_present_then_none():
    with tempfile.TemporaryDirectory() as td:
        plan_dir = Path(td)
        assert plan_drift.blocking_ack_pause_reason(plan_dir) is None
        plan_drift.record_blocking_ack_required(
            plan_dir, plan_id="P", feature_id="F001", report=_blocking_report()
        )
        reason = plan_drift.blocking_ack_pause_reason(plan_dir)
        assert reason is not None
        assert "drift:blocking_policy" in reason
        plan_drift.acknowledge_blocking_drift(plan_dir, plan_id="P")
        assert plan_drift.blocking_ack_pause_reason(plan_dir) is None


# ───────── check_and_reconcile records marker only for blocking drift ────────


def _fingerprint_pair_with_allowed_paths(plan_dir: Path, before_val, after_val):
    base = plan_drift.compute_fingerprint(plan_dir)
    before = dataclasses.replace(
        base, plan_semantics={**base.plan_semantics, "allowed_paths": before_val}
    )
    after = dataclasses.replace(
        base, plan_semantics={**base.plan_semantics, "allowed_paths": after_val}
    )
    return before, after


def test_check_and_reconcile_records_marker_on_blocking():
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        before, after = _fingerprint_pair_with_allowed_paths(
            plan_dir, ["scripts/**"], ["scripts/safe/**"]
        )
        decision = plan_drift.check_and_reconcile(
            plan_dir,
            plan_id="P",
            feature_id="F001",
            stage=plan_drift.STAGE_DISPATCH,
            baseline=before,
            current=after,
            emit=True,
        )
        assert decision.proceed is False
        assert decision.report.drift_class is plan_drift.DriftClass.BLOCKING_POLICY
        assert plan_drift.is_blocking_ack_pending(plan_dir) is True


def test_check_and_reconcile_no_marker_on_refresh():
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        base = plan_drift.compute_fingerprint(plan_dir)
        before = dataclasses.replace(
            base, plan_semantics={**base.plan_semantics, "loop_caps": {"max_iterations": 1}}
        )
        after = dataclasses.replace(
            base, plan_semantics={**base.plan_semantics, "loop_caps": {"max_iterations": 9}}
        )
        decision = plan_drift.check_and_reconcile(
            plan_dir,
            plan_id="P",
            feature_id="F001",
            stage=plan_drift.STAGE_DISPATCH,
            baseline=before,
            current=after,
            emit=True,
        )
        assert decision.proceed is False
        assert decision.report.drift_class is plan_drift.DriftClass.CONTEXT_REFRESH
        # Refresh drift does not require human ack — a redispatch is the fix.
        assert plan_drift.is_blocking_ack_pending(plan_dir) is False


def test_check_and_reconcile_pause_reason_carries_one_reconcile_command():
    """AC3 / codex i1 #1: the FIRST blocking-policy detection must fold the ONE
    reconciliation command into ``pause_reason`` at its single source, so every
    downstream consumer that surfaces only ``pause_reason`` (CLI ``PausedOnDrift``
    text, volley ``VolleyResult.reason``, the mid-run pause, the INBOX body) shows
    a runnable action rather than a bare headline. Exactly one command; never a
    bare ``resume`` (which would leave the ack marker pending)."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        before, after = _fingerprint_pair_with_allowed_paths(
            plan_dir, ["scripts/**"], ["scripts/safe/**"]
        )
        # emit=False keeps this a pure unit check — build_guidance still runs, so
        # pause_reason is populated regardless of marker/sidecar side effects.
        decision = plan_drift.check_and_reconcile(
            plan_dir,
            plan_id="P",
            feature_id="F001",
            stage=plan_drift.STAGE_DISPATCH,
            baseline=before,
            current=after,
            emit=False,
        )
        assert decision.proceed is False
        assert decision.report.drift_class is plan_drift.DriftClass.BLOCKING_POLICY
        cmd = "dontpanic approve P drift:blocking_policy"
        assert decision.pause_reason is not None
        assert decision.pause_reason.count(cmd) == 1, decision.pause_reason
        assert "resume" not in decision.pause_reason


# ──────────────────────── single-agent path (codex #4/#5) ───────────────────


def test_single_agent_pauses_on_pending_blocking_ack():
    """AC4/codex #5: a pending blocking-drift ack marker pauses the single-agent
    path before any paid call — PausedOnDrift, executor never dispatched."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()

        plan_drift.record_blocking_ack_required(
            plan_dir, plan_id="P", feature_id="F001", report=_blocking_report()
        )

        with pytest.raises(supervisor.PausedOnDrift):
            supervisor.dispatch_single_agent(plan_dir, "F001", agent_role="implementer")
        assert impl.calls == [], "no paid single-agent call may proceed with a pending ack"


def test_single_agent_pauses_on_concurrent_edit(monkeypatch):
    """AC1/codex #4: a concurrent features.json edit between the dispatch-start
    baseline and the pre-paid drift check pauses the single-agent path — the
    paid implementer dispatch never happens."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()

        # Inject the edit just after the dispatch-start baseline is written,
        # before the pre-paid check_and_reconcile runs — the "another process
        # edited the plan mid-run" race.
        orig_record = plan_drift.record_baseline
        state = {"injected": False}

        def _record_then_edit(pd, fingerprint=None):
            result = orig_record(pd, fingerprint)
            if not state["injected"]:
                state["injected"] = True
                _bump_acceptance(Path(pd))
            return result

        monkeypatch.setattr(plan_drift, "record_baseline", _record_then_edit)

        with pytest.raises(supervisor.PausedOnDrift):
            supervisor.dispatch_single_agent(plan_dir, "F001", agent_role="implementer")
        assert impl.calls == [], "single-agent must NOT dispatch on stale context"


def test_single_agent_pause_message_carries_one_reconcile_command(monkeypatch):
    """AC3 / codex i1 #2: drive the ACTUAL single-agent pause surface (not just
    the guidance object) and assert the operator-facing ``PausedOnDrift`` message
    — the exact text the CLI prints — carries exactly ONE
    ``dontpanic approve <plan> drift:blocking_policy`` action. Proves the
    pause_reason fix flows end-to-end to the surface the operator reads."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td), with_scope=True)
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()

        # Narrow protected_paths just after the dispatch-start baseline is
        # captured → a fresh BLOCKING_POLICY drift on the pre-paid check (no
        # pre-existing ack marker), so the surfaced reason comes from
        # check_and_reconcile's pause_reason, not blocking_ack_pause_reason.
        orig_record = plan_drift.record_baseline
        state = {"injected": False}

        def _record_then_narrow(pd, fingerprint=None):
            result = orig_record(pd, fingerprint)
            if not state["injected"]:
                state["injected"] = True
                _narrow_protected_paths(Path(pd))
            return result

        monkeypatch.setattr(plan_drift, "record_baseline", _record_then_narrow)

        with pytest.raises(supervisor.PausedOnDrift) as exc:
            supervisor.dispatch_single_agent(plan_dir, "F001", agent_role="implementer")
        msg = str(exc.value)
        plan_id = "2026-05-30-014-infra-drift-single-agent-demo"
        cmd = f"dontpanic approve {plan_id} drift:blocking_policy"
        assert msg.count(cmd) == 1, msg
        assert "resume" not in msg
        assert impl.calls == [], "single-agent must NOT dispatch on stale context"


def test_single_agent_proceeds_when_no_drift():
    """Parity guard: with no drift and no pending ack, the single-agent path
    runs the paid call exactly once and writes an audit envelope."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()

        out_path = supervisor.dispatch_single_agent(
            plan_dir, "F001", agent_role="implementer"
        )
        assert impl.calls == ["implementer"]
        assert out_path.exists()


# ─────────────── blocking-drift ack: blocks-then-resumes (volley) ────────────


def _narrow_protected_paths(plan_dir: Path) -> None:
    text = (plan_dir / "plan.md").read_text()
    text = text.replace("  - docs/**", "  - docs/plans/**")
    (plan_dir / "plan.md").write_text(text)


def test_blocking_drift_blocks_then_resumes_after_ack(monkeypatch):
    """AC2/AC4/codex #5 — the full human-ack workflow on the volley path:

      1. allowed_paths narrows mid-run → blocking drift → volley pauses AND a
         durable ack marker is written.
      2. a plain re-dispatch STILL pauses (the marker is unacknowledged) — a
         redispatch cannot silently launder the new scope.
      3. `acknowledge_blocking_drift` clears the marker.
      4. the next dispatch records a fresh baseline against the accepted scope
         and proceeds — the paid implementer call finally runs.
    """
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td), with_scope=True)
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()

        # (1) one-shot edit after the clean dispatch-start baseline.
        orig_record = plan_drift.record_baseline
        state = {"injected": False}

        def _record_then_edit(pd, fingerprint=None):
            result = orig_record(pd, fingerprint)
            if not state["injected"]:
                state["injected"] = True
                _narrow_protected_paths(Path(pd))
            return result

        monkeypatch.setattr(plan_drift, "record_baseline", _record_then_edit)

        r1 = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
        assert r1.final_status == "paused_on_drift"
        assert impl.calls == []
        assert plan_drift.is_blocking_ack_pending(plan_dir) is True

        # (2) plain re-dispatch — still blocked by the unacknowledged marker.
        monkeypatch.setattr(plan_drift, "record_baseline", orig_record)
        r2 = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
        assert r2.final_status == "paused_on_drift"
        assert impl.calls == [], "an un-acknowledged scope change must keep pausing"

        # (3) operator acknowledges the new boundary.
        plan_drift.acknowledge_blocking_drift(
            plan_dir, plan_id=plan_dir.name, drift_class="blocking_policy"
        )
        assert plan_drift.is_blocking_ack_pending(plan_dir) is False

        # (4) redispatch now proceeds against the accepted scope.
        r3 = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
        assert r3.final_status != "paused_on_drift", r3.final_status
        assert impl.calls == ["implementer"], "post-ack redispatch must run the paid call"


# ──────────────────────── CLI: approve <plan> drift:<class> ─────────────────


def test_cli_approve_drift_clears_marker(capsys):
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        plan_id = plan_dir.name
        report = dataclasses.replace(_blocking_report())
        plan_drift.record_blocking_ack_required(
            plan_dir, plan_id=plan_id, feature_id="F001", report=report
        )

        rc = cli._approve_main([str(plan_dir), "drift:blocking_policy"])
        assert rc == 0
        assert plan_drift.is_blocking_ack_pending(plan_dir) is False
        # The acknowledgement is recorded on the INBOX for the audit trail.
        inbox_text = (plan_dir / "INBOX.md").read_text()
        assert "plan_drift_acknowledged" in inbox_text


def test_cli_approve_bare_drift_token_clears_marker():
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        plan_drift.record_blocking_ack_required(
            plan_dir, plan_id=plan_dir.name, feature_id="F001", report=_blocking_report()
        )
        rc = cli._approve_main([str(plan_dir), "drift"])
        assert rc == 0
        assert plan_drift.is_blocking_ack_pending(plan_dir) is False


def test_cli_approve_drift_no_marker_refused(capsys):
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        rc = cli._approve_main([str(plan_dir), "drift:blocking_policy"])
        assert rc == 2
        assert "REFUSED" in capsys.readouterr().err


def test_cli_approve_drift_class_mismatch_refused(capsys):
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        plan_drift.record_blocking_ack_required(
            plan_dir, plan_id=plan_dir.name, feature_id="F001", report=_blocking_report()
        )
        rc = cli._approve_main([str(plan_dir), "drift:context_refresh"])
        assert rc == 2
        assert plan_drift.is_blocking_ack_pending(plan_dir) is True


# ───────────────────── AC6: exactly ONE reconciliation action ────────────────


def test_repeated_blocking_emits_yield_one_dashboard_action(monkeypatch):
    """F009 AC6: even when the blocking-drift check fires repeatedly (dispatch
    stage, then implementer stage, then a re-dispatch), the dashboard surfaces
    exactly ONE concise reconciliation action — the event sidecar dedupes on the
    stable ActionChoice id rather than stacking a warning per fire."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        sidecar = plan_dir / "event-actions.jsonl"
        monkeypatch.setattr(
            operator_console, "default_event_sidecar_path", lambda: sidecar
        )

        before, after = _fingerprint_pair_with_allowed_paths(
            plan_dir, ["scripts/**"], ["scripts/safe/**"]
        )
        for stage in (
            plan_drift.STAGE_DISPATCH,
            plan_drift.STAGE_IMPLEMENTER,
            plan_drift.STAGE_AUDITOR,
        ):
            plan_drift.check_and_reconcile(
                plan_dir,
                plan_id=plan_dir.name,
                feature_id="F001",
                stage=stage,
                baseline=before,
                current=after,
                emit=True,
            )

        merged = operator_console.merge_with_event_sidecar([], sidecar_path=sidecar)
        # The sidecar reader namespaces the id (operations:<plan>:<feature>:...);
        # the stable suffix is the ActionChoice id, deduped across the 3 fires.
        drift_actions = [it for it in merged if it.id.endswith("plan-drift-policy-ack")]
        assert len(drift_actions) == 1, (
            f"expected exactly one reconciliation action, got {len(drift_actions)}: "
            f"{[it.id for it in merged]}"
        )
        # The single action must point at the human-ack workflow command that
        # actually clears the marker — NOT a bare `resume --all`, which would
        # leave the marker pending and re-pause on the next dispatch.
        assert drift_actions[0].exact_command == (
            f"dontpanic approve {plan_dir.name} drift:blocking_policy"
        ), drift_actions[0].exact_command


def test_blocking_guidance_emits_approve_drift_command():
    """The ONE blocking-drift reconciliation action must be the human-ack
    command that clears the marker (`dontpanic approve <plan> drift:<class>`),
    matching record_blocking_ack_required's stored ack_command — NOT a bare
    `dontpanic resume <plan> --all`, which leaves the marker pending and
    re-pauses on the next dispatch (codex F014 #1)."""
    report = _blocking_report()
    guidance = plan_drift.build_guidance("P", "F001", report)
    assert len(guidance.choices) == 1
    choice = guidance.choices[0]
    assert choice.id == "plan-drift-policy-ack"
    assert choice.requires_human is True
    assert choice.exact_command == "dontpanic approve P drift:blocking_policy"
    assert "resume" not in choice.exact_command
