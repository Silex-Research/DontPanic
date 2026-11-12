"""Build-checks baseline checkpoint (2026-11-07) -- DP-003 diagnostic reproduction.

BASELINE REPRODUCTION ONLY. Required contract under test: a volley may be
reported as successful (return value, INBOX ``volley_terminal`` with
``final_status=signed_off``, ``signoff``-kind notification, ``passes:true``
flip) only after a durable signoff exists and, when a child charter is
declared, charter compliance has passed.

Production code is executed unchanged through ``supervisor.dispatch_volley``
-> ``_emit_volley_terminal`` -> ``signoff_writer.write_signoff`` and the
consumers ``signed_off_finalizer.finalize_signed_off_feature``,
``cli.main(["finalize", ...])`` and ``mcp_server.dispatch_tool("dispatch")``.

Failure sources are kept separate:
  * ChildCharterViolation  -- REAL: child plan with no close-out memo, raised
    by the real ``check_child_charter_compliance``; no injection.
  * SignoffWriteError      -- real class raised by real ``build_signoff_dict``
    validation, but only reachable here through a boundary fault injection
    (``signoff_writer.VALID_TIERS`` emptied). A no-injection unit control
    proves the real validation path separately.
  * raw OSError            -- REAL ``IsADirectoryError`` from ``write_text``:
    a directory occupies the signoff path (environment fault, no mock).

Notifications are captured locally (``notify_event.dispatch_event`` replaced
by a recorder); nothing is delivered externally. ``test_red_*`` tests encode
the contract and are expected to fail on baseline 5bd81ae3 if DP-003 holds.
``test_control_*``/``test_measure_*`` tests are baseline controls or honest
measurements of current propagation and must pass.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    cli,
    inbox,
    gate_pause,
    mcp_server,
    nested_orchestration,
    notify,
    projects_registry,
    signed_off_finalizer,
    signoff_writer,
    supervisor,
)
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)

WORKTREE_PACKAGE_DIR = HERE.parents[1]
PARENT_ID = "2026-11-07-300-infra-dp003-parent"

# ───────────────────────── synthetic plans ─────────────────────────


def _plan_md(plan_id: str, gates: list[str], extra_blocks: str = "") -> str:
    gates_yaml = "\n".join(f"  - {g}" for g in gates)
    return f"""---
id: {plan_id}
title: Build-checks baseline checkpoint DP-003 synthetic
type: infra
tier: trivial
status: draft
date: "2026-11-07"
description: Synthetic plan for the DP-003 baseline checkpoint.
agents_required:
  - claude
  - codex
human_gates:
{gates_yaml}
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
{extra_blocks}links:
  features: ./features.json
---

# DP-003 checkpoint synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""


_CHILD_BLOCKS = f"""orchestration:
  parent_plan_id: {PARENT_ID}
  spawn_reason: operator_manual
  depth_limit: 3
child_charter:
  kind: implementation
  parent_objective: 'resolve synthetic parent finding'
  parent_acceptance_item: 'parent acceptance #1'
  allowed_paths:
    - 'docs/plans/**'
  forbidden_decisions: []
  return_condition_summary: 'synthetic finding closed'
  may_edit_product_code: false
  may_spawn_children: false
"""


def _make_plan(repo: Path, plan_id: str, gates: list[str], *, child: bool = False) -> Path:
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_plan_md(plan_id, gates, _CHILD_BLOCKS if child else ""))
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
                        "description": "Synthetic DP-003 feature.",
                        "steps": ["scripted"],
                        "acceptance": "Success only after durable signoff.",
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


def _make_child(repo: Path, plan_id: str, *, memo_status: str | None) -> Path:
    if not (repo / "docs" / "plans" / PARENT_ID).is_dir():
        _make_plan(repo, PARENT_ID, ["pre_merge"])
    plan_dir = _make_plan(repo, plan_id, ["pre_merge"], child=True)
    if memo_status is not None:
        ev = plan_dir / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        (ev / "closeout-memo.md").write_text(
            f"# Close-out\n\n## Return Condition\n\nstatus: {memo_status}\n"
        )
    return plan_dir


def _preclear_pre_merge(plan_dir: Path, plan_id: str) -> None:
    gate_pause.record_pause(plan_dir, plan_id=plan_id, pause_gates=["pre_merge"], stage="pre_merge")
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "dp003-repo"
    r.mkdir()
    projects_registry.add_project("dp003", str(r))
    return r


