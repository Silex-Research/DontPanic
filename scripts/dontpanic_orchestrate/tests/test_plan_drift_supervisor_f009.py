"""F009 — supervisor + CLI call-boundary drift tests.

Plan 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 F009 AC(2)/(4)/(7).

The pure reconciliation engine is exercised in ``test_plan_drift_f009``. This
module proves the WIRING: that ``dispatch_volley`` actually SKIPS a paid agent
call when another process edits a plan artifact mid-run, at each boundary —

  * before the implementer call,
  * before the auditor call (implementer already ran),
  * including a mid-run edit to ``audit/gate-state.json``,

and that the no-paid ``dontpanic finalize`` path REFUSES to mutate signoff /
features state when the plan drifted since dispatch (auditor finding #3).

It drives the supervisor with scripted executors that count their dispatches, so
"the paid call did not happen" is an assertion on the executor, not a proxy.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import plan_drift, supervisor  # noqa: E402
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _CountingExecutor(BaseExecutor):
    """Scripted executor that records each dispatch and optionally runs a
    side-effect callback when it dispatches (used to simulate another process
    editing the plan WHILE the implementer is working)."""

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
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=f"[scripted {self.agent_name}/{task.agent_role}] iter={task.iteration}",
            quota_consumed={"tokens_in": 100, "tokens_out": 50},
        )


def _make_plan(tmp_dir: Path) -> Path:
    plan_id = "2026-05-30-009-infra-drift-boundary-demo"
    plan_dir = tmp_dir / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        """---
id: 2026-05-30-009-infra-drift-boundary-demo
title: Drift boundary demonstration
type: infra
tier: trivial
status: active
date: "2026-05-30"
description: Synthetic plan proving mid-run drift skips paid calls (F009).
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

# Drift boundary demonstration

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
                        "description": "Synthetic feature for the drift-boundary demo.",
                        "steps": ["scripted implementer", "scripted auditor"],
                        "acceptance": "Volley pauses when the plan changes mid-run.",
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


def _bump_acceptance(plan_dir: Path) -> None:
    """Simulate another agent rewriting the feature acceptance mid-run."""
    feats = json.loads((plan_dir / "features.json").read_text())
    feats["features"][0]["acceptance"] = "REWRITTEN by another interactive agent"
    (plan_dir / "features.json").write_text(json.dumps(feats, indent=2))


def _register(impl: _CountingExecutor, aud: _CountingExecutor) -> None:
    AGENT_REGISTRY["claude"] = lambda i=impl: i  # type: ignore[assignment]
    AGENT_REGISTRY["codex"] = lambda a=aud: a  # type: ignore[assignment]


def _disable_quota_gate() -> None:
    supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")


@pytest.fixture(autouse=True)
def _restore_supervisor_after():
    yield
    importlib.reload(supervisor)


# ─────────────────────────── implementer boundary ──────────────────────────


def test_implementer_call_skipped_on_concurrent_edit(monkeypatch):
    """AC2/AC7: a concurrent features.json edit between dispatch-start and the
    implementer call pauses the volley — the paid implementer dispatch never
    happens."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()

        # Wrap record_baseline so the edit lands AFTER the clean dispatch-start
        # baseline but BEFORE the implementer drift check — exactly the "another
        # process edited the plan mid-run" race. One-shot so additive baseline
        # advances later pass through untouched.
        orig_record = plan_drift.record_baseline
        state = {"injected": False}

        def _record_then_edit(pd, fingerprint=None):
            result = orig_record(pd, fingerprint)
            if not state["injected"]:
                state["injected"] = True
                _bump_acceptance(Path(pd))
            return result

        monkeypatch.setattr(plan_drift, "record_baseline", _record_then_edit)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)

        assert result.final_status == "paused_on_drift", (
            f"expected paused_on_drift, got {result.final_status}"
        )
        assert impl.calls == [], "implementer must NOT be dispatched on stale context"
        assert aud.calls == [], "auditor must NOT be dispatched either"


# ───────────────────────────── auditor boundary ────────────────────────────


def test_auditor_call_skipped_on_concurrent_edit(monkeypatch):
    """AC2/AC7: the implementer runs, then another process edits features.json
    while it works; the auditor drift check pauses BEFORE the paid auditor call."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))

        # The implementer applies the concurrent edit as it dispatches.
        def _edit_during_impl(task):
            if task.agent_role == "implementer":
                _bump_acceptance(plan_dir)

        impl = _CountingExecutor("claude", on_dispatch=_edit_during_impl)
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)

        assert result.final_status == "paused_on_drift", (
            f"expected paused_on_drift, got {result.final_status}"
        )
        assert impl.calls == ["implementer"], "implementer should run exactly once"
        assert aud.calls == [], "auditor must NOT be dispatched on stale context"


