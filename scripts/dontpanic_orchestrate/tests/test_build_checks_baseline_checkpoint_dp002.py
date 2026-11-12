"""Build-checks baseline checkpoint (2026-11-07) -- DP-002 diagnostic reproduction.

BASELINE REPRODUCTION ONLY. These tests exercise the UNCHANGED production
approval writer (``gate_pause.approve_gate``) and its real entrypoints:

  * CLI   ``cli.main(["approve", ...])`` and ``cli.main(["resume", ..., "--gate", ...])``
  * MCP   ``mcp_server.dispatch_tool("approve_gate", ...)`` preview + confirm
  * Buzz  ``buzz_gate_bridge.process_approval`` with real BIP-340 signed events

Safety contract under test (lifecycle never-happen invariant): a lifecycle
gate for an unreached future stage (``pre_merge`` while the supervisor is
paused at ``pre_impl``) must be refused with no durable mutation, through
every entrypoint. Tests named ``test_red_*`` encode that contract and are
EXPECTED to fail on baseline 5bd81ae3 if the DP-002 hypothesis holds; they
are deliberately not xfail'd. Tests named ``test_control_*`` are green
baseline controls (valid pending approval, restart/duplicate replay, breaker,
implicit pre_impl, child pre_resume boundary) that must keep passing.

No production code is modified. Only the executor registry, quota/breaker
evaluators and notification sinks are replaced for determinism, mirroring
``test_lifecycle_staged_gates.py``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
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
    buzz_gate_bridge as bridge,
    circuit_breakers,
    cli,
    gate_pause,
    inbox,
    mcp_server,
    nostr_event,
    notify,
    projects_registry,
    supervisor,
)
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)

WORKTREE_PACKAGE_DIR = HERE.parents[1]

# ───────────────────────── synthetic plan fixtures ─────────────────────────

_PLAN_TEMPLATE = """---
id: {plan_id}
title: Build-checks baseline checkpoint DP-002 synthetic
type: infra
tier: trivial
status: draft
date: "2026-11-07"
description: Synthetic plan for the DP-002 baseline checkpoint.
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

# DP-002 checkpoint synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""


