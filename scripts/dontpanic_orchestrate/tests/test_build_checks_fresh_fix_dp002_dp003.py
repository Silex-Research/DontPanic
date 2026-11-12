"""Fresh-fix window 2026-11-07 (owner-authorized narrow fix) -- DP-002 / DP-003.

DP-002: the shared approval writer must not clear a lifecycle gate for a
stage other than the one the supervisor is currently paused on (pre_merge
while paused at pre_impl). Legacy approvals with no pending stage, and the
pre_impl no-pause compatibility, are preserved.

DP-003: successful finalization (including signoff repair) of a CHILD plan
requires a durable, charter-compliant signoff. Integrated path: real child
pre_merge pause -> real CLI approve -> real CLI finalize, for a noncompliant
child (must refuse, no passes flip) and a compliant child (must finalize).
A noncompliant child redispatch terminates `blocked`, not `signed_off`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import gate_pause, mcp_server, signoff_writer, supervisor  # noqa: E402
from dontpanic_orchestrate.tests.test_build_checks_baseline_checkpoint_dp002 import (  # noqa: E402
    _make_plan,
    _pause_pre_impl,
    _state,
    _tree_digest,
)
from dontpanic_orchestrate.tests.test_build_checks_baseline_checkpoint_dp003 import (  # noqa: E402,F401
    _make_child,
    _passes,
    _run_cli,
    captured,
    repo,
)

_GATES = ["pre_impl", "pre_merge"]


def test_dp002_writer_and_mcp_refuse_pre_merge_while_pre_impl_pending(repo: Path) -> None:
    plan_id = "2026-11-07-401-infra-fresh-dp002"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    _pause_pre_impl(plan_dir, plan_id)
    before = _tree_digest(plan_dir)

    preview = mcp_server.dispatch_tool("approve_gate", {"plan": plan_id, "gate": "pre_merge"})
    out = mcp_server.dispatch_tool(
        "approve_gate", {"plan": plan_id, "gate": "pre_merge", "confirm": True}
    )

    assert preview["intent"]["would_clear"] is False, preview
    assert out["result"]["changed"] is False, out
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id) is False
    assert _tree_digest(plan_dir) == before
    assert _state(plan_dir)["pending_stage"] == "pre_impl"


def test_dp002_pending_and_legacy_approvals_still_clear(repo: Path) -> None:
    pending_id = "2026-11-07-402-infra-fresh-dp002-pending"
    pending_dir = _make_plan(repo, pending_id, _GATES)
    _pause_pre_impl(pending_dir, pending_id)
    out = mcp_server.dispatch_tool(
        "approve_gate", {"plan": pending_id, "gate": "pre_impl", "confirm": True}
    )
    assert out["result"]["changed"] is True

    legacy_id = "2026-11-07-403-infra-fresh-dp002-legacy"
    legacy_dir = _make_plan(repo, legacy_id, _GATES)
    # No pause recorded at all: legacy/no-pause approvals keep working.
    assert gate_pause.approve_gate(legacy_dir, "pre_merge", plan_id=legacy_id) is True
    assert gate_pause.approve_gate(legacy_dir, "pre_impl", plan_id=legacy_id) is True


def _child_through_real_pause_and_cli_approve(repo: Path, plan_id: str, memo: str | None) -> Path:
    plan_dir = _make_child(repo, plan_id, memo_status=memo)
    first = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert first.final_status == "paused_on_gate", first
    assert gate_pause.pending_stage(plan_dir) == "pre_merge"
    rc, _o, err = _run_cli(["approve", str(plan_dir), "pre_merge"])
    assert rc == 0, err
    second = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    # A charter-noncompliant child (no close-out memo) must never be reported
    # as signed_off; it is downgraded to the existing `blocked` terminal.
    expected = "signed_off" if memo == "satisfied" else "blocked"
    assert second.final_status == expected, second
    return plan_dir


def test_dp003_cli_finalize_refuses_noncompliant_child(repo: Path, captured: list[Any]) -> None:
    plan_id = "2026-11-07-404-infra-fresh-dp003-noncompliant"
    plan_dir = _child_through_real_pause_and_cli_approve(repo, plan_id, memo=None)

    rc, out, err = _run_cli(["finalize", str(plan_dir), "--feature", "F001"])

    assert rc != 0, (rc, out, err)
    assert "child" in err.lower() or "charter" in err.lower(), err
    assert _passes(plan_dir) is False
    assert not signoff_writer.signoff_path(plan_dir, plan_id).exists()
    assert not signoff_writer.charter_compliance_path(plan_dir, plan_id).exists()


def test_dp003_cli_finalize_accepts_compliant_child(repo: Path, captured: list[Any]) -> None:
    plan_id = "2026-11-07-405-infra-fresh-dp003-compliant"
    plan_dir = _child_through_real_pause_and_cli_approve(repo, plan_id, memo="satisfied")

    rc, out, err = _run_cli(["finalize", str(plan_dir), "--feature", "F001"])

    assert rc == 0, (rc, out, err)
    assert _passes(plan_dir) is True
    assert signoff_writer.signoff_path(plan_dir, plan_id).is_file()
    side = json.loads(signoff_writer.charter_compliance_path(plan_dir, plan_id).read_text())
    assert side["return_condition_status"] == "satisfied"