# ──────────────────────────── gate-state boundary ──────────────────────────


def test_gate_state_edit_skips_paid_call(monkeypatch):
    """Finding #1 wiring: a mid-run edit to audit/gate-state.json is detected at
    the implementer boundary and pauses before the paid call."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()

        orig_record = plan_drift.record_baseline
        state = {"injected": False}

        def _record_then_edit_gate(pd, fingerprint=None):
            result = orig_record(pd, fingerprint)
            if not state["injected"]:
                state["injected"] = True
                audit = Path(pd) / "audit"
                audit.mkdir(parents=True, exist_ok=True)
                (audit / "gate-state.json").write_text(
                    json.dumps({"plan_id": "p", "cleared_gates": ["pre_merge"]})
                )
            return result

        monkeypatch.setattr(plan_drift, "record_baseline", _record_then_edit_gate)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)

        assert result.final_status == "paused_on_drift"
        assert impl.calls == [], "gate-state tamper must pause before the paid call"


# ─────────────────────────── fail-closed boundary ──────────────────────────


def test_drift_check_raising_does_not_dispatch_paid_call(monkeypatch):
    """codex #3 (AC5/AC6): if the drift check itself RAISES at the implementer
    boundary, the volley must FAIL CLOSED — pause before the paid call rather
    than swallow the error and continue on possibly-stale context. A safety
    mechanism that errors must not fail open. Here the dispatch-stage check
    passes (real behaviour) but the implementer-stage check is forced to raise;
    we assert no executor was dispatched."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()

        real_check = plan_drift.check_and_reconcile

        def _raise_at_implementer(plan_dir_arg, *, stage, **kwargs):
            if stage == plan_drift.STAGE_IMPLEMENTER:
                raise RuntimeError("simulated drift-check failure")
            return real_check(plan_dir_arg, stage=stage, **kwargs)

        monkeypatch.setattr(plan_drift, "check_and_reconcile", _raise_at_implementer)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)

        assert result.final_status == "paused_on_drift", (
            f"a raised drift check must pause fail-closed, got {result.final_status}"
        )
        assert impl.calls == [], "implementer must NOT be dispatched when the drift check errors"
        assert aud.calls == [], "auditor must NOT be dispatched when the drift check errors"


