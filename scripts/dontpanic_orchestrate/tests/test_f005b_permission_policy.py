"""F005b — DispatchTask.permission_policy contract + role-derivation helper.

Covers F001 acceptance:
  - Helper maps role string → permission_policy correctly (single source of truth)
  - DispatchTask field exists with the right type and defaults to None
  - The volley body (_run_round) populates permission_policy from agent_role
    via the helper
  - dispatch_single_agent populates permission_policy via the same helper
    (verified via source inspection because the function's full setup —
    ExecutionEnvironment, plan_loader.load, registered_supervisor — is heavy
    to mock for one-line wiring; the helper is the single source of truth so
    the source-level assertion is sufficient when paired with the helper test)
  - permission_policy=None preserves legacy argv shape (covered separately
    in test_f005b_executor_argv.py — no flags added when policy is None)
"""

from __future__ import annotations

import inspect
import textwrap

import pytest

from dontpanic_orchestrate import supervisor
from dontpanic_orchestrate.executors.base import (
    DispatchResult,
    DispatchTask,
    _derive_permission_policy,
)

# ── F001 helper ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "agent_role,expected",
    [
        ("implementer", "implementer"),
        ("auditor", "auditor"),
        ("reviewer", None),
        ("verifier", None),
        ("", None),
        (None, None),
    ],
)
def test_derive_permission_policy(agent_role, expected):
    assert _derive_permission_policy(agent_role) == expected


# ── F001 DispatchTask field ───────────────────────────────────────────────


def test_dispatch_task_accepts_permission_policy_field(tmp_path):
    """The new optional field exists with the right type and defaults to None."""
    task = DispatchTask(
        plan_id="p",
        plan_dir=tmp_path,
        feature_id="F001",
        feature_description="d",
        feature_acceptance="a",
        feature_steps=[],
        agent_role="implementer",
    )
    # Default is None — preserves legacy behavior for any caller that hasn't
    # been updated to set it yet.
    assert task.permission_policy is None

    task2 = DispatchTask(
        plan_id="p",
        plan_dir=tmp_path,
        feature_id="F001",
        feature_description="d",
        feature_acceptance="a",
        feature_steps=[],
        agent_role="implementer",
        permission_policy="implementer",
    )
    assert task2.permission_policy == "implementer"


# ── F001 volley path (_run_round) ─────────────────────────────────────────


class _CapturingExecutor:
    """Captures the DispatchTask the supervisor passes in, returns a synthetic
    successful result so audit_writer downstream is happy."""

    agent_name = "claude"

    def __init__(self) -> None:
        self.captured: list[DispatchTask] = []

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.captured.append(task)
        return DispatchResult(
            agent="claude",
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at="2026-04-29T00:00:00Z",
            completed_at="2026-04-29T00:00:01Z",
            success=True,
            summary="ok",
        )


def _make_loaded(tmp_path):
    """Construct a minimal LoadedPlan that's just rich enough for _run_round."""
    plan_dir = tmp_path / "2026-04-29-002-feat-test"
    plan_dir.mkdir()
    (plan_dir / "audit").mkdir()
    return supervisor.plan_loader.LoadedPlan(
        plan_id="2026-04-29-002-feat-test",
        plan_dir=plan_dir,
        plan={
            "id": "2026-04-29-002-feat-test",
            "title": "t",
            "type": "feat",
            "tier": "trivial",
            "status": "draft",
            "date": "2026-04-29",
            "description": "test plan for F005b",
        },
        features={
            "task_id": "2026-04-29-002-feat-test",
            "schema_version": "1.0",
            "features": [],
        },
        schemas_dir=supervisor.plan_loader.SCHEMAS_DIR,
    )