# ───────────────────────── scripted runtime + capture ─────────────────────────


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _summary(agent: str, role: str) -> str:
    return (
        "Repo: synthetic\nEnv: dev\nProject: (none)\n\n## Target context\n"
        "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
        "Overall verdict: signed_off.\n"
        f"{agent}/{role} completed the scripted DP-003 checkpoint."
    )


class _ScriptedExecutor(BaseExecutor):
    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=_summary(self.agent_name, task.agent_role),
            raw_response=_summary(self.agent_name, task.agent_role),
            error=None,
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Install deterministic executors/evaluators; capture notifications
    locally with NO external delivery."""
    events: list[Any] = []
    monkeypatch.setenv(notify.DISABLE_ENV, "1")
    monkeypatch.setitem(AGENT_REGISTRY, "claude", lambda: _ScriptedExecutor("claude"))
    monkeypatch.setitem(AGENT_REGISTRY, "codex", lambda: _ScriptedExecutor("codex"))
    monkeypatch.setattr(supervisor, "_quota_gate", lambda agent: (None, "[quota] bypassed"))
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "evaluate_global",
        lambda: supervisor.circuit_breakers.GlobalBreakerState(False, 0),
    )
    monkeypatch.setattr(supervisor.circuit_breakers, "check_wall_clock", lambda *a, **k: (False, ""))
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_budget_ceiling",
        lambda *a, **k: supervisor.circuit_breakers.BudgetCeilingResult(
            supervisor.circuit_breakers.BudgetCeilingKind.OK, False, ""
        ),
    )
    monkeypatch.setattr(
        supervisor.quota_admission,
        "evaluate",
        lambda *a, **k: supervisor.quota_admission.AdmissionCheck(
            supervisor.quota_admission.DispatchClass.AUTONOMOUS,
            supervisor.quota_admission.QuotaCheck(False, None, None, 90.0),
            supervisor.quota_admission.InteractiveCheck(False, None),
            frozenset(),
        ),
    )

    def _record(event: Any, **kw: Any) -> dict[str, bool]:
        events.append(event)
        return {}

    monkeypatch.setattr(supervisor.notify_event, "dispatch_event", _record)
    return events


def _success_events(plan_dir: Path) -> list[str]:
    return [
        e.headers.get("final_status", "")
        for e in inbox.read_events(plan_dir)
        if e.event == "volley_terminal" and e.headers.get("final_status") == "signed_off"
    ]


def _signoff_notifications(events: list[Any]) -> list[Any]:
    return [e for e in events if getattr(e, "kind", None) == "signoff"]


def _passes(plan_dir: Path) -> bool:
    data = json.loads((plan_dir / "features.json").read_text())
    return bool(data["features"][0]["passes"])


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = cli.main(argv)
        except SystemExit as exc:
            rc = int(exc.code or 0)
    return int(rc or 0), out.getvalue(), err.getvalue()


# ───────────────────────── identity + positive controls ─────────────────────────


def test_control_imports_resolve_to_this_worktree() -> None:
    for mod in (supervisor, signoff_writer, signed_off_finalizer, nested_orchestration, cli, mcp_server):
        assert Path(mod.__file__).resolve().parent == WORKTREE_PACKAGE_DIR, mod.__file__


def test_control_valid_top_level_success_durable_signoff_then_finalize(
    repo: Path, captured: list[Any]
) -> None:
    plan_id = "2026-11-07-301-infra-dp003-valid-top"
    plan_dir = _make_plan(repo, plan_id, ["pre_merge"])
    _preclear_pre_merge(plan_dir, plan_id)

    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert result.final_status == "signed_off", result
    sp = signoff_writer.signoff_path(plan_dir, plan_id)
    assert sp.is_file() and json.loads(sp.read_text())["signoff"] is True
    assert _success_events(plan_dir) == ["signed_off"]
    assert len(_signoff_notifications(captured)) == 1
    assert _passes(plan_dir) is False  # supervisor itself never flips passes

    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert fin.signoff_repaired is False
    assert fin.features_passes_flipped is True
    assert _passes(plan_dir) is True


def test_control_valid_child_success_writes_signoff_and_compliance(
    repo: Path, captured: list[Any]
) -> None:
    plan_id = "2026-11-07-302-infra-dp003-valid-child"
    plan_dir = _make_child(repo, plan_id, memo_status="satisfied")
    _preclear_pre_merge(plan_dir, plan_id)

    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert result.final_status == "signed_off", result
    assert signoff_writer.signoff_path(plan_dir, plan_id).is_file()
    side = json.loads(signoff_writer.charter_compliance_path(plan_dir, plan_id).read_text())
    assert side["return_condition_status"] == "satisfied"
    assert _success_events(plan_dir) == ["signed_off"]


def test_control_real_signoff_write_error_validation_writes_nothing(tmp_path: Path) -> None:
    """No injection: the real validation path raises the real class and
    persists no artifact."""
    plan_dir = tmp_path / "unit"
    (plan_dir / "audit").mkdir(parents=True)
    audit = plan_dir / "audit" / "x.json"
    audit.write_text("{}")
    with pytest.raises(signoff_writer.SignoffWriteError):
        signoff_writer.write_signoff(
            plan_id="p",
            tier="trivial",
            iteration=0,
            agents_in_panel=[],
            audit_paths=[audit],
            plan_dir=plan_dir,
            volley_status="signed_off",
        )
    assert not signoff_writer.signoff_path(plan_dir, "p").exists()


# ───────────────────────── ChildCharterViolation (real) ─────────────────────────

_CHILD_VIOLATION_ID = "2026-11-07-310-infra-dp003-child-violation"


def _dispatch_child_violation(repo: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Path, Any, str]:
    plan_dir = _make_child(repo, _CHILD_VIOLATION_ID, memo_status=None)
    _preclear_pre_merge(plan_dir, _CHILD_VIOLATION_ID)
    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    return plan_dir, result, capsys.readouterr().out


def test_control_child_violation_is_real_and_leaves_no_partial_artifact(
    repo: Path, captured: list[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    plan_dir, _result, out = _dispatch_child_violation(repo, capsys)
    assert "[volley] signoff_writer skipped:" in out
    assert "close-out memo not found" in out
    assert not signoff_writer.signoff_path(plan_dir, _CHILD_VIOLATION_ID).exists()
    assert not signoff_writer.charter_compliance_path(plan_dir, _CHILD_VIOLATION_ID).exists()


def test_red_child_violation_not_reported_as_success(
    repo: Path, captured: list[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    plan_dir, result, _out = _dispatch_child_violation(repo, capsys)
    observed = {
        "final_status": result.final_status,
        "inbox_success_events": _success_events(plan_dir),
        "signoff_notifications": len(_signoff_notifications(captured)),
    }
    assert result.final_status != "signed_off", observed
    assert observed["inbox_success_events"] == [], observed
    assert observed["signoff_notifications"] == 0, observed


def test_red_finalizer_refuses_child_without_durable_compliant_signoff(
    repo: Path, captured: list[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    plan_dir, _result, _out = _dispatch_child_violation(repo, capsys)
    try:
        fin = signed_off_finalizer.finalize_signed_off_feature(
            plan_dir, plan_id=_CHILD_VIOLATION_ID, feature_id="F001"
        )
        outcome: Any = fin
    except signed_off_finalizer.FinalizeError as exc:
        outcome = exc.code
    observed = {
        "outcome": repr(outcome),
        "passes": _passes(plan_dir),
        "signoff_exists": signoff_writer.signoff_path(plan_dir, _CHILD_VIOLATION_ID).exists(),
        "compliance_exists": signoff_writer.charter_compliance_path(plan_dir, _CHILD_VIOLATION_ID).exists(),
    }
    assert isinstance(outcome, str), observed
    assert observed["passes"] is False, observed


def test_red_cli_finalize_refuses_child_without_durable_compliant_signoff(
    repo: Path, captured: list[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    plan_dir, _result, _out = _dispatch_child_violation(repo, capsys)
    rc, out, err = _run_cli(["finalize", str(plan_dir), "--feature", "F001"])
    observed = {"rc": rc, "out": out[-400:], "err": err[-400:], "passes": _passes(plan_dir)}
    assert rc != 0, observed
    assert observed["passes"] is False, observed


def test_red_mcp_dispatch_does_not_report_success_on_child_violation(
    repo: Path, captured: list[Any]
) -> None:
    plan_id = "2026-11-07-311-infra-dp003-child-violation-mcp"
    plan_dir = _make_child(repo, plan_id, memo_status=None)
    _preclear_pre_merge(plan_dir, plan_id)
    try:
        out: Any = mcp_server.dispatch_tool(
            "dispatch", {"plan": plan_id, "feature": "F001", "confirm": True}
        )
        status = out["result"]["final_status"]
    except mcp_server.MCPError as exc:
        status = f"MCPError:{exc}"
    assert status != "signed_off", status


# ───────────────────────── SignoffWriteError (injected boundary fault) ─────────────────────────


def test_red_signoff_write_error_not_reported_as_success(
    repo: Path, captured: list[Any], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_id = "2026-11-07-320-infra-dp003-signoff-write-error"
    plan_dir = _make_plan(repo, plan_id, ["pre_merge"])
    _preclear_pre_merge(plan_dir, plan_id)
    # Boundary fault injection: real build_signoff_dict raises the real
    # SignoffWriteError because the tier allow-list is empty.
    monkeypatch.setattr(signoff_writer, "VALID_TIERS", frozenset())

    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    out = capsys.readouterr().out
    observed = {
        "final_status": result.final_status,
        "skip_line": [ln for ln in out.splitlines() if "signoff_writer skipped" in ln],
        "inbox_success_events": _success_events(plan_dir),
        "signoff_notifications": len(_signoff_notifications(captured)),
        "signoff_exists": signoff_writer.signoff_path(plan_dir, plan_id).exists(),
    }
    assert observed["skip_line"] and "not in" in observed["skip_line"][0], observed
    assert observed["signoff_exists"] is False, observed
    assert result.final_status != "signed_off", observed
    assert observed["inbox_success_events"] == [], observed
    assert observed["signoff_notifications"] == 0, observed


# ───────────────────────── raw OSError (real IsADirectoryError) ─────────────────────────


def _occupy_signoff_path(plan_dir: Path, plan_id: str) -> Path:
    p = signoff_writer.signoff_path(plan_dir, plan_id)
    p.mkdir(parents=True)
    return p


def test_measure_raw_oserror_propagates_out_of_dispatch(repo: Path, captured: list[Any]) -> None:
    """Honest measurement: _emit_volley_terminal does not catch raw OSError;
    it escapes dispatch_volley (not swallowed)."""
    plan_id = "2026-11-07-330-infra-dp003-raw-oserror"
    plan_dir = _make_plan(repo, plan_id, ["pre_merge"])
    _preclear_pre_merge(plan_dir, plan_id)
    _occupy_signoff_path(plan_dir, plan_id)

    with pytest.raises(OSError) as exc_info:
        supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert isinstance(exc_info.value, IsADirectoryError), repr(exc_info.value)
    assert _passes(plan_dir) is False


def test_red_raw_oserror_no_success_event_or_notification_before_failure(
    repo: Path, captured: list[Any]
) -> None:
    plan_id = "2026-11-07-331-infra-dp003-raw-oserror-events"
    plan_dir = _make_plan(repo, plan_id, ["pre_merge"])
    _preclear_pre_merge(plan_dir, plan_id)
    _occupy_signoff_path(plan_dir, plan_id)

    with pytest.raises(OSError):
        supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    observed = {
        "inbox_success_events": _success_events(plan_dir),
        "signoff_notifications": len(_signoff_notifications(captured)),
    }
    assert observed["inbox_success_events"] == [], observed
    assert observed["signoff_notifications"] == 0, observed


def test_measure_mcp_dispatch_maps_raw_oserror_to_internal_error(
    repo: Path, captured: list[Any]
) -> None:
    plan_id = "2026-11-07-332-infra-dp003-raw-oserror-mcp"
    plan_dir = _make_plan(repo, plan_id, ["pre_merge"])
    _preclear_pre_merge(plan_dir, plan_id)
    _occupy_signoff_path(plan_dir, plan_id)

    with pytest.raises(mcp_server.MCPError) as exc_info:
        mcp_server.dispatch_tool("dispatch", {"plan": plan_id, "feature": "F001", "confirm": True})
    assert exc_info.value.code == mcp_server.ERR_INTERNAL
    assert exc_info.value.data == {"error_type": "IsADirectoryError"}
    print(
        "OBSERVED mcp_raw_oserror",
        json.dumps(
            {
                "inbox_success_events": _success_events(plan_dir),
                "signoff_notifications": len(_signoff_notifications(captured)),
            }
        ),
    )