def test_missing_baseline_mid_run_fails_closed(monkeypatch):
    """codex #1 wiring: if the dispatch-start baseline is deleted/corrupted
    between dispatch and the implementer boundary, the REAL
    ``check_and_reconcile`` raises DriftBaselineMissingError and the volley
    pauses before the paid call rather than silently re-baselining the current
    state and proceeding. The dispatch-stage check runs unmodified; only the
    implementer-stage check finds the baseline gone."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()

        real_check = plan_drift.check_and_reconcile

        def _delete_baseline_at_implementer(plan_dir_arg, *, stage, **kwargs):
            if stage == plan_drift.STAGE_IMPLEMENTER:
                plan_drift.baseline_path(Path(plan_dir_arg)).unlink(missing_ok=True)
            # Delegate to the real check — at the implementer stage it now finds
            # no readable baseline and raises DriftBaselineMissingError.
            return real_check(plan_dir_arg, stage=stage, **kwargs)

        monkeypatch.setattr(
            plan_drift, "check_and_reconcile", _delete_baseline_at_implementer
        )

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)

        assert result.final_status == "paused_on_drift"
        assert impl.calls == [], "missing baseline mid-run must pause before the paid call"


# ───────────────────────── finalize (no-paid) boundary ──────────────────────


def test_finalize_refuses_on_drift(capsys):
    """Auditor finding #3: `dontpanic finalize` must refuse (exit 6) and leave
    features.json untouched when the plan drifted since dispatch — no signoff
    mutation against stale context."""
    from dontpanic_orchestrate import cli

    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        # Record the dispatch-start baseline, then another agent rewrites the
        # feature acceptance (context-refresh drift) before finalize runs.
        plan_drift.record_baseline(plan_dir)
        _bump_acceptance(plan_dir)

        rc = cli._finalize_main([str(plan_dir), "--feature", "F001"])

        assert rc == 6, f"finalize must refuse with exit 6 on drift, got {rc}"
        feats = json.loads((plan_dir / "features.json").read_text())
        assert feats["features"][0]["passes"] is False, (
            "features.json must NOT be flipped when finalize refused on drift"
        )
        err = capsys.readouterr().err
        assert "plan_drift" in err


# ──────────────── parameterized concurrent-edit matrix (volley path) ─────────
#
# Auditor i1 finding #2 (medium, test_coverage): the required volley-path
# concurrent-edit coverage was incomplete — loop caps, human gates, roles,
# allowed_paths, objective_contract, and additive decisions.jsonl were only
# exercised by the PURE classifier/reconcile tests, never proven to pause/
# reconcile on the actual ``dispatch_volley`` path. These tests close that gap:
# each mutation is injected by a SEPARATE process model (a one-shot wrapper that
# fires AFTER the clean dispatch-start baseline is written but BEFORE the
# dispatch-stage drift check), and we assert on the COUNTING executor that no
# paid call leaked through on stale context for the pause dimensions, and that
# the additive dimension reconciled-and-proceeded instead of pausing.


def _edit_frontmatter(plan_dir: Path, mutate) -> None:
    """Rewrite plan.md frontmatter via ``mutate(fm_dict)`` — used to simulate
    another interactive agent editing the plan's declared semantics mid-run."""
    text = (plan_dir / "plan.md").read_text()
    parts = text.split("---", 2)
    fm = yaml.safe_load(parts[1]) or {}
    mutate(fm)
    new_fm = yaml.safe_dump(fm, sort_keys=False)
    (plan_dir / "plan.md").write_text(f"---\n{new_fm}---{parts[2]}")


def _mutate_loop_caps(plan_dir: Path) -> None:
    _edit_frontmatter(plan_dir, lambda fm: fm["loop_caps"].update({"max_iterations": 9}))


def _mutate_human_gates(plan_dir: Path) -> None:
    _edit_frontmatter(plan_dir, lambda fm: fm.__setitem__("human_gates", ["pre_merge"]))


def _mutate_roles(plan_dir: Path) -> None:
    _edit_frontmatter(
        plan_dir, lambda fm: fm.__setitem__("agents_required", ["claude", "gemini"])
    )


def _make_child_charter_plan(plan_dir: Path) -> None:
    """Promote the demo plan to a valid CHILD plan carrying a child_charter with
    allowed_paths, so a later allowed_paths edit is a real scope/policy drift.
    The charter is schema-valid (orchestration.parent_plan_id present, commit
    policy agrees) so plan_loader.load accepts it; the parent need not exist on
    disk because the dispatch-stage drift check pauses before the nested-orch
    guards that would resolve it."""

    def _augment(fm):
        fm["orchestration"] = {
            "parent_plan_id": "2026-05-30-000-infra-drift-parent",
            "spawn_reason": "operator_manual",
        }
        fm["child_charter"] = {
            "kind": "implementation",
            "parent_objective": "demonstrate allowed_paths scope drift",
            "parent_acceptance_item": "AC-allowed-paths",
            "allowed_paths": ["scripts/**"],
            "return_condition_summary": "scope change acknowledged",
            "may_edit_product_code": False,
        }
        fm["commit_policy"] = {"mode": "evidence_only", "requires": []}

    _edit_frontmatter(plan_dir, _augment)


def _narrow_allowed_paths(plan_dir: Path) -> None:
    """Another agent narrows the child charter's allowed_paths mid-run — a
    BLOCKING scope/policy change that needs human acknowledgement."""
    _edit_frontmatter(
        plan_dir,
        lambda fm: fm["child_charter"].__setitem__("allowed_paths", ["scripts/safe/**"]),
    )


def _mutate_objective_contract(plan_dir: Path) -> None:
    (plan_dir / "objective_contract.json").write_text(
        json.dumps({"acceptance_signals": ["another agent rewrote the contract"]}) + "\n"
    )