def _make_plan(repo: Path, plan_id: str, gates: list[str]) -> Path:
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    gates_yaml = "\n".join(f"  - {g}" for g in gates)
    (plan_dir / "plan.md").write_text(_PLAN_TEMPLATE.format(plan_id=plan_id, gates_yaml=gates_yaml))
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
                        "description": "Synthetic DP-002 feature.",
                        "steps": ["scripted"],
                        "acceptance": "Approval policy is enforced.",
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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Registered synthetic repo so the MCP strict resolver accepts plans.
    DONTPANIC_HOME is already redirected to tmp by conftest autouse."""
    r = tmp_path / "dp002-repo"
    r.mkdir()
    projects_registry.add_project("dp002", str(r))
    return r


def _tree_digest(plan_dir: Path) -> dict[str, str]:
    """Durable-state snapshot: every file under plan_dir -> sha256."""
    out: dict[str, str] = {}
    for p in sorted(plan_dir.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(plan_dir))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _state(plan_dir: Path) -> dict[str, Any]:
    p = gate_pause.gate_state_path(plan_dir)
    return json.loads(p.read_text()) if p.is_file() else {}


def _pause_pre_impl(plan_dir: Path, plan_id: str) -> None:
    gate_pause.record_pause(plan_dir, plan_id=plan_id, pause_gates=["pre_impl"], stage="pre_impl")


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = cli.main(argv)
        except SystemExit as exc:  # argparse paths
            rc = int(exc.code or 0)
    return int(rc or 0), out.getvalue(), err.getvalue()


# ───────────────────────── Buzz signed-event helpers ─────────────────────────

_CHANNEL = "11111111-2222-3333-4444-555555555555"
_HUMAN_SK = 11
_AGENT_SK = 33
_HUMAN_PUBKEY = nostr_event.pubkey_from_seckey(_HUMAN_SK)
_AGENT_PUBKEY = nostr_event.pubkey_from_seckey(_AGENT_SK)
_NOW = 1_785_000_000


@pytest.fixture
def buzz_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("BUZZ_GATE_WEBHOOK_SECRET", raising=False)
    path = tmp_path / "buzz.json"
    path.write_text(
        json.dumps(
            {
                "relay_url": "wss://relay.example.com",
                "channels": [_CHANNEL],
                "reporter_key_ref": "env:BUZZ_PRIVATE_KEY",
                "gate_bridge": {
                    "enabled": True,
                    "approver_pubkeys": [_HUMAN_PUBKEY],
                    "agent_pubkeys": [_AGENT_PUBKEY],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DONTPANIC_BUZZ_CONFIG", str(path))
    return path


def _buzz_payload(plan_id: str, gate: str, *, created_at: int = _NOW) -> bridge.ApprovalPayload:
    event: dict[str, object] = {
        "pubkey": _HUMAN_PUBKEY,
        "created_at": created_at,
        "kind": 9,
        "tags": [["h", _CHANNEL]],
        "content": bridge.approval_content(plan_id, gate),
    }
    event_id = nostr_event.compute_event_id(event)
    event["id"] = event_id
    event["sig"] = nostr_event.schnorr_sign(bytes.fromhex(event_id), _HUMAN_SK).hex()
    return bridge.parse_approval_payload({"event": event, "source": "poll"})


# ───────────────────────── scripted supervisor runtime ─────────────────────────


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _summary(agent: str, role: str) -> str:
    return (
        "Repo: synthetic\nEnv: dev\nProject: (none)\n\n## Target context\n"
        "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
        "Overall verdict: signed_off.\n"
        f"{agent}/{role} completed the scripted DP-002 checkpoint."
    )


class _ScriptedExecutor(BaseExecutor):
    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.dispatches: list[DispatchTask] = []

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.dispatches.append(task)
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


def _install_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[_ScriptedExecutor, _ScriptedExecutor]:
    impl, aud = _ScriptedExecutor("claude"), _ScriptedExecutor("codex")
    monkeypatch.setenv(notify.DISABLE_ENV, "1")
    monkeypatch.setitem(AGENT_REGISTRY, "claude", lambda: impl)
    monkeypatch.setitem(AGENT_REGISTRY, "codex", lambda: aud)
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
    # Capture-only notification boundary: record events, deliver nowhere.
    monkeypatch.setattr(
        supervisor.notify_event,
        "dispatch_event",
        lambda event, **kw: {},
    )
    return impl, aud


# ───────────────────────── identity control ─────────────────────────


def test_control_imports_resolve_to_this_worktree() -> None:
    for mod in (gate_pause, cli, mcp_server, bridge, supervisor):
        assert Path(mod.__file__).resolve().parent == WORKTREE_PACKAGE_DIR, mod.__file__


# ───────────────────────── first sharp negative: future pre_merge ─────────────────────────

_GATES = ["pre_impl", "pre_merge"]


def test_red_shared_writer_refuses_unreached_pre_merge_without_mutation(repo: Path) -> None:
    """Contract at the authoritative writer (safe-maintenance 'enforce at the
    actual writer'). Baseline hypothesis: approve_gate only checks
    already-cleared, so it clears pre_merge and marks the stage completed."""
    plan_id = "2026-11-07-201-infra-dp002-writer"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    _pause_pre_impl(plan_dir, plan_id)
    before = _tree_digest(plan_dir)

    changed = gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id)

    after_state = _state(plan_dir)
    assert changed is False, f"writer cleared unreached pre_merge; state={after_state}"
    assert _tree_digest(plan_dir) == before
    assert "pre_merge" not in (after_state.get("completed_stages") or [])
    assert after_state.get("pending_stage") == "pre_impl"


def test_control_cli_approve_refuses_unreached_pre_merge_byte_identical(repo: Path) -> None:
    plan_id = "2026-11-07-202-infra-dp002-cli-approve"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    _pause_pre_impl(plan_dir, plan_id)
    before = _tree_digest(plan_dir)

    rc, _out, err = _run_cli(["approve", str(plan_dir), "pre_merge"])

    assert rc == 2, err
    assert "not currently pending" in err
    assert _tree_digest(plan_dir) == before


def test_control_cli_resume_gate_refuses_unreached_pre_merge_byte_identical(repo: Path) -> None:
    plan_id = "2026-11-07-203-infra-dp002-cli-resume"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    _pause_pre_impl(plan_dir, plan_id)
    before = _tree_digest(plan_dir)

    rc, _out, err = _run_cli(["resume", str(plan_dir), "--gate", "pre_merge"])

    assert rc == 2, err
    assert "not currently pending" in err
    assert _tree_digest(plan_dir) == before


def test_control_buzz_refuses_unreached_pre_merge_byte_identical(
    repo: Path, buzz_enabled: Path
) -> None:
    plan_id = "2026-11-07-204-infra-dp002-buzz"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    _pause_pre_impl(plan_dir, plan_id)
    before = _tree_digest(plan_dir)

    decision = bridge.process_approval(
        plan_dir, plan_id=plan_id, payload=_buzz_payload(plan_id, "pre_merge"), now=_NOW
    )

    assert decision.approved is False
    assert decision.outcome == bridge.REFUSED_NOT_PENDING, decision
    assert _tree_digest(plan_dir) == before


def test_control_mcp_preview_does_not_mutate(repo: Path) -> None:
    plan_id = "2026-11-07-205-infra-dp002-mcp-preview"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    _pause_pre_impl(plan_dir, plan_id)
    before = _tree_digest(plan_dir)

    out = mcp_server.dispatch_tool("approve_gate", {"plan": plan_id, "gate": "pre_merge"})

    assert out["dry_run"] is True
    assert _tree_digest(plan_dir) == before


def test_red_mcp_preview_reports_unreached_pre_merge_as_not_clearable(repo: Path) -> None:
    """Preview/commit parity: the preview should not promise a clearance the
    CLI and Buzz entrypoints refuse."""
    plan_id = "2026-11-07-206-infra-dp002-mcp-preview-intent"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    _pause_pre_impl(plan_dir, plan_id)

    out = mcp_server.dispatch_tool("approve_gate", {"plan": plan_id, "gate": "pre_merge"})

    assert out["intent"]["would_clear"] is False, out


def test_red_mcp_confirm_refuses_unreached_pre_merge_without_mutation(repo: Path) -> None:
    plan_id = "2026-11-07-207-infra-dp002-mcp-confirm"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    _pause_pre_impl(plan_dir, plan_id)
    before = _tree_digest(plan_dir)

    try:
        out: dict[str, Any] | None = mcp_server.dispatch_tool(
            "approve_gate", {"plan": plan_id, "gate": "pre_merge", "confirm": True}
        )
    except mcp_server.MCPError:
        out = None  # a typed refusal is an acceptable contract shape

    after_state = _state(plan_dir)
    assert out is None or out["result"]["changed"] is False, (out, after_state)
    assert _tree_digest(plan_dir) == before, after_state
    assert "pre_merge" not in (after_state.get("completed_stages") or [])


def test_red_integrated_mcp_preclear_must_not_skip_pre_merge_pause(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end consequence through the real supervisor: pause at pre_impl,
    MCP confirm on pre_merge, operator clears pre_impl via CLI, redispatch.
    Contract: the volley must still pause at pre_merge before success."""
    impl, aud = _install_runtime(monkeypatch)
    plan_id = "2026-11-07-208-infra-dp002-integrated"
    plan_dir = _make_plan(repo, plan_id, _GATES)

    first = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert first.final_status == "paused_on_gate", first
    assert gate_pause.pending_stage(plan_dir) == "pre_impl"

    try:
        mcp_server.dispatch_tool(
            "approve_gate", {"plan": plan_id, "gate": "pre_merge", "confirm": True}
        )
    except mcp_server.MCPError:
        pass
    rc, _o, err = _run_cli(["approve", str(plan_dir), "pre_impl"])
    assert rc == 0, err

    second = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert second.final_status == "paused_on_gate", (
        f"supervisor reached {second.final_status!r} without a human pre_merge decision; "
        f"state={_state(plan_dir)}"
    )
    assert gate_pause.pending_stage(plan_dir) == "pre_merge"


# ───────────────────────── valid pending approval controls ─────────────────────────


def test_control_valid_pending_pre_impl_each_entrypoint_records_own_actor(
    repo: Path, buzz_enabled: Path
) -> None:
    """Valid pending approvals succeed through every entrypoint. Actor and
    INBOX side effects are recorded as observed, not forced identical."""
    observed: dict[str, dict[str, Any]] = {}

    cli_dir = _make_plan(repo, "2026-11-07-211-infra-dp002-valid-cli", _GATES)
    _pause_pre_impl(cli_dir, "2026-11-07-211-infra-dp002-valid-cli")
    rc, _o, err = _run_cli(["approve", str(cli_dir), "pre_impl"])
    assert rc == 0, err

    mcp_id = "2026-11-07-212-infra-dp002-valid-mcp"
    mcp_dir = _make_plan(repo, mcp_id, _GATES)
    _pause_pre_impl(mcp_dir, mcp_id)
    out = mcp_server.dispatch_tool("approve_gate", {"plan": mcp_id, "gate": "pre_impl", "confirm": True})
    assert out["result"]["changed"] is True

    buzz_id = "2026-11-07-213-infra-dp002-valid-buzz"
    buzz_dir = _make_plan(repo, buzz_id, _GATES)
    _pause_pre_impl(buzz_dir, buzz_id)
    decision = bridge.process_approval(
        buzz_dir, plan_id=buzz_id, payload=_buzz_payload(buzz_id, "pre_impl"), now=_NOW
    )
    assert decision.approved is True, decision

    for name, d in (("cli", cli_dir), ("mcp", mcp_dir), ("buzz", buzz_dir)):
        st = _state(d)
        assert "pre_impl" in st["cleared_gates"]
        assert "pre_impl" in st["completed_stages"]
        assert "pending_stage" not in st and "pause_gates" not in st
        observed[name] = {
            "actor": [h["actor"] for h in st["history"] if h.get("action") == "approve"],
            "inbox_gate_cleared": [e.event for e in inbox.read_events(d)].count("gate_cleared"),
        }

    assert observed["cli"]["actor"] == ["operator"]
    assert observed["buzz"]["actor"] == [f"buzz:{_HUMAN_PUBKEY}"]
    # Characterization (not a contract): MCP records the default actor and
    # writes no INBOX gate_cleared event.
    assert observed["mcp"]["actor"] == ["operator"]
    assert observed["cli"]["inbox_gate_cleared"] == 1
    assert observed["buzz"]["inbox_gate_cleared"] == 1
    assert observed["mcp"]["inbox_gate_cleared"] == 0, observed


def test_control_duplicate_replay_after_restart_is_noop_everywhere(
    repo: Path, buzz_enabled: Path
) -> None:
    """After a valid clear is durable, a fresh read (restart: every call
    re-reads gate-state.json) plus duplicate deliveries never re-mutate."""
    plan_id = "2026-11-07-214-infra-dp002-replay"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    _pause_pre_impl(plan_dir, plan_id)
    payload = _buzz_payload(plan_id, "pre_impl")
    first = bridge.process_approval(plan_dir, plan_id=plan_id, payload=payload, now=_NOW)
    assert first.approved is True
    settled = _tree_digest(plan_dir)

    replay = bridge.process_approval(plan_dir, plan_id=plan_id, payload=payload, now=_NOW)
    assert replay.approved is False
    assert replay.outcome in {bridge.NOOP_ALREADY_CLEARED, bridge.REFUSED_REPLAY}, replay

    rc, _o, _e = _run_cli(["approve", str(plan_dir), "pre_impl"])
    assert rc == 2
    rc, _o, _e = _run_cli(["resume", str(plan_dir), "--gate", "pre_impl"])
    assert rc == 2
    out = mcp_server.dispatch_tool("approve_gate", {"plan": plan_id, "gate": "pre_impl", "confirm": True})
    assert out["result"]["changed"] is False
    assert gate_pause.approve_gate(plan_dir, "pre_impl", plan_id=plan_id) is False

    assert _tree_digest(plan_dir) == settled


# ───────────────────────── boundary controls ─────────────────────────


def test_control_global_breaker_not_clearable_by_cli_or_mcp(repo: Path) -> None:
    """Global breaker is hard-stop. The supervisor never persists it in
    active_breakers (only APPROVAL_BREAKERS), so the writer has nothing to
    pop. This narrows the 'MCP can clear a global breaker' hypothesis."""
    plan_id = "2026-11-07-215-infra-dp002-global-breaker"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    _pause_pre_impl(plan_dir, plan_id)
    gate = f"breaker:{circuit_breakers.BreakerKind.GLOBAL_CIRCUIT_BREAKER.value}"
    assert circuit_breakers.BreakerKind.GLOBAL_CIRCUIT_BREAKER not in circuit_breakers.APPROVAL_BREAKERS
    before = _tree_digest(plan_dir)

    rc, _o, _e = _run_cli(["approve", str(plan_dir), gate])
    assert rc == 2
    rc, _o, _e = _run_cli(["resume", str(plan_dir), "--gate", gate])
    assert rc == 2
    out = mcp_server.dispatch_tool("approve_gate", {"plan": plan_id, "gate": gate, "confirm": True})
    assert out["result"]["changed"] is False
    assert _tree_digest(plan_dir) == before


def test_control_approval_breaker_and_defer_keep_relaxed_clearance(repo: Path) -> None:
    from dontpanic_orchestrate import quota_admission

    plan_id = "2026-11-07-216-infra-dp002-breaker-defer"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    kind = sorted(circuit_breakers.APPROVAL_BREAKERS, key=lambda k: k.value)[0]
    breaker_gate = circuit_breakers.gate_name(kind)
    defer_gate = quota_admission.gate_name(sorted(quota_admission.DeferKind, key=lambda k: k.value)[0])
    assert gate_pause.add_breaker(plan_dir, breaker_gate, plan_id=plan_id)
    assert gate_pause.add_defer(plan_dir, defer_gate, plan_id=plan_id)

    assert gate_pause.approve_gate(plan_dir, breaker_gate, plan_id=plan_id) is True
    assert gate_pause.approve_gate(plan_dir, defer_gate, plan_id=plan_id) is True
    st = _state(plan_dir)
    assert "active_breakers" not in st and "active_defers" not in st
    assert breaker_gate not in st["cleared_gates"] and defer_gate not in st["cleared_gates"]


def test_control_implicit_pre_impl_clear_for_active_plan(repo: Path) -> None:
    plan_id = "2026-11-07-217-infra-dp002-implicit"
    plan_dir = _make_plan(repo, plan_id, _GATES)

    assert gate_pause.implicit_clear_pre_impl_for_active_plan(
        plan_dir, plan_id=plan_id, declared_gates=_GATES
    )
    st = _state(plan_dir)
    assert st["cleared_gates"] == ["pre_impl"]
    assert st["completed_stages"] == ["pre_impl"]
    assert "pre_merge" not in st["cleared_gates"]
    assert [e["cleared_by"] for e in st["gate_events"]] == ["supervisor:plan_status_active"]
    assert gate_pause.implicit_clear_pre_impl_for_active_plan(
        plan_dir, plan_id=plan_id, declared_gates=_GATES
    ) is False


def test_control_corrupt_state_fix_stays_closed(repo: Path) -> None:
    """Previously fixed finding (kept closed, control only): reads are side-
    effect free on corrupt gate-state; the next write preserves the corrupt
    bytes before replacing them."""
    plan_id = "2026-11-07-220-infra-dp002-corrupt"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    p = gate_pause.gate_state_path(plan_dir)
    p.parent.mkdir(parents=True)
    corrupt = b"{not json \xff"
    p.write_bytes(corrupt)
    corrupt_copy = p.with_suffix(".corrupt.json")

    assert gate_pause.cleared_gates(plan_dir) == []
    assert gate_pause.load_gate_state_compat(plan_dir).pending_stage is None
    assert not corrupt_copy.exists()
    assert p.read_bytes() == corrupt

    _pause_pre_impl(plan_dir, plan_id)
    assert corrupt_copy.read_bytes() == corrupt
    assert _state(plan_dir)["pending_stage"] == "pre_impl"


def test_control_child_pre_resume_boundary_survives_mcp_confirm(repo: Path) -> None:
    """MCP confirm on an armed pre_resume_after_child gate does not release
    the parent pause (active_pre_resume_after_children is untouched), and
    CLI resume --gate refuses it. Observed writer pollution of
    cleared_gates is recorded, not asserted as a contract."""
    plan_id = "2026-11-07-218-infra-dp002-child-boundary"
    plan_dir = _make_plan(repo, plan_id, _GATES)
    child_id = "2026-11-07-219-infra-dp002-child"
    gate = f"pre_resume_after_child:{child_id}"
    assert gate_pause.add_pre_resume_after_child(plan_dir, child_id, plan_id=plan_id)
    gate_pause.record_pause(plan_dir, plan_id=plan_id, pause_gates=[gate])

    rc, _o, err = _run_cli(["resume", str(plan_dir), "--gate", gate])
    assert rc == 2, err

    out = mcp_server.dispatch_tool("approve_gate", {"plan": plan_id, "gate": gate, "confirm": True})
    st = _state(plan_dir)
    assert st["active_pre_resume_after_children"] == [gate]
    assert gate in gate_pause.evaluate(plan_dir, _GATES).unmet
    assert st.get("pause_gates") == [gate]
    # Observation only: what MCP reported and whether cleared_gates was written.
    print(
        "OBSERVED mcp_child_gate",
        json.dumps({"changed": out["result"]["changed"], "cleared_gates": st.get("cleared_gates")}),
    )