def test_run_round_sets_permission_policy_from_role_implementer(tmp_path):
    """The volley body — _run_round — derives permission_policy from the role
    argument via _derive_permission_policy. Implementer case.

    target_env="dev" is passed so audit_writer.write's F002 gate accepts
    the audit (commands_run is empty here, so validate_target_context
    short-circuits — the writer just injects the canonical prelude into
    the summary). The DispatchTask we assert against is captured BEFORE
    audit_writer fires, so this test still pins the original contract.
    """
    loaded = _make_loaded(tmp_path)
    executor = _CapturingExecutor()
    feature = {
        "id": "F001",
        "description": "x is at least ten chars",
        "acceptance": "a",
        "steps": [],
    }
    supervisor._run_round(
        loaded=loaded,
        executor=executor,
        agent_name="claude",
        role="implementer",
        iteration=0,
        feature=feature,
        prompt="x",
        extra_validation=[],
        target_env="dev",
        target_project=None,
    )
    assert executor.captured, "expected at least one dispatch"
    task = executor.captured[-1]
    assert task.agent_role == "implementer"
    assert task.permission_policy == "implementer"


def test_run_round_sets_permission_policy_from_role_auditor(tmp_path):
    """The volley body — _run_round — derives permission_policy from the role
    argument via _derive_permission_policy. Auditor case."""
    loaded = _make_loaded(tmp_path)
    executor = _CapturingExecutor()
    feature = {
        "id": "F001",
        "description": "x is at least ten chars",
        "acceptance": "a",
        "steps": [],
    }
    supervisor._run_round(
        loaded=loaded,
        executor=executor,
        agent_name="claude",
        role="auditor",
        iteration=0,
        feature=feature,
        prompt="x",
        extra_validation=[],
        target_env="dev",
        target_project=None,
    )
    assert executor.captured, "expected at least one dispatch"
    task = executor.captured[-1]
    assert task.agent_role == "auditor"
    assert task.permission_policy == "auditor"


def test_run_round_legacy_role_yields_none_permission_policy(tmp_path):
    """Unknown roles fall through to permission_policy=None so executors emit
    no permission flags. This preserves the legacy argv shape that
    synthetic-disagreement / mock tests depend on."""
    loaded = _make_loaded(tmp_path)
    executor = _CapturingExecutor()
    feature = {
        "id": "F001",
        "description": "x is at least ten chars",
        "acceptance": "a",
        "steps": [],
    }
    supervisor._run_round(
        loaded=loaded,
        executor=executor,
        agent_name="claude",
        role="verifier",  # legacy / not implementer or auditor
        iteration=0,
        feature=feature,
        prompt="x",
        extra_validation=[],
        target_env="dev",
        target_project=None,
    )
    assert executor.captured[-1].permission_policy is None


# ── F001 dispatch_single_agent wiring ─────────────────────────────────────


def test_dispatch_single_agent_calls_derive_permission_policy():
    """dispatch_single_agent's full call surface (ExecutionEnvironment,
    plan_loader.load, _registered_supervisor, environment-registry validation,
    quota gate, audit_writer.build_audit) is heavy to mock for what amounts to
    a one-line wiring assertion. Since _derive_permission_policy is the single
    source of truth for the role→policy mapping (verified by the helper test),
    confirming dispatch_single_agent calls it at the DispatchTask construction
    site is sufficient. Source-level check: the function body must reference
    `_derive_permission_policy(agent_role)` so the produced task carries the
    right policy."""
    src = textwrap.dedent(inspect.getsource(supervisor.dispatch_single_agent))
    assert "_derive_permission_policy(agent_role)" in src, (
        "dispatch_single_agent must derive permission_policy from agent_role "
        "via the F005b helper at DispatchTask construction. If you've renamed "
        "the helper or the call site, update this assertion accordingly."
    )


def test_run_round_calls_derive_permission_policy():
    """Symmetric source-level check for _run_round (covers the volley path)."""
    src = textwrap.dedent(inspect.getsource(supervisor._run_round))
    assert "_derive_permission_policy(role)" in src, (
        "_run_round must derive permission_policy from role via the F005b "
        "helper at DispatchTask construction."
    )