def _one_shot_edit_after_baseline(monkeypatch, mutate) -> None:
    """Patch record_baseline so the FIRST call writes the clean dispatch-start
    baseline and then immediately applies ``mutate`` — modelling another process
    editing the plan in the window between baseline capture and the next check.
    One-shot so a later additive baseline-advance is not re-injected."""
    orig_record = plan_drift.record_baseline
    state = {"injected": False}

    def _record_then_edit(pd, fingerprint=None):
        result = orig_record(pd, fingerprint)
        if not state["injected"]:
            state["injected"] = True
            mutate(Path(pd))
        return result

    monkeypatch.setattr(plan_drift, "record_baseline", _record_then_edit)


@pytest.mark.parametrize(
    "mutate, expected_class",
    [
        (_mutate_loop_caps, plan_drift.DriftClass.CONTEXT_REFRESH),
        (_mutate_human_gates, plan_drift.DriftClass.CONTEXT_REFRESH),
        (_mutate_roles, plan_drift.DriftClass.CONTEXT_REFRESH),
        (_mutate_objective_contract, plan_drift.DriftClass.CONTEXT_REFRESH),
    ],
    ids=["loop_caps", "human_gates", "roles", "objective_contract"],
)
def test_volley_pauses_on_concurrent_edit_matrix(monkeypatch, mutate, expected_class):
    """AC2/AC4/AC7: each required refresh/blocking mutation made by another
    process mid-run pauses the volley on the dispatch path — the paid
    implementer call never happens — and is classified in the expected band."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()
        _one_shot_edit_after_baseline(monkeypatch, mutate)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)

        assert result.final_status == "paused_on_drift", (
            f"{expected_class.value}: expected paused_on_drift, got {result.final_status}"
        )
        assert impl.calls == [], "implementer must NOT be dispatched on stale context"
        assert aud.calls == [], "auditor must NOT be dispatched on stale context"
        # The persisted INBOX event records the actual classification band.
        inbox_text = (plan_dir / "INBOX.md").read_text()
        assert expected_class.value in inbox_text, (
            f"expected {expected_class.value} in INBOX, got:\n{inbox_text}"
        )


def test_volley_pauses_on_allowed_paths_scope_drift(monkeypatch):
    """AC4/AC7: a mid-run narrowing of the child charter's allowed_paths is a
    BLOCKING scope/policy drift — the volley pauses on the dispatch path, the
    paid implementer call never happens, and the INBOX records the blocking
    band requiring human acknowledgement. allowed_paths lives under
    child_charter, so the baseline plan is a valid child plan carrying it."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        _make_child_charter_plan(plan_dir)  # baseline plan now carries allowed_paths
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()
        _one_shot_edit_after_baseline(monkeypatch, _narrow_allowed_paths)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)

        assert result.final_status == "paused_on_drift", (
            f"allowed_paths scope drift must pause, got {result.final_status}"
        )
        assert impl.calls == [], "implementer must NOT be dispatched on a scope change"
        inbox_text = (plan_dir / "INBOX.md").read_text()
        assert plan_drift.DriftClass.BLOCKING_POLICY.value in inbox_text, (
            f"expected blocking_policy in INBOX, got:\n{inbox_text}"
        )


def test_volley_reconciles_additive_decisions_and_proceeds(monkeypatch):
    """AC3: an additive decisions.jsonl append made by another process mid-run is
    reconciled IN-PLACE on the volley path — the volley does NOT pause, the paid
    implementer call proceeds, and a plan_drift_reconciled event is recorded."""

    def _append_decision(plan_dir: Path) -> None:
        with (plan_dir / "decisions.jsonl").open("a") as f:
            f.write(json.dumps({"id": "D002", "title": "added", "body": "y"}) + "\n")

    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        impl = _CountingExecutor("claude")
        aud = _CountingExecutor("codex")
        _register(impl, aud)
        _disable_quota_gate()
        _one_shot_edit_after_baseline(monkeypatch, _append_decision)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)

        assert result.final_status != "paused_on_drift", (
            f"additive drift must NOT pause the volley, got {result.final_status}"
        )
        assert impl.calls == ["implementer"], (
            "additive drift must reconcile and let the paid implementer call proceed"
        )
        inbox_text = (plan_dir / "INBOX.md").read_text()
        assert "plan_drift_reconciled" in inbox_text, (
            f"expected a plan_drift_reconciled event in INBOX, got:\n{inbox_text}"
        )
