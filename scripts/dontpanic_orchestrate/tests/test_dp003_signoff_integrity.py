"""DP-003 signoff integrity (Sentinel review 5869656515).

Contract: charter violations or missing required child signoff cannot be
presented as successful finalization, including repair paths; a reported
``signed_off`` requires a successful durable signoff.

Covers:
  Item 2  — the F007 finalizer validates an EXISTING signoff before flipping
            passes (empty/torn, stale, non-success, wrong plan, child
            compliance side-car missing/failing) and still accepts a valid one
            without clobbering it.
  Item 3a — the transcript terminal records the FINAL status returned by
            ``_emit_volley_terminal`` (never a signed_off later downgraded).
  Item 3b — ``signoff_writer`` writes the child compliance side-car BEFORE the
            signoff; a failed signoff write leaves no valid-looking signoff.
  Item 4a — signed_off with empty audit_paths is announced as ``blocked``.
  Item 4b — PatchCompletenessError / CrossFeatureEditError in the deferred
            signed_off path produce exactly one non-success terminal INBOX +
            notify entry and still propagate.

Real code paths throughout; the only substitutions are deterministic
executors / quota checks for ``dispatch_volley`` (as in the neighbouring
build-checks tests), a local notification recorder (no external delivery),
and explicit write-fault injection at the signoff_writer file boundary.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    gate_pause,
    inbox,
    notify,
    plan_loader,
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
from dontpanic_orchestrate.patch_completeness_gate import PatchCompletenessError  # noqa: E402
from dontpanic_orchestrate.plan_review.cross_feature import CrossFeatureEditError  # noqa: E402

PARENT_ID = "2026-11-12-400-infra-dp003i-parent"
TOP_ID = "2026-11-12-401-infra-dp003i-top"
CHILD_ID = "2026-11-12-402-infra-dp003i-child"


# ───────────────────────── synthetic plans ─────────────────────────


def _plan_md(plan_id: str, extra_blocks: str = "") -> str:
    return f"""---
id: {plan_id}
title: DP-003 signoff integrity synthetic
type: infra
tier: trivial
status: draft
date: "2026-11-12"
description: Synthetic plan for DP-003 signoff integrity tests.
agents_required:
  - claude
  - codex
human_gates:
  - pre_merge
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
{extra_blocks}links:
  features: ./features.json
---

# DP-003 signoff integrity synthetic

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


def _feature(fid: str, description: str) -> dict[str, Any]:
    return {
        "id": fid,
        "category": "test",
        "phase": 0,
        "description": description,
        "steps": ["scripted"],
        "acceptance": "Success only after durable signoff.",
        "passes": False,
        "depends_on": [],
    }


def _make_plan(
    repo: Path,
    plan_id: str,
    *,
    child: bool = False,
    features: list[dict[str, Any]] | None = None,
) -> Path:
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_plan_md(plan_id, _CHILD_BLOCKS if child else ""))
    feats = features or [_feature("F001", "Synthetic DP-003 feature.")]
    (plan_dir / "features.json").write_text(
        json.dumps({"task_id": plan_id, "schema_version": "1.0", "features": feats}, indent=2)
        + "\n"
    )
    return plan_dir


def _make_child(repo: Path, plan_id: str = CHILD_ID, *, memo_status: str | None) -> Path:
    if not (repo / "docs" / "plans" / PARENT_ID).is_dir():
        _make_plan(repo, PARENT_ID)
    plan_dir = _make_plan(repo, plan_id, child=True)
    if memo_status is not None:
        ev = plan_dir / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        (ev / "closeout-memo.md").write_text(
            f"# Close-out\n\n## Return Condition\n\nstatus: {memo_status}\n"
        )
    return plan_dir


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_envelopes(
    plan_dir: Path,
    plan_id: str,
    *,
    iteration: int = 0,
    completed_at: dt.datetime | None = None,
) -> Path:
    """Implementer + signed_off auditor envelopes for F001 at ``iteration``.
    Returns the auditor envelope path."""
    audit = plan_dir / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    ts = _iso(completed_at or dt.datetime.now(dt.timezone.utc))
    (audit / f"claude-implementer-F001-i{iteration}.json").write_text(
        json.dumps({"agent": "claude", "agent_role": "implementer", "iteration": iteration})
    )
    auditor = audit / f"codex-auditor-F001-i{iteration}.json"
    auditor.write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "audit_id": f"{plan_id}#codex#{iteration}",
                "agent": "codex",
                "agent_role": "auditor",
                "iteration": iteration,
                "started_at": ts,
                "completed_at": ts,
                "audit_status": "signed_off",
                "findings": [],
                "summary": "Looks good.",
            }
        )
    )
    return auditor


def _clear_pre_merge(plan_dir: Path, plan_id: str) -> None:
    gate_pause.record_pause(plan_dir, plan_id=plan_id, pause_gates=["pre_merge"], stage="pre_merge")
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=plan_id)


def _write_valid_signoff(
    plan_dir: Path,
    plan_id: str,
    auditor: Path,
    *,
    iteration: int = 0,
    volley_status: str = "signed_off",
    child: bool = False,
) -> Path:
    loaded = plan_loader.load(plan_dir) if child else None
    return signoff_writer.write_signoff(
        plan_id=plan_id,
        tier="trivial",
        iteration=iteration,
        agents_in_panel=["claude", "codex"],
        audit_paths=[auditor],
        plan_dir=plan_dir,
        volley_status=volley_status,
        child_charter=loaded.child_charter if loaded else None,
        commit_policy=loaded.commit_policy if loaded else None,
    )


def _passes(plan_dir: Path) -> bool:
    data = json.loads((plan_dir / "features.json").read_text())
    return bool(data["features"][0]["passes"])


def _audit_snapshot(plan_dir: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted((plan_dir / "audit").iterdir()) if p.is_file()}


def _assert_refused(plan_dir: Path, plan_id: str, code: str) -> None:
    """Finalize refuses with ``code``; no passes flip and no file writes."""
    before_audit = _audit_snapshot(plan_dir)
    before_features = (plan_dir / "features.json").read_bytes()
    with pytest.raises(signed_off_finalizer.FinalizeError) as exc:
        signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert exc.value.code == code, (exc.value.code, str(exc.value))
    assert _passes(plan_dir) is False
    assert (plan_dir / "features.json").read_bytes() == before_features
    assert _audit_snapshot(plan_dir) == before_audit


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "dp003i-repo"
    r.mkdir()
    projects_registry.add_project("dp003i", str(r))
    return r


# ───────────────────────── Item 2 — existing signoff validation ─────────────────────────


def test_item2_empty_signoff_file_refused(repo: Path) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    _write_envelopes(plan_dir, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    signoff_writer.signoff_path(plan_dir, TOP_ID).write_text("")
    _assert_refused(plan_dir, TOP_ID, "signoff_unreadable")


def test_item2_torn_signoff_json_refused(repo: Path) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    sp = _write_valid_signoff(plan_dir, TOP_ID, auditor)
    sp.write_text(sp.read_text()[:40])  # truncated mid-object
    _assert_refused(plan_dir, TOP_ID, "signoff_unreadable")


def test_item2_stale_signoff_for_older_iteration_refused(repo: Path) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    old_auditor = _write_envelopes(plan_dir, TOP_ID, iteration=0)
    _clear_pre_merge(plan_dir, TOP_ID)
    _write_valid_signoff(plan_dir, TOP_ID, old_auditor, iteration=0)
    # A newer signed_off verdict (i1) is now the selected envelope.
    new_auditor = _write_envelopes(plan_dir, TOP_ID, iteration=1)
    later = old_auditor.stat().st_mtime + 10
    os.utime(new_auditor, (later, later))
    _assert_refused(plan_dir, TOP_ID, "signoff_stale")


def test_item2_stale_signoff_predating_rewritten_envelope_refused(repo: Path) -> None:
    """Re-dispatch reuses the ``-i0`` filename: the old signoff lists the same
    path and iteration but predates the fresh verdict's completed_at."""
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    sp = _write_valid_signoff(plan_dir, TOP_ID, auditor)
    data = json.loads(sp.read_text())
    data["decided_at"] = "2020-01-01T00:00:00Z"
    sp.write_text(json.dumps(data, indent=2) + "\n")
    _assert_refused(plan_dir, TOP_ID, "signoff_stale")


def test_item2_non_success_signoff_refused(repo: Path) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    sp = _write_valid_signoff(plan_dir, TOP_ID, auditor, volley_status="blocked")
    assert json.loads(sp.read_text())["signoff"] is False
    _assert_refused(plan_dir, TOP_ID, "signoff_not_success")


def test_item2_wrong_plan_signoff_refused(repo: Path) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    other = signoff_writer.build_signoff_dict(
        plan_id="2026-11-12-499-some-other-plan",
        tier="trivial",
        iteration=0,
        agents_in_panel=["claude", "codex"],
        audit_paths=[auditor],
        plan_dir=plan_dir,
        volley_status="signed_off",
    )
    signoff_writer.signoff_path(plan_dir, TOP_ID).write_text(json.dumps(other, indent=2) + "\n")
    _assert_refused(plan_dir, TOP_ID, "signoff_wrong_plan")


def test_item2_child_signoff_with_missing_compliance_sidecar_refused(repo: Path) -> None:
    plan_dir = _make_child(repo, memo_status="satisfied")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    side = signoff_writer.charter_compliance_path(plan_dir, CHILD_ID)
    assert side.is_file()
    side.unlink()
    _assert_refused(plan_dir, CHILD_ID, "child_signoff_missing")


def test_item2_child_signoff_with_failing_compliance_sidecar_refused(repo: Path) -> None:
    plan_dir = _make_child(repo, memo_status="satisfied")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    side = signoff_writer.charter_compliance_path(plan_dir, CHILD_ID)
    data = json.loads(side.read_text())
    data["return_condition_status"] = None  # not a recorded compliance result
    side.write_text(json.dumps(data, indent=2) + "\n")
    _assert_refused(plan_dir, CHILD_ID, "child_signoff_missing")


def test_item2_valid_existing_signoff_accepted_without_clobber(repo: Path) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    sp = _write_valid_signoff(plan_dir, TOP_ID, auditor)
    before = sp.read_bytes()

    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=TOP_ID, feature_id="F001")

    assert fin.signoff_repaired is False
    assert fin.features_passes_flipped is True
    assert _passes(plan_dir) is True
    assert sp.read_bytes() == before


def test_item2_valid_existing_child_signoff_with_sidecar_accepted(repo: Path) -> None:
    plan_dir = _make_child(repo, memo_status="satisfied")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    sp = _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    before = sp.read_bytes()

    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=CHILD_ID, feature_id="F001")

    assert fin.signoff_repaired is False
    assert fin.features_passes_flipped is True
    assert sp.read_bytes() == before


# ───────────────────────── scripted dispatch runtime (Item 3a) ─────────────────────────


def _summary(agent: str, role: str) -> str:
    return (
        "Repo: synthetic\nEnv: dev\nProject: (none)\n\n## Target context\n"
        "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
        "Overall verdict: signed_off.\n"
        f"{agent}/{role} completed the scripted DP-003 integrity run."
    )


class _ScriptedExecutor(BaseExecutor):
    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        now = _iso(dt.datetime.now(dt.timezone.utc))
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=now,
            completed_at=now,
            success=True,
            summary=_summary(self.agent_name, task.agent_role),
            raw_response=_summary(self.agent_name, task.agent_role),
            error=None,
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Deterministic executors/quota; notifications recorded locally only."""
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


def _transcript_terminals(plan_dir: Path) -> list[str]:
    text = (plan_dir / "audit" / "transcript.md").read_text()
    out = []
    for line in text.splitlines():
        if " terminal: `" in line:
            out.append(line.split(" terminal: `", 1)[1].split("`", 1)[0])
    return out


def test_item3a_transcript_records_signed_off_on_success(repo: Path, captured: list[Any]) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert result.final_status == "signed_off", result
    assert _transcript_terminals(plan_dir) == ["signed_off"]


def test_item3a_transcript_records_blocked_on_child_charter_violation(
    repo: Path, captured: list[Any]
) -> None:
    plan_dir = _make_child(repo, memo_status=None)  # no close-out memo -> real violation
    _clear_pre_merge(plan_dir, CHILD_ID)
    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert result.final_status == "blocked", result
    assert _transcript_terminals(plan_dir) == ["blocked"]


def test_item3a_transcript_records_blocked_on_signoff_write_error(
    repo: Path, captured: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    # Boundary fault: real build_signoff_dict raises the real SignoffWriteError.
    monkeypatch.setattr(signoff_writer, "VALID_TIERS", frozenset())
    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert result.final_status == "blocked", result
    assert _transcript_terminals(plan_dir) == ["blocked"]


def test_item3a_transcript_records_blocked_when_terminal_raises(
    repo: Path, captured: list[Any]
) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    signoff_writer.signoff_path(plan_dir, TOP_ID).mkdir(parents=True)  # real IsADirectoryError
    with pytest.raises(IsADirectoryError):
        supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert _transcript_terminals(plan_dir) == ["blocked"]


# ───────────────────────── Item 3b — side-car before signoff ─────────────────────────


def _fail_writes_to(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    real = signoff_writer._atomic_write_json

    def _faulty(path: Path, obj: dict[str, Any]) -> None:
        if Path(path) == target:
            raise OSError(28, "No space left on device (injected)")
        real(path, obj)

    monkeypatch.setattr(signoff_writer, "_atomic_write_json", _faulty)


def test_item3b_signoff_write_failure_after_sidecar_leaves_no_signoff(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _make_child(repo, memo_status="satisfied")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    sp = signoff_writer.signoff_path(plan_dir, CHILD_ID)
    _fail_writes_to(monkeypatch, sp)

    with pytest.raises(OSError):
        _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)

    # Side-car was written first, then rolled back with the failed signoff
    # (Sentinel 5870049314 HIGH-3 — all-or-nothing): neither artifact (nor
    # any temp file) remains.
    assert not signoff_writer.charter_compliance_path(plan_dir, CHILD_ID).exists()
    assert not sp.exists()
    assert not [p for p in (plan_dir / "audit").iterdir() if p.name.endswith(".tmp")]

    # The orphan side-car is not success: finalize cannot flip passes while
    # the signoff cannot be made durable.
    with pytest.raises(OSError):
        signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=CHILD_ID, feature_id="F001")
    assert not sp.exists()
    assert _passes(plan_dir) is False


def test_item3b_sidecar_write_failure_writes_no_signoff(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _make_child(repo, memo_status="satisfied")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _fail_writes_to(monkeypatch, signoff_writer.charter_compliance_path(plan_dir, CHILD_ID))

    with pytest.raises(OSError):
        _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)

    assert not signoff_writer.signoff_path(plan_dir, CHILD_ID).exists()
    assert not signoff_writer.charter_compliance_path(plan_dir, CHILD_ID).exists()


def test_item3b_orphan_sidecar_with_torn_signoff_is_refused(repo: Path) -> None:
    plan_dir = _make_child(repo, memo_status="satisfied")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    sp = _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    sp.write_text("")  # passing side-car alone, signoff not durable
    _assert_refused(plan_dir, CHILD_ID, "signoff_unreadable")


# ───────────────────────── Item 4 — _emit_volley_terminal MEDs ─────────────────────────


def _terminal_inbox(plan_dir: Path) -> list[inbox.InboxEntry]:
    return [e for e in inbox.read_events(plan_dir) if e.event == "volley_terminal"]


def test_item4a_signed_off_with_empty_audit_paths_is_blocked(
    repo: Path, captured: list[Any]
) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    loaded = plan_loader.load(plan_dir)

    out = supervisor._emit_volley_terminal(
        supervisor.VolleyResult("signed_off", 1, "auditor signed off", []),
        loaded=loaded,
        feature_id="F001",
        agents_in_panel=["claude", "codex"],
    )

    assert out.final_status == "blocked"
    assert "no signoff possible" in out.reason
    terminals = _terminal_inbox(plan_dir)
    assert [e.headers.get("final_status") for e in terminals] == ["blocked"]
    assert [getattr(e, "kind", None) for e in captured] == ["volley_terminal"]
    assert not signoff_writer.signoff_path(plan_dir, TOP_ID).exists()


def _git_state(plan_dir: Path, state: dict[str, Any]) -> None:
    ev = plan_dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    full = {
        "staged": [],
        "unstaged_modified": [],
        "untracked": [],
        "deleted_staged": [],
        "deleted_unstaged": [],
    }
    full.update(state)
    (ev / "git-state-0-implementer.json").write_text(json.dumps(full) + "\n")


def _assert_one_blocked_terminal(plan_dir: Path, captured: list[Any], cls_name: str) -> None:
    terminals = _terminal_inbox(plan_dir)
    assert len(terminals) == 1, terminals
    assert terminals[0].headers.get("final_status") == "blocked"
    assert cls_name in terminals[0].body
    assert len(captured) == 1, captured
    assert captured[0].kind == "volley_terminal"
    assert captured[0].technical_metadata["final_status"] == "blocked"
    assert not signoff_writer.signoff_path(plan_dir, plan_dir.name).exists()


def test_item4b_patch_completeness_error_announces_blocked_and_propagates(
    repo: Path, captured: list[Any]
) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID)
    # Real Mode-3 violation: an untracked test file the patch never declared.
    (plan_dir / "tests").mkdir()
    (plan_dir / "tests" / "test_new.py").write_text("def test_x(): assert True\n")
    _git_state(plan_dir, {"untracked": ["tests/test_new.py"]})
    loaded = plan_loader.load(plan_dir)

    with pytest.raises(PatchCompletenessError):
        supervisor._emit_volley_terminal(
            supervisor.VolleyResult("signed_off", 1, "auditor signed off", [auditor]),
            loaded=loaded,
            feature_id="F001",
            agents_in_panel=["claude", "codex"],
        )

    _assert_one_blocked_terminal(plan_dir, captured, "PatchCompletenessError")


def test_item4b_dispatch_level_patch_gate_failure_announced_exactly_once(
    repo: Path, captured: list[Any]
) -> None:
    """Through dispatch_volley the F004 backstop converts the propagated
    PatchCompletenessError into a blocked return; the failure is still
    announced exactly once (no duplicate from the backstop)."""
    plan_dir = _make_plan(repo, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    # Real Mode-3 violation in a real git repo: an untracked test file next to
    # a tracked one (so git lists it individually, not as a collapsed dir).
    git = ["git", "-C", str(plan_dir), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", str(plan_dir)], check=True)
    (plan_dir / "tests").mkdir()
    (plan_dir / "tests" / "conftest.py").write_text("")
    subprocess.run([*git, "add", "tests/conftest.py"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "seed"], check=True)
    (plan_dir / "tests" / "test_new.py").write_text("def test_x(): assert True\n")

    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert result.final_status == "blocked", result
    terminals = _terminal_inbox(plan_dir)
    assert [e.headers.get("final_status") for e in terminals] == ["blocked"], terminals
    assert "PatchCompletenessError" in terminals[0].body
    kinds = [getattr(e, "kind", None) for e in captured]
    assert kinds.count("volley_terminal") == 1, kinds
    assert "signoff" not in kinds
    assert _transcript_terminals(plan_dir) == ["blocked"]
    # Sentinel r3b LOW2: the F004 backstop still records its (non-terminal)
    # crash entry exactly once, and adds no second terminal entry.
    assert _crash_caught(plan_dir) == ["PatchCompletenessError"]


def _crash_caught(plan_dir: Path) -> list[str | None]:
    return [
        e.headers.get("exception_class")
        for e in inbox.read_events(plan_dir)
        if e.event == "volley_crash_caught"
    ]


def test_r3b_dispatch_level_cross_feature_failure_announced_exactly_once(
    repo: Path, captured: list[Any]
) -> None:
    """Sentinel r3b LOW2 — through dispatch_volley a CrossFeatureEditError
    from the signed_off gates reaches the F004 backstop: exactly one terminal
    INBOX entry + one terminal notification (the gate's blocked announcement;
    the backstop passes announce=False), plus one volley_crash_caught."""
    plan_dir = _make_plan(
        repo,
        TOP_ID,
        features=[
            _feature("F001", "Synthetic DP-003 feature."),
            _feature("F002", "Foreign feature that owns src/foreign_module.py."),
        ],
    )
    _clear_pre_merge(plan_dir, TOP_ID)
    git = ["git", "-C", str(plan_dir), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", str(plan_dir)], check=True)
    (plan_dir / "src").mkdir()
    (plan_dir / "src" / "foreign_module.py").write_text("X = 1\n")
    subprocess.run([*git, "add", "src/foreign_module.py"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "seed"], check=True)
    (plan_dir / "src" / "foreign_module.py").write_text("X = 2\n")  # foreign bleed

    result = supervisor.dispatch_volley(
        plan_dir,
        "F001",
        max_iterations=1,
        allow_incomplete_patch_reason="operator accepts patch shape for this test",
    )

    assert result.final_status == "blocked", result
    terminals = _terminal_inbox(plan_dir)
    assert [e.headers.get("final_status") for e in terminals] == ["blocked"], terminals
    assert "CrossFeatureEditError" in terminals[0].body
    kinds = [getattr(e, "kind", None) for e in captured]
    assert kinds.count("volley_terminal") == 1, kinds
    assert "signoff" not in kinds
    assert _crash_caught(plan_dir) == ["CrossFeatureEditError"]
    assert _transcript_terminals(plan_dir) == ["blocked"]


def test_item4b_cross_feature_edit_error_announces_blocked_and_propagates(
    repo: Path, captured: list[Any]
) -> None:
    plan_dir = _make_plan(
        repo,
        TOP_ID,
        features=[
            _feature("F001", "Synthetic DP-003 feature."),
            _feature("F002", "Foreign feature that owns src/foreign_module.py."),
        ],
    )
    auditor = _write_envelopes(plan_dir, TOP_ID)
    _git_state(plan_dir, {"staged": [{"path": "src/foreign_module.py"}]})
    loaded = plan_loader.load(plan_dir)

    with pytest.raises(CrossFeatureEditError):
        supervisor._emit_volley_terminal(
            supervisor.VolleyResult("signed_off", 1, "auditor signed off", [auditor]),
            loaded=loaded,
            feature_id="F001",
            agents_in_panel=["claude", "codex"],
            # Isolate the cross-feature gate from the patch gate.
            allow_incomplete_patch_reason="operator accepts patch shape for this test",
        )

    _assert_one_blocked_terminal(plan_dir, captured, "CrossFeatureEditError")


# ───────────────── Sentinel r3b (B) — finalizer fails closed on an unloadable plan ─────────────────


def test_r3b_unloadable_top_level_plan_refused_without_writes(repo: Path) -> None:
    """No ``child_charter:`` line and an unloadable plan: the old regex
    fallback repaired the signoff with no compliance check; now refused with
    ``plan_unloadable`` and nothing is written."""
    plan_dir = _make_plan(repo, TOP_ID)
    _write_envelopes(plan_dir, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    plan_md = plan_dir / "plan.md"
    plan_md.write_text(plan_md.read_text().replace("title: DP-003 signoff integrity synthetic\n", ""))
    assert "child_charter" not in plan_md.read_text()
    with pytest.raises(Exception):
        plan_loader.load(plan_dir)
    _assert_refused(plan_dir, TOP_ID, "plan_unloadable")
    assert not signoff_writer.signoff_path(plan_dir, TOP_ID).exists()


def test_r3b_unloadable_plan_refused_even_with_valid_existing_signoff(repo: Path) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    _write_valid_signoff(plan_dir, TOP_ID, auditor)
    features = plan_dir / "features.json"
    features.write_text(features.read_text().replace('"category": "test",', ""))
    _assert_refused(plan_dir, TOP_ID, "plan_unloadable")


def test_r3b_unloadable_child_plan_refused_without_writes(repo: Path) -> None:
    plan_dir = _make_child(repo, memo_status="satisfied")
    _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    plan_md = plan_dir / "plan.md"
    plan_md.write_text(plan_md.read_text().replace("  kind: implementation\n", "  kind: bogus\n"))
    _assert_refused(plan_dir, CHILD_ID, "plan_unloadable")
    assert not signoff_writer.charter_compliance_path(plan_dir, CHILD_ID).exists()


def test_r3b_noncompliant_child_repair_refused_without_writes(repo: Path) -> None:
    """Repair path: a child with no close-out memo violates its charter, so
    the finalizer refuses instead of writing an unchecked signoff."""
    plan_dir = _make_child(repo, memo_status=None)
    _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _assert_refused(plan_dir, CHILD_ID, "child_charter_violation")
    assert not signoff_writer.signoff_path(plan_dir, CHILD_ID).exists()
    assert not signoff_writer.charter_compliance_path(plan_dir, CHILD_ID).exists()


# ───────────────── Sentinel r3b (A) — pending_stage is the authority ─────────────────


_BOTH_GATES_ID = "2026-11-12-403-infra-dp003i-stage-authority"


def _contradictory_plan(repo: Path) -> Path:
    """Plan declaring pre_impl + pre_merge whose gate-state carries
    contradictory markers: pending_stage ``pre_impl`` but pause_gates
    ``["pre_merge"]`` (a stale write)."""
    plan_dir = _make_plan(repo, _BOTH_GATES_ID)
    plan_md = plan_dir / "plan.md"
    plan_md.write_text(
        plan_md.read_text().replace(
            "human_gates:\n  - pre_merge\n", "human_gates:\n  - pre_impl\n  - pre_merge\n"
        )
    )
    state_path = gate_pause.gate_state_path(plan_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "plan_id": _BOTH_GATES_ID,
        "cleared_gates": [],
        "history": [],
        "paused_at": "2026-11-12T00:00:00Z",
        "pause_gates": ["pre_merge"],
        "pending_stage": "pre_impl",
    }
    state_path.write_text(json.dumps(state, indent=2) + "\n")
    return plan_dir


def _state_bytes(plan_dir: Path) -> bytes:
    return gate_pause.gate_state_path(plan_dir).read_bytes()


def test_r3b_writer_refuses_pre_merge_under_contradictory_markers(repo: Path) -> None:
    plan_dir = _contradictory_plan(repo)
    before = _state_bytes(plan_dir)
    assert gate_pause.is_gate_approval_eligible(plan_dir, "pre_merge") is False
    assert gate_pause.is_gate_currently_pending(plan_dir, "pre_merge") is False
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=_BOTH_GATES_ID) is False
    assert _state_bytes(plan_dir) == before
    # The authoritative stage stays approvable.
    assert gate_pause.is_gate_currently_pending(plan_dir, "pre_impl") is True
    assert gate_pause.approve_gate(plan_dir, "pre_impl", plan_id=_BOTH_GATES_ID) is True
    assert gate_pause.cleared_gates(plan_dir) == ["pre_impl"]


def test_r3b_mcp_preview_and_confirm_refuse_pre_merge_under_contradictory_markers(
    repo: Path,
) -> None:
    from dontpanic_orchestrate import mcp_server

    plan_dir = _contradictory_plan(repo)
    before = _state_bytes(plan_dir)

    preview = mcp_server.dispatch_tool("approve_gate", {"plan": _BOTH_GATES_ID, "gate": "pre_merge"})
    assert preview["dry_run"] is True
    assert preview["intent"]["would_clear"] is False, preview

    confirm = mcp_server.dispatch_tool(
        "approve_gate", {"plan": _BOTH_GATES_ID, "gate": "pre_merge", "confirm": True}
    )
    assert confirm["result"]["changed"] is False, confirm
    assert _state_bytes(plan_dir) == before


def test_r3b_resume_all_clears_only_pending_stage_under_contradictory_markers(
    repo: Path,
) -> None:
    plan_dir = _contradictory_plan(repo)
    newly = gate_pause.resume_all(
        plan_dir, plan_id=_BOTH_GATES_ID, declared_gates=["pre_impl", "pre_merge"]
    )
    assert newly == ["pre_impl"]
    assert gate_pause.cleared_gates(plan_dir) == ["pre_impl"]
    assert not gate_pause.is_gate_cleared(plan_dir, "pre_merge")


def test_r3b_resume_all_still_clears_transient_gates_with_pending_stage(repo: Path) -> None:
    plan_dir = _contradictory_plan(repo)
    state_path = gate_pause.gate_state_path(plan_dir)
    state = json.loads(state_path.read_text())
    state["active_breakers"] = ["breaker:no_progress"]
    state["pause_gates"] = ["pre_merge", "breaker:no_progress"]
    state_path.write_text(json.dumps(state, indent=2) + "\n")

    newly = gate_pause.resume_all(
        plan_dir, plan_id=_BOTH_GATES_ID, declared_gates=["pre_impl", "pre_merge"]
    )
    assert newly == ["pre_impl", "breaker:no_progress"]
    assert gate_pause.active_breakers(plan_dir) == []
    assert not gate_pause.is_gate_cleared(plan_dir, "pre_merge")


@pytest.mark.parametrize(
    "argv",
    [["approve", _BOTH_GATES_ID, "pre_merge"], ["resume", _BOTH_GATES_ID, "--gate", "pre_merge"]],
)
def test_r3b_cli_refuses_pre_merge_under_contradictory_markers(
    repo: Path, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    from dontpanic_orchestrate import cli

    plan_dir = _contradictory_plan(repo)
    before = _state_bytes(plan_dir)
    assert cli.main(argv) == 2
    assert "not currently pending" in capsys.readouterr().err
    assert _state_bytes(plan_dir) == before


@pytest.mark.parametrize(
    "argv",
    [["approve", _BOTH_GATES_ID, "pre_impl"], ["resume", _BOTH_GATES_ID, "--gate", "pre_impl"]],
)
def test_r3b_cli_clears_authoritative_stage_under_contradictory_markers(
    repo: Path, argv: list[str]
) -> None:
    from dontpanic_orchestrate import cli

    plan_dir = _contradictory_plan(repo)
    assert cli.main(argv) == 0
    assert gate_pause.cleared_gates(plan_dir) == ["pre_impl"]
    assert not gate_pause.is_gate_cleared(plan_dir, "pre_merge")


# ═════════════════════ Sentinel 5870049314 (r4) + Thanos correction ═════════════════════


def _side_car(plan_dir: Path, plan_id: str) -> Path:
    return signoff_writer.charter_compliance_path(plan_dir, plan_id)


def _newer(path: Path, than: Path) -> None:
    later = than.stat().st_mtime + 10
    os.utime(path, (later, later))


# ───────── HIGH-1 — side-car bound to iteration, selected audit and charter ─────────


def test_r4_stale_sidecar_from_older_iteration_refused(repo: Path) -> None:
    """An i0 side-car must not authorize the i1 signoff."""
    plan_dir = _make_child(repo, memo_status="satisfied")
    old_auditor = _write_envelopes(plan_dir, CHILD_ID, iteration=0)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _write_valid_signoff(plan_dir, CHILD_ID, old_auditor, iteration=0, child=True)
    old_side_car = _side_car(plan_dir, CHILD_ID).read_bytes()

    new_auditor = _write_envelopes(plan_dir, CHILD_ID, iteration=1)
    _newer(new_auditor, old_auditor)
    _write_valid_signoff(plan_dir, CHILD_ID, new_auditor, iteration=1, child=True)
    _side_car(plan_dir, CHILD_ID).write_bytes(old_side_car)  # stale i0 side-car

    _assert_refused(plan_dir, CHILD_ID, "child_signoff_stale")


def test_r4_sidecar_not_listing_selected_audit_refused(repo: Path) -> None:
    plan_dir = _make_child(repo, memo_status="satisfied")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    side = _side_car(plan_dir, CHILD_ID)
    data = json.loads(side.read_text())
    data["audits"] = ["audit/codex-auditor-F001-i9.json"]
    side.write_text(json.dumps(data, indent=2) + "\n")
    _assert_refused(plan_dir, CHILD_ID, "child_signoff_stale")


def test_r4_sidecar_from_changed_charter_refused(repo: Path) -> None:
    """The charter changed after the side-car was written: digest mismatch."""
    plan_dir = _make_child(repo, memo_status="satisfied")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    plan_md = plan_dir / "plan.md"
    plan_md.write_text(
        plan_md.read_text().replace(
            "return_condition_summary: 'synthetic finding closed'",
            "return_condition_summary: 'a different, widened return condition'",
        )
    )
    plan_loader.load(plan_dir)  # still loadable — only the charter changed
    _assert_refused(plan_dir, CHILD_ID, "child_signoff_stale")


def test_r4_legacy_sidecar_without_binding_refused(repo: Path) -> None:
    plan_dir = _make_child(repo, memo_status="satisfied")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    side = _side_car(plan_dir, CHILD_ID)
    data = json.loads(side.read_text())
    for key in ("iteration", "signoff_id", "audits", "charter_digest"):
        data.pop(key)
    side.write_text(json.dumps(data, indent=2) + "\n")
    _assert_refused(plan_dir, CHILD_ID, "child_signoff_stale")


def test_r4_sidecar_records_binding_fields(repo: Path) -> None:
    from dontpanic_orchestrate import nested_orchestration

    plan_dir = _make_child(repo, memo_status="satisfied")
    auditor = _write_envelopes(plan_dir, CHILD_ID, iteration=2)
    sp = _write_valid_signoff(plan_dir, CHILD_ID, auditor, iteration=2, child=True)
    signoff = json.loads(sp.read_text())
    side = json.loads(_side_car(plan_dir, CHILD_ID).read_text())
    loaded = plan_loader.load(plan_dir)
    assert side["iteration"] == 2 == signoff["iteration"]
    assert side["signoff_id"] == signoff["signoff_id"]
    assert side["audits"] == signoff["audits"]
    assert side["charter_digest"] == nested_orchestration.charter_digest(
        loaded.child_charter, loaded.commit_policy
    )
    assert side["return_condition_status"] == "satisfied"  # recording unchanged


# ───────── HIGH-2 — fail closed on missing / unparseable completed_at ─────────


@pytest.mark.parametrize("completed_at", [None, "", "not-a-timestamp", 12345])
def test_r4_missing_or_unparseable_completed_at_fails_closed(
    repo: Path, completed_at: Any
) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    _write_valid_signoff(plan_dir, TOP_ID, auditor)
    env = json.loads(auditor.read_text())
    if completed_at is None:
        env.pop("completed_at")
    else:
        env["completed_at"] = completed_at
    auditor.write_text(json.dumps(env))
    _assert_refused(plan_dir, TOP_ID, "signoff_stale")


# ───────── Thanos guard — only a satisfied child finalizes ─────────


def test_r4_blocked_child_existing_signoff_not_success(repo: Path) -> None:
    plan_dir = _make_child(repo, memo_status="blocked")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    # Recording is unchanged: the writer still records ``blocked``.
    assert json.loads(_side_car(plan_dir, CHILD_ID).read_text())["return_condition_status"] == "blocked"
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r4_blocked_child_repair_path_not_success_and_writes_nothing(repo: Path) -> None:
    plan_dir = _make_child(repo, memo_status="blocked")
    _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")
    assert not signoff_writer.signoff_path(plan_dir, CHILD_ID).exists()
    assert not _side_car(plan_dir, CHILD_ID).exists()


def test_r4_superseded_child_without_successor_not_success(repo: Path) -> None:
    plan_dir = _make_child(repo, memo_status="superseded")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


_SUCCESSOR_ID = "2026-11-12-404-infra-dp003i-successor"


def _successor(repo: Path, memo_status: str) -> Path:
    """Sibling child of the same parent for the same parent_acceptance_item,
    with a durable signoff + side-car."""
    succ = _make_child(repo, _SUCCESSOR_ID, memo_status=memo_status)
    auditor = _write_envelopes(succ, _SUCCESSOR_ID)
    _write_valid_signoff(succ, _SUCCESSOR_ID, auditor, child=True)
    return succ


def test_r4_superseded_child_with_blocked_successor_not_success(repo: Path) -> None:
    _successor(repo, "blocked")
    plan_dir = _make_child(repo, memo_status="superseded")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r4_superseded_child_with_satisfied_successor_accepted(repo: Path) -> None:
    _successor(repo, "satisfied")
    plan_dir = _make_child(repo, memo_status="superseded")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    sp = _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    before = sp.read_bytes()

    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=CHILD_ID, feature_id="F001")

    assert fin.features_passes_flipped is True
    assert _passes(plan_dir) is True
    assert sp.read_bytes() == before


def test_r4_superseded_child_repair_with_satisfied_successor_accepted(repo: Path) -> None:
    _successor(repo, "satisfied")
    plan_dir = _make_child(repo, memo_status="superseded")
    _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)

    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=CHILD_ID, feature_id="F001")

    assert fin.signoff_repaired is True
    assert _passes(plan_dir) is True


# ───────── r5 — a successor counts only while its LATEST audit backs its signoff ─────────


def _superseded_child_with_signoff(repo: Path) -> Path:
    plan_dir = _make_child(repo, memo_status="superseded")
    auditor = _write_envelopes(plan_dir, CHILD_ID)
    _clear_pre_merge(plan_dir, CHILD_ID)
    _write_valid_signoff(plan_dir, CHILD_ID, auditor, child=True)
    return plan_dir


def _blocked_auditor_envelope(plan_dir: Path, plan_id: str, *, iteration: int, newer_than: Path) -> Path:
    """A later auditor envelope for F001 whose verdict is not signed_off."""
    auditor = _write_envelopes(plan_dir, plan_id, iteration=iteration)
    env = json.loads(auditor.read_text())
    env["audit_status"] = "blocked"
    env["summary"] = "Blocked on a later volley."
    auditor.write_text(json.dumps(env))
    _newer(auditor, newer_than)
    return auditor


def test_r5_stale_successor_after_refused_blocked_rewrite_not_accepted(repo: Path) -> None:
    """Successor (requires tests_pass) signs off satisfied at i0; a later i1
    volley ends blocked and the REAL writer refuses the blocked rewrite
    (ChildCharterViolation), leaving the i0 pair on disk. That stale pair must
    not let a superseded sibling finalize."""
    from dontpanic_orchestrate import nested_orchestration

    succ = _make_child(repo, _SUCCESSOR_ID, memo_status="satisfied")
    plan_md = succ / "plan.md"
    plan_md.write_text(
        plan_md.read_text().replace(
            "links:\n", "commit_policy:\n  mode: evidence_only\n  requires:\n    - tests_pass\nlinks:\n"
        )
    )
    assert plan_loader.load(succ).commit_policy.requires == ["tests_pass"]
    i0 = _write_envelopes(succ, _SUCCESSOR_ID, iteration=0)
    _write_valid_signoff(succ, _SUCCESSOR_ID, i0, iteration=0, child=True)
    i0_signoff = signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_bytes()
    i0_side = _side_car(succ, _SUCCESSOR_ID).read_bytes()

    i1 = _blocked_auditor_envelope(succ, _SUCCESSOR_ID, iteration=1, newer_than=i0)
    (succ / "evidence" / "closeout-memo.md").write_text(
        "# Close-out\n\n## Return Condition\n\nstatus: blocked\n"
    )
    with pytest.raises(nested_orchestration.ChildCharterViolation):
        _write_valid_signoff(succ, _SUCCESSOR_ID, i1, iteration=1, volley_status="blocked", child=True)
    # The writer refused, so the stale i0 success pair is still on disk.
    assert signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_bytes() == i0_signoff
    assert _side_car(succ, _SUCCESSOR_ID).read_bytes() == i0_side

    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r5_successor_whose_latest_audit_is_blocked_not_accepted(repo: Path) -> None:
    """Successor's i0 success pair is untouched, but its latest (i1) auditor
    envelope is blocked: it is not a satisfied successor."""
    succ = _successor(repo, "satisfied")
    i0 = succ / "audit" / "codex-auditor-F001-i0.json"
    _blocked_auditor_envelope(succ, _SUCCESSOR_ID, iteration=1, newer_than=i0)

    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


@pytest.mark.parametrize(
    ("acceptance_item", "accepted"),
    [("parent acceptance #1", True), ("parent acceptance #2", False)],
)
def test_r5_successor_must_share_parent_acceptance_item(
    repo: Path, acceptance_item: str, accepted: bool
) -> None:
    """A fully satisfied, current sibling of the same parent counts as a
    successor only for the SAME parent_acceptance_item (Sentinel L3 / M10)."""
    succ = _make_child(repo, _SUCCESSOR_ID, memo_status="satisfied")
    plan_md = succ / "plan.md"
    plan_md.write_text(
        plan_md.read_text().replace(
            "parent_acceptance_item: 'parent acceptance #1'",
            f"parent_acceptance_item: '{acceptance_item}'",
        )
    )
    assert plan_loader.load(succ).child_charter.parent_acceptance_item == acceptance_item
    auditor = _write_envelopes(succ, _SUCCESSOR_ID)
    _write_valid_signoff(succ, _SUCCESSOR_ID, auditor, child=True)

    plan_dir = _superseded_child_with_signoff(repo)
    if accepted:
        fin = signed_off_finalizer.finalize_signed_off_feature(
            plan_dir, plan_id=CHILD_ID, feature_id="F001"
        )
        assert fin.features_passes_flipped is True
        assert _passes(plan_dir) is True
    else:
        _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


# ───────── r6 — each feature's LATEST auditor envelope backs the successor (per feature;
# the signoff must list its OWN feature's latest — see r7/r8 for the exact rule) ─────────


def _auditor_envelope_for(
    plan_dir: Path,
    plan_id: str,
    fid: str,
    *,
    iteration: int,
    audit_status: str,
    newer_than: Path | None,
    completed_at: dt.datetime | None = None,
    vendor: str = "codex",
) -> Path:
    """An auditor envelope for feature ``fid`` at ``iteration``, made strictly
    newer (mtime) than ``newer_than`` (``None``: natural write mtime, no
    forced ordering). ``completed_at`` defaults to now."""
    auditor = plan_dir / "audit" / f"{vendor}-auditor-{fid}-i{iteration}.json"
    ts = _iso(completed_at or dt.datetime.now(dt.timezone.utc))
    auditor.write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "audit_id": f"{plan_id}#{vendor}#{fid}#{iteration}",
                "agent": vendor,
                "agent_role": "auditor",
                "iteration": iteration,
                "started_at": ts,
                "completed_at": ts,
                "audit_status": audit_status,
                "findings": [],
                "summary": f"{fid} {audit_status}.",
            }
        )
    )
    if newer_than is not None:
        _newer(auditor, newer_than)
    return auditor


def _two_feature_successor(repo: Path) -> tuple[Path, Path]:
    """Satisfied successor with features F001 + F002 and ``requires:
    [tests_pass]``; F001 signed off at i0 (bound pair). Returns
    ``(successor_dir, f001_i0_auditor)``."""
    if not (repo / "docs" / "plans" / PARENT_ID).is_dir():
        _make_plan(repo, PARENT_ID)
    succ = _make_plan(
        repo,
        _SUCCESSOR_ID,
        child=True,
        features=[_feature("F001", "Successor feature one."), _feature("F002", "Successor feature two.")],
    )
    (succ / "evidence").mkdir(parents=True, exist_ok=True)
    (succ / "evidence" / "closeout-memo.md").write_text(
        "# Close-out\n\n## Return Condition\n\nstatus: satisfied\n"
    )
    plan_md = succ / "plan.md"
    plan_md.write_text(
        plan_md.read_text().replace(
            "links:\n", "commit_policy:\n  mode: evidence_only\n  requires:\n    - tests_pass\nlinks:\n"
        )
    )
    loaded = plan_loader.load(succ)
    assert loaded.commit_policy.requires == ["tests_pass"]
    assert [f["id"] for f in json.loads((succ / "features.json").read_text())["features"]] == ["F001", "F002"]
    i0 = _write_envelopes(succ, _SUCCESSOR_ID, iteration=0)
    _write_valid_signoff(succ, _SUCCESSOR_ID, i0, iteration=0, child=True)
    side = json.loads(_side_car(succ, _SUCCESSOR_ID).read_text())
    assert side["return_condition_status"] == "satisfied"
    return succ, i0


def test_r6_sp8_stale_successor_after_newer_blocked_f002_volley_not_accepted(repo: Path) -> None:
    """SP8: successor signs off F001 satisfied at i0; a later, newer F002
    volley ends blocked and the REAL writer refuses the blocked rewrite,
    leaving the F001 pair on disk. The successor's newest audit is blocked, so
    the superseded sibling must not finalize."""
    from dontpanic_orchestrate import nested_orchestration

    succ, i0 = _two_feature_successor(repo)
    i0_signoff = signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_bytes()
    i0_side = _side_car(succ, _SUCCESSOR_ID).read_bytes()

    f002 = _auditor_envelope_for(
        succ, _SUCCESSOR_ID, "F002", iteration=0, audit_status="blocked", newer_than=i0
    )
    with pytest.raises(nested_orchestration.ChildCharterViolation):
        _write_valid_signoff(succ, _SUCCESSOR_ID, f002, iteration=0, volley_status="blocked", child=True)
    # The writer refused, so the stale F001 success pair is still on disk.
    assert signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_bytes() == i0_signoff
    assert _side_car(succ, _SUCCESSOR_ID).read_bytes() == i0_side

    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r6_successor_newest_audit_iteration_mismatch_not_accepted(repo: Path) -> None:
    """Every feature's latest auditor envelope is signed_off and the
    (per-volley, F002) signoff lists its own feature's latest, but that
    envelope's iteration differs from the signoff's: not a successor (only the
    iteration-equality check refuses this)."""
    succ, _i0, f002 = _current_two_feature_successor(repo)
    signoff = json.loads(signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_text())
    assert signoff["iteration"] == 0
    assert [Path(a).name for a in signoff["audits"]] == [f002.name]
    env = json.loads(f002.read_text())
    env["iteration"] = 1
    f002.write_text(json.dumps(env))
    assert env["audit_status"] == "signed_off"

    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r6_successor_newest_audit_not_listed_in_signoff_not_accepted(repo: Path) -> None:
    """The signoff lists F001's i0 auditor envelope, but a LATER (by
    completed_at) signed_off F001 auditor envelope at the same iteration (a
    second auditor vendor) is not listed: the signoff is not backed by its own
    feature's latest audit (only the own-feature listed check refuses this —
    verdict, iteration and every other feature are fine)."""
    succ, i0 = _two_feature_successor(repo)
    t = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    _auditor_envelope_for(
        succ, _SUCCESSOR_ID, "F002", iteration=0, audit_status="signed_off", newer_than=None,
        completed_at=t + dt.timedelta(seconds=30),
    )
    later = _auditor_envelope_for(
        succ, _SUCCESSOR_ID, "F001", iteration=0, audit_status="signed_off", newer_than=None,
        completed_at=t + dt.timedelta(seconds=60), vendor="gemini",
    )
    signoff = json.loads(signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_text())
    assert signoff["iteration"] == 0
    assert any(Path(a).name == i0.name for a in signoff["audits"])
    assert not any(Path(a).name == later.name for a in signoff["audits"])

    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r6_two_feature_successor_current_signoff_accepted(repo: Path) -> None:
    """Positive control: the two-feature successor whose F001 AND F002 latest
    auditor envelopes are signed_off, with per-volley real-writer signoffs
    (F001's, then F002's superseding it — each listing only its own feature),
    is a satisfied successor."""
    _current_two_feature_successor(repo)
    plan_dir = _superseded_child_with_signoff(repo)
    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=CHILD_ID, feature_id="F001")
    assert fin.features_passes_flipped is True
    assert _passes(plan_dir) is True


# ───────── r7 (DPN-010) — per-feature successor currency, deterministic under mtime ties ─────────


def _write_successor_signoff(succ: Path, audit_paths: list[Path], *, iteration: int = 0) -> Path:
    """Real ``signoff_writer.write_signoff`` for the successor listing exactly
    ``audit_paths``."""
    loaded = plan_loader.load(succ)
    return signoff_writer.write_signoff(
        plan_id=_SUCCESSOR_ID,
        tier="trivial",
        iteration=iteration,
        agents_in_panel=["claude", "codex"],
        audit_paths=audit_paths,
        plan_dir=succ,
        volley_status="signed_off",
        child_charter=loaded.child_charter,
        commit_policy=loaded.commit_policy,
    )


def _current_two_feature_successor(repo: Path) -> tuple[Path, Path, Path]:
    """Two-feature successor with F001 AND F002 auditor envelopes signed_off at
    i0 and per-volley real signoffs, exactly as the supervisor writes them:
    F001's volley signoff (listing only F001), then F002's volley signoff
    (listing only F002) superseding it, with its bound side-car. Returns
    ``(successor_dir, f001_auditor, f002_auditor)``."""
    succ, f001 = _two_feature_successor(repo)
    f002 = _auditor_envelope_for(
        succ, _SUCCESSOR_ID, "F002", iteration=0, audit_status="signed_off", newer_than=None
    )
    _write_successor_signoff(succ, [f002])
    signoff = json.loads(signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_text())
    assert [Path(a).name for a in signoff["audits"]] == [f002.name]
    side = json.loads(_side_car(succ, _SUCCESSOR_ID).read_text())
    assert side["return_condition_status"] == "satisfied"
    assert side["signoff_id"] == signoff["signoff_id"]
    return succ, f001, f002


def _sp8_successor(repo: Path, *, force_newer: bool) -> tuple[Path, Path, Path]:
    """SP8 state: F001 signed off satisfied at i0 (bound pair); a later F002
    auditor envelope is blocked and the REAL writer refuses the blocked
    rewrite (ChildCharterViolation), leaving the F001 pair on disk. With
    ``force_newer=False`` the F002 envelope keeps its natural write mtime."""
    from dontpanic_orchestrate import nested_orchestration

    succ, f001 = _two_feature_successor(repo)
    signoff_bytes = signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_bytes()
    side_bytes = _side_car(succ, _SUCCESSOR_ID).read_bytes()
    f002 = _auditor_envelope_for(
        succ,
        _SUCCESSOR_ID,
        "F002",
        iteration=0,
        audit_status="blocked",
        newer_than=f001 if force_newer else None,
    )
    with pytest.raises(nested_orchestration.ChildCharterViolation):
        _write_valid_signoff(succ, _SUCCESSOR_ID, f002, iteration=0, volley_status="blocked", child=True)
    assert signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_bytes() == signoff_bytes
    assert _side_car(succ, _SUCCESSOR_ID).read_bytes() == side_bytes
    return succ, f001, f002


def _equalize_audit_mtimes(plan_dir: Path) -> None:
    """Force the SAME atime/mtime on every audit envelope (as after a clone /
    copy that lands every file in the same timestamp tick)."""
    files = sorted(p for p in (plan_dir / "audit").iterdir() if p.is_file())
    assert files
    stamp = max(p.stat().st_mtime for p in files)
    for p in files:
        os.utime(p, (stamp, stamp))
    assert len({p.stat().st_mtime for p in files}) == 1


def _git(cwd: Path, *args: str) -> None:
    """Hermetic git for fixture repos: no host config, no signing."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_")
    }
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
    )
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
        cwd=str(cwd),
        env=env,
        check=True,
        capture_output=True,
    )


def _real_copy(repo: Path, how: str) -> Path:
    """Copy the fixture repo with a REAL tool (no forced mtimes); returns the
    copy's root."""
    dest = repo.parent / f"copy-{how}"
    if how == "cp_R":
        subprocess.run(["cp", "-R", str(repo), str(dest)], check=True)
    elif how == "git_clone":
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "sp8 state")
        _git(repo.parent, "clone", "-q", str(repo), str(dest))
    else:  # pragma: no cover — guarded by parametrize
        raise AssertionError(how)
    assert (dest / "docs" / "plans" / _SUCCESSOR_ID / "audit" / "codex-auditor-F002-i0.json").is_file()
    return dest


def _sp8_same_feature_successor(repo: Path) -> tuple[Path, Path, Path]:
    """SP8 where the later blocked volley is in the SAME feature as a listed
    signed_off envelope: F001 i0 and F002 i0 signed_off, a real signoff listing
    both at iteration 0; then a later (completed_at) F002 i1 volley ends
    blocked and the REAL writer refuses the blocked rewrite, leaving the
    iteration-0 pair on disk. Returns ``(successor_dir, f002_i0, f002_i1)``."""
    from dontpanic_orchestrate import nested_orchestration

    succ, f001 = _two_feature_successor(repo)
    t = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    f002_i0 = _auditor_envelope_for(
        succ, _SUCCESSOR_ID, "F002", iteration=0, audit_status="signed_off", newer_than=None,
        completed_at=t + dt.timedelta(seconds=30),
    )
    _write_successor_signoff(succ, [f001, f002_i0])
    signoff_bytes = signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_bytes()
    side_bytes = _side_car(succ, _SUCCESSOR_ID).read_bytes()
    f002_i1 = _auditor_envelope_for(
        succ, _SUCCESSOR_ID, "F002", iteration=1, audit_status="blocked", newer_than=None,
        completed_at=t + dt.timedelta(seconds=60),
    )
    with pytest.raises(nested_orchestration.ChildCharterViolation):
        _write_valid_signoff(succ, _SUCCESSOR_ID, f002_i1, iteration=1, volley_status="blocked", child=True)
    assert signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_bytes() == signoff_bytes
    assert _side_car(succ, _SUCCESSOR_ID).read_bytes() == side_bytes
    return succ, f002_i0, f002_i1


@pytest.mark.parametrize("how", ["cp_R", "git_clone"])
def test_r7_sp8_after_real_copy_not_accepted(repo: Path, how: str) -> None:
    """SP8 state (later F002 i1 volley blocked, stale iteration-0 pair on disk)
    copied with a real tool (``cp -R`` / ``git clone``). A copy assigns new,
    tied or reordered mtimes; to make the worst case deterministic on every
    platform, the copied stale signed_off F002 i0 is then given a NEWER mtime
    than the copied blocked F002 i1. Finalizing the superseded child IN THE
    COPY must still refuse: F002's latest audit by completed_at is blocked."""
    _sp8_same_feature_successor(repo)
    _superseded_child_with_signoff(repo)
    copy_root = _real_copy(repo, how)
    audit = copy_root / "docs" / "plans" / _SUCCESSOR_ID / "audit"
    blocked, stale = audit / "codex-auditor-F002-i1.json", audit / "codex-auditor-F002-i0.json"
    _newer(stale, blocked)
    assert stale.stat().st_mtime > blocked.stat().st_mtime
    child_copy = copy_root / "docs" / "plans" / CHILD_ID
    _assert_refused(child_copy, CHILD_ID, "child_not_satisfied")


def test_r7_sp8_equal_mtimes_not_accepted(repo: Path) -> None:
    """SP8 with every successor audit envelope forced to the same atime/mtime:
    the blocked F002 latest audit still disqualifies the successor."""
    succ, _f001, _f002 = _sp8_successor(repo, force_newer=True)
    _equalize_audit_mtimes(succ)
    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r7_sp8_older_f001_touched_after_blocked_f002_not_accepted(repo: Path) -> None:
    """SP8 where the older signed_off F001 file is touched AFTER the blocked
    F002 file (mtime no longer tracks volley order): still refused."""
    succ, f001, f002 = _sp8_successor(repo, force_newer=True)
    _newer(f001, f002)
    assert f001.stat().st_mtime > f002.stat().st_mtime
    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r7_equal_mtimes_f001_higher_iteration_cannot_mask_blocked_f002(repo: Path) -> None:
    """Equal mtimes: a signed_off, listed F001 i2 (higher iteration index) must
    not outrank F002's own latest audit (i0, blocked)."""
    succ, _f001_i0 = _two_feature_successor(repo)
    f001_i2 = _write_envelopes(succ, _SUCCESSOR_ID, iteration=2)
    _write_successor_signoff(succ, [f001_i2], iteration=2)
    _auditor_envelope_for(succ, _SUCCESSOR_ID, "F002", iteration=0, audit_status="blocked", newer_than=None)
    _equalize_audit_mtimes(succ)
    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


@pytest.mark.parametrize("bad_status", ["needs_changes", "blocked"])
def test_r7_successor_feature_latest_audit_not_signed_off_not_accepted(
    repo: Path, bad_status: str
) -> None:
    """Every feature's latest auditor envelope is at the signoff's iteration
    and the signoff lists its own (F002) feature's latest, but F002's verdict
    is not signed_off: refused (only the verdict check refuses this)."""
    succ, _f001, f002 = _current_two_feature_successor(repo)
    env = json.loads(f002.read_text())
    env["audit_status"] = bad_status
    f002.write_text(json.dumps(env))
    signoff = json.loads(signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_text())
    assert env["iteration"] == signoff["iteration"] == 0
    assert any(Path(a).name == f002.name for a in signoff["audits"])

    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


@pytest.mark.parametrize("listed", ["F001", "F002"])
def test_r7_equal_mtimes_own_feature_latest_must_be_listed(repo: Path, listed: str) -> None:
    """Both features' latest audits are signed_off at the signoff's iteration
    and all mtimes are equal, but the signoff lists an OLDER envelope of its
    own feature while a later (completed_at) signed_off envelope of that same
    feature (second auditor vendor, same iteration) is unlisted: refused,
    whichever feature it is (the listed rule does not depend on tie order)."""
    succ, f001, f002 = _current_two_feature_successor(repo)
    only = f001 if listed == "F001" else f002
    _write_successor_signoff(succ, [only])
    signoff = json.loads(signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_text())
    assert [Path(a).name for a in signoff["audits"]] == [only.name]
    _auditor_envelope_for(
        succ, _SUCCESSOR_ID, listed, iteration=0, audit_status="signed_off", newer_than=None,
        completed_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60), vendor="gemini",
    )
    _equalize_audit_mtimes(succ)

    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r7_successor_feature_without_auditor_envelope_not_accepted(repo: Path) -> None:
    """A feature in the successor's features.json with no auditor envelope at
    all: the plan-level signoff is not backed for that feature."""
    _two_feature_successor(repo)  # F001 signed off; F002 never audited
    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r7_two_feature_successor_accepted_with_equal_mtimes(repo: Path) -> None:
    """Tie-stable positive control: the current two-feature successor is still
    accepted when every audit envelope shares one atime/mtime."""
    succ, _f001, _f002 = _current_two_feature_successor(repo)
    _equalize_audit_mtimes(succ)
    plan_dir = _superseded_child_with_signoff(repo)
    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=CHILD_ID, feature_id="F001")
    assert fin.features_passes_flipped is True
    assert _passes(plan_dir) is True


@pytest.mark.parametrize("how", ["cp_R", "git_clone"])
def test_r7_two_feature_successor_accepted_after_real_copy(repo: Path, how: str) -> None:
    """Positive control after a real copy: the current two-feature successor
    still backs the superseded child in the copy."""
    _current_two_feature_successor(repo)
    _superseded_child_with_signoff(repo)
    copy_root = _real_copy(repo, how)
    child_copy = copy_root / "docs" / "plans" / CHILD_ID
    fin = signed_off_finalizer.finalize_signed_off_feature(child_copy, plan_id=CHILD_ID, feature_id="F001")
    assert fin.features_passes_flipped is True
    assert _passes(child_copy) is True


# ───────── r8 (DPN-010 r2) — own-feature listing; latest by completed_at, never mtime ─────────

_REAL_CHILD_PLAN = HERE.parents[3] / "docs" / "plans" / "2026-05-19-003-fix-plan-schema-orchestration-fields"
_TESTS_PASS_POLICY = "commit_policy:\n  mode: evidence_only\n  requires:\n    - tests_pass\nlinks:\n"


def _base_time() -> dt.datetime:
    """Base completed_at for scripted volleys, far enough in the PAST that
    every offset volley (up to +100s) completed before the real writer stamps
    ``decided_at`` (DPN-011: a signoff must not predate its listed envelope)."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(seconds=600)


def _child_successor(repo: Path, features: list[dict[str, Any]]) -> Path:
    """Satisfied-memo successor child (same parent + acceptance item) with
    ``requires: [tests_pass]`` and the given features; no audits yet."""
    if not (repo / "docs" / "plans" / PARENT_ID).is_dir():
        _make_plan(repo, PARENT_ID)
    succ = _make_plan(repo, _SUCCESSOR_ID, child=True, features=features)
    (succ / "evidence").mkdir(parents=True, exist_ok=True)
    (succ / "evidence" / "closeout-memo.md").write_text(
        "# Close-out\n\n## Return Condition\n\nstatus: satisfied\n"
    )
    plan_md = succ / "plan.md"
    plan_md.write_text(plan_md.read_text().replace("links:\n", _TESTS_PASS_POLICY))
    assert plan_loader.load(succ).commit_policy.requires == ["tests_pass"]
    return succ


def _volley(
    succ: Path, fid: str, iteration: int, audit_status: str, completed_at: dt.datetime
) -> tuple[Path, Path]:
    """One volley's implementer + auditor envelopes for ``fid`` (natural
    mtimes). Returns ``(implementer, auditor)``."""
    impl = succ / "audit" / f"claude-implementer-{fid}-i{iteration}.json"
    impl.parent.mkdir(parents=True, exist_ok=True)
    impl.write_text(json.dumps({"agent": "claude", "agent_role": "implementer", "iteration": iteration}))
    aud = _auditor_envelope_for(
        succ, _SUCCESSOR_ID, fid, iteration=iteration, audit_status=audit_status,
        newer_than=None, completed_at=completed_at,
    )
    return impl, aud


def _real_shape_features() -> list[dict[str, Any]]:
    """The feature list of a committed multi-feature child plan (3 features),
    reset to un-passed so the successor's own ``passes`` state is neutral."""
    data = json.loads((_REAL_CHILD_PLAN / "features.json").read_text())
    feats = []
    for f in data["features"]:
        feats.append(
            {
                **{k: f[k] for k in ("id", "category", "phase", "description", "steps", "acceptance", "depends_on")},
                "passes": False,
            }
        )
    assert [f["id"] for f in feats] == ["F001", "F002", "F003"]
    return feats


def _real_shape_successor(repo: Path, *, audit_f003: bool) -> Path:
    """Successor mirroring a committed 3-feature child plan, whose signoffs
    come ONLY from the real writer with per-volley, single-feature
    ``audit_paths`` (each volley's signoff lists only its own feature's
    envelopes and supersedes the previous one): F001 converges at i0, F002 at
    i2 (i0/i1 needs_changes), F003 at i0 (skipped when ``audit_f003`` is
    False — a later feature not audited yet)."""
    succ = _child_successor(repo, _real_shape_features())
    t = _base_time()
    f001 = _volley(succ, "F001", 0, "signed_off", t)
    _write_successor_signoff(succ, list(f001), iteration=0)
    f002: list[Path] = []
    for i, status in enumerate(["needs_changes", "needs_changes", "signed_off"]):
        f002.extend(_volley(succ, "F002", i, status, t + dt.timedelta(seconds=10 * (i + 1))))
    _write_successor_signoff(succ, f002, iteration=2)
    if audit_f003:
        f003 = _volley(succ, "F003", 0, "signed_off", t + dt.timedelta(seconds=60))
        _write_successor_signoff(succ, list(f003), iteration=0)
    signoff = json.loads(signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_text())
    listed_features = {Path(a).name.split("-")[2] for a in signoff["audits"]}
    assert listed_features == ({"F003"} if audit_f003 else {"F002"})
    side = json.loads(_side_car(succ, _SUCCESSOR_ID).read_text())
    assert side["return_condition_status"] == "satisfied"
    assert side["signoff_id"] == signoff["signoff_id"]
    return succ


def test_r8_real_shape_multi_feature_per_volley_successor_accepted(repo: Path) -> None:
    """A real 3-feature child-plan shape with per-volley single-feature
    signoffs: every feature's latest auditor envelope is signed_off and the
    final (F003) signoff lists F003's latest at its iteration, so the
    superseded sibling finalizes SUCCESS and ``passes`` flips."""
    _real_shape_successor(repo, audit_f003=True)
    plan_dir = _superseded_child_with_signoff(repo)
    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=CHILD_ID, feature_id="F001")
    assert fin.features_passes_flipped is True
    assert _passes(plan_dir) is True


def test_r8_real_shape_successor_with_unaudited_later_feature_refused(repo: Path) -> None:
    """Same real shape, but F003 has not been audited yet: refused."""
    _real_shape_successor(repo, audit_f003=False)
    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def _stale_single_feature_successor(repo: Path) -> tuple[Path, Path, Path]:
    """Acceptance 8 base state: single-feature successor (``requires:
    [tests_pass]``); i0 signed_off and listed by a real signoff; a LATER (by
    completed_at) i1 volley ends blocked and the REAL writer refuses the
    blocked rewrite, leaving the i0 pair on disk. Returns
    ``(successor_dir, i0_auditor, i1_auditor)``."""
    from dontpanic_orchestrate import nested_orchestration

    succ = _child_successor(repo, [_feature("F001", "Successor feature one.")])
    t = _base_time()
    i0 = _volley(succ, "F001", 0, "signed_off", t)
    _write_successor_signoff(succ, list(i0), iteration=0)
    signoff_bytes = signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_bytes()
    side_bytes = _side_car(succ, _SUCCESSOR_ID).read_bytes()
    i1 = _volley(succ, "F001", 1, "blocked", t + dt.timedelta(seconds=60))
    (succ / "evidence" / "closeout-memo.md").write_text(
        "# Close-out\n\n## Return Condition\n\nstatus: blocked\n"
    )
    with pytest.raises(nested_orchestration.ChildCharterViolation):
        _write_valid_signoff(succ, _SUCCESSOR_ID, i1[1], iteration=1, volley_status="blocked", child=True)
    assert signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_bytes() == signoff_bytes
    assert _side_car(succ, _SUCCESSOR_ID).read_bytes() == side_bytes
    return succ, i0[1], i1[1]


def test_r8_touched_older_signed_off_i0_refused(repo: Path) -> None:
    """Touching the stale signed_off i0 (newer mtime than the blocked i1) must
    not make it the latest."""
    _succ, i0, i1 = _stale_single_feature_successor(repo)
    _newer(i0, i1)
    assert i0.stat().st_mtime > i1.stat().st_mtime
    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r8_same_bytes_rewrite_of_i0_after_i1_refused(repo: Path) -> None:
    """Rewriting i0 with the SAME bytes after i1 (a real write, newer mtime)
    must not make the stale signed_off i0 the latest."""
    _succ, i0, i1 = _stale_single_feature_successor(repo)
    old = i1.stat().st_mtime - 1000
    os.utime(i0, (old, old))
    os.utime(i1, (old + 100, old + 100))
    i0.write_bytes(i0.read_bytes())
    assert i0.stat().st_mtime > i1.stat().st_mtime
    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r8_branch_switch_mtime_inversion_refused(repo: Path) -> None:
    """Hermetic fixture git repo: commit the stale state on ``main``, make a
    branch that differs ONLY in i0, then switch back with a real ``git
    checkout`` that rewrites only i0 (newer mtime). The older signoff must not
    beat the later blocked audit."""
    _succ, i0, i1 = _stale_single_feature_successor(repo)
    main_i0 = i0.read_bytes()
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "stale successor state")
    _git(repo, "checkout", "-q", "-b", "alt")
    env = json.loads(main_i0)
    env["summary"] = "Alternate branch wording."
    i0.write_text(json.dumps(env))
    _git(repo, "commit", "-q", "-am", "alt: i0 only")
    old = i1.stat().st_mtime - 1000
    os.utime(i0, (old, old))
    os.utime(i1, (old + 100, old + 100))
    _git(repo, "checkout", "-q", "main")
    assert i0.read_bytes() == main_i0
    assert i0.stat().st_mtime > i1.stat().st_mtime
    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


@pytest.mark.parametrize("which", ["older_i0", "listed_i1"])
@pytest.mark.parametrize("bad", ["missing", "not-a-timestamp"])
def test_r8_missing_or_unparseable_completed_at_refused(repo: Path, which: str, bad: str) -> None:
    """Otherwise-current successor (i0 signed_off, later i1 signed_off listed
    at iteration 1); a missing or unparseable ``completed_at`` on ANY of the
    feature's auditor envelopes disqualifies it (fail closed)."""
    succ = _child_successor(repo, [_feature("F001", "Successor feature one.")])
    t = _base_time()
    i0 = _volley(succ, "F001", 0, "signed_off", t)
    i1 = _volley(succ, "F001", 1, "signed_off", t + dt.timedelta(seconds=60))
    _write_successor_signoff(succ, [*i0, *i1], iteration=1)
    target = i0[1] if which == "older_i0" else i1[1]
    env = json.loads(target.read_text())
    if bad == "missing":
        env.pop("completed_at")
    else:
        env["completed_at"] = bad
    target.write_text(json.dumps(env))
    # Keep file timestamps in volley order (i1 newer) so only completed_at matters.
    old = i1[1].stat().st_mtime - 1000
    os.utime(i0[1], (old, old))
    os.utime(i1[1], (old + 100, old + 100))
    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r8_redispatch_later_blocked_i0_beats_older_signed_off_i2_refused(repo: Path) -> None:
    """Redispatch reuses iteration filenames: i2 signed_off (listed, signoff
    iteration 2), then a LATER (completed_at) redispatched i0 ends blocked and
    the real writer refuses the blocked rewrite. With equal mtimes, the higher
    iteration index must not outrank the later completed_at: refused."""
    from dontpanic_orchestrate import nested_orchestration

    succ = _child_successor(repo, [_feature("F001", "Successor feature one.")])
    t = _base_time()
    paths: list[Path] = []
    for i, status in enumerate(["needs_changes", "needs_changes", "signed_off"]):
        paths.extend(_volley(succ, "F001", i, status, t + dt.timedelta(seconds=10 * i)))
    _write_successor_signoff(succ, paths, iteration=2)
    _impl, i0 = _volley(succ, "F001", 0, "blocked", t + dt.timedelta(seconds=100))
    (succ / "evidence" / "closeout-memo.md").write_text(
        "# Close-out\n\n## Return Condition\n\nstatus: blocked\n"
    )
    with pytest.raises(nested_orchestration.ChildCharterViolation):
        _write_valid_signoff(succ, _SUCCESSOR_ID, i0, iteration=0, volley_status="blocked", child=True)
    _equalize_audit_mtimes(succ)
    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def test_r8_redispatch_later_signed_off_i0_beats_stale_i2_accepted(repo: Path) -> None:
    """Positive redispatch control: a stale needs_changes i2 from an earlier
    run and a LATER (completed_at) redispatched i0 signed_off, listed by the
    real signoff at iteration 0. With equal mtimes the later i0 is the latest:
    the superseded sibling finalizes."""
    succ = _child_successor(repo, [_feature("F001", "Successor feature one.")])
    t = _base_time()
    _volley(succ, "F001", 2, "needs_changes", t)
    i0 = _volley(succ, "F001", 0, "signed_off", t + dt.timedelta(seconds=100))
    _write_successor_signoff(succ, list(i0), iteration=0)
    _equalize_audit_mtimes(succ)
    plan_dir = _superseded_child_with_signoff(repo)
    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=CHILD_ID, feature_id="F001")
    assert fin.features_passes_flipped is True
    assert _passes(plan_dir) is True


# ───────── r9 (DPN-011) — successor freshness, digest binding, newest tie, zone-less timestamps ─────────


def _sha256(path: Path) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _signoff_json(succ: Path) -> dict[str, Any]:
    return json.loads(signoff_writer.signoff_path(succ, _SUCCESSOR_ID).read_text())


def _rewrite_signoff(succ: Path, data: dict[str, Any]) -> None:
    signoff_writer.signoff_path(succ, _SUCCESSOR_ID).write_text(json.dumps(data, indent=2) + "\n")


def _set_completed_at(path: Path, value: Any) -> None:
    env = json.loads(path.read_text())
    env["completed_at"] = value
    env["started_at"] = value
    path.write_text(json.dumps(env))


def _signed_single_feature_successor(
    repo: Path, *, completed_at: dt.datetime | None = None
) -> tuple[Path, Path]:
    """Single-feature successor: F001 i0 signed_off (``completed_at`` defaults
    to a minute in the past) and a REAL-writer signoff listing that volley at
    iteration 0. Returns ``(successor_dir, i0_auditor)``."""
    succ = _child_successor(repo, [_feature("F001", "Successor feature one.")])
    when = completed_at or (dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(seconds=60))
    i0 = _volley(succ, "F001", 0, "signed_off", when)
    _write_successor_signoff(succ, list(i0), iteration=0)
    return succ, i0[1]


def _overwrite_in_place(auditor: Path, completed_at: str, *, tag: str) -> None:
    """Redispatch overwrite of the SAME ``-iN`` auditor path: a different
    ``signed_off`` envelope (new audit_id/summary/findings) at ``completed_at``."""
    env = json.loads(auditor.read_text())
    env.update(
        {
            "audit_id": f"{env['audit_id']}#redispatch-{tag}",
            "started_at": completed_at,
            "completed_at": completed_at,
            "audit_status": "signed_off",
            "summary": f"Redispatched verdict ({tag}).",
            "findings": [{"severity": "low", "summary": f"redispatch {tag}"}],
        }
    )
    auditor.write_text(json.dumps(env))


def _overwrite_with_failed_signoff_rewrite(
    succ: Path, auditor: Path, completed_at: str, monkeypatch: pytest.MonkeyPatch, *, tag: str
) -> None:
    """Overwrite ``auditor`` in place, then make the real writer's rewrite of
    the signoff fail (injected ENOSPC on the signoff file) so the OLD signoff +
    side-car pair stays on disk unchanged."""
    sp = signoff_writer.signoff_path(succ, _SUCCESSOR_ID)
    before_signoff, before_side = sp.read_bytes(), _side_car(succ, _SUCCESSOR_ID).read_bytes()
    _overwrite_in_place(auditor, completed_at, tag=tag)
    with monkeypatch.context() as m:
        _fail_writes_to(m, sp)
        with pytest.raises(OSError):
            _write_successor_signoff(succ, [succ / "audit" / "claude-implementer-F001-i0.json", auditor])
    assert sp.read_bytes() == before_signoff
    assert _side_car(succ, _SUCCESSOR_ID).read_bytes() == before_side


def _assert_superseded_sibling_finalizes(repo: Path) -> None:
    plan_dir = _superseded_child_with_signoff(repo)
    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=CHILD_ID, feature_id="F001")
    assert fin.features_passes_flipped is True
    assert _passes(plan_dir) is True


def _assert_superseded_sibling_refused(repo: Path) -> None:
    plan_dir = _superseded_child_with_signoff(repo)
    _assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


# ── (1) freshness: decided_at must not predate the listed latest envelope ──


def test_r9_redispatch_overwrite_later_than_signoff_refused(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """i0 signed off and listed; a redispatch overwrites the SAME i0 path with
    a signed_off envelope completed AFTER the signoff's decided_at and the
    signoff rewrite fails, leaving the old signoff: not a successor."""
    succ, i0 = _signed_single_feature_successor(repo)
    decided = signed_off_finalizer._parse_iso(_signoff_json(succ)["decided_at"])
    assert decided is not None
    later = _iso(decided + dt.timedelta(seconds=60))
    _overwrite_with_failed_signoff_rewrite(succ, i0, later, monkeypatch, tag="later")
    assert json.loads(i0.read_text())["completed_at"] == later
    _assert_superseded_sibling_refused(repo)


def test_r9_successor_signoff_predating_listed_envelope_refused(repo: Path) -> None:
    """Digest-bound (nothing overwritten) but the listed latest envelope's
    completed_at is later than the signoff's decided_at (the real writer ran
    while the envelope was stamped in the future): the freshness rule alone
    refuses it."""
    future = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(seconds=120)
    succ, i0 = _signed_single_feature_successor(repo, completed_at=future)
    signoff = _signoff_json(succ)
    decided = signed_off_finalizer._parse_iso(signoff["decided_at"])
    assert decided is not None and decided < future
    assert json.loads(i0.read_text())["completed_at"] == _iso(future)  # never overwritten
    _assert_superseded_sibling_refused(repo)


@pytest.mark.parametrize("bad", ["missing", "", "not-a-timestamp", 12345])
def test_r9_successor_missing_or_unparseable_decided_at_refused(repo: Path, bad: Any) -> None:
    succ, _i0 = _signed_single_feature_successor(repo)
    signoff = _signoff_json(succ)
    if bad == "missing":
        signoff.pop("decided_at")
    else:
        signoff["decided_at"] = bad
    _rewrite_signoff(succ, signoff)
    _assert_superseded_sibling_refused(repo)


# ── (1b) digest binding: an in-place overwrite in the SAME second is caught ──


def test_r9_same_second_same_path_overwrite_refused(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As above, but the overwriting envelope's completed_at is the SAME second
    as the signoff's decided_at (so ``decided < completed`` cannot see it) and
    its bytes differ while it is still signed_off: refused by the digest."""
    succ, i0 = _signed_single_feature_successor(repo)
    signoff = _signoff_json(succ)
    before = _sha256(i0)
    _overwrite_with_failed_signoff_rewrite(succ, i0, signoff["decided_at"], monkeypatch, tag="same-second")
    env = json.loads(i0.read_text())
    assert env["completed_at"] == signoff["decided_at"]
    assert env["audit_status"] == "signed_off"
    assert _sha256(i0) != before
    _assert_superseded_sibling_refused(repo)


def test_r9_legacy_successor_signoff_without_audit_digests_refused(repo: Path) -> None:
    succ, _i0 = _signed_single_feature_successor(repo)
    signoff = _signoff_json(succ)
    signoff.pop("audit_digests")
    _rewrite_signoff(succ, signoff)
    _assert_superseded_sibling_refused(repo)


@pytest.mark.parametrize(
    "tamper",
    ["wrong_hex", "no_prefix", "not_a_string", "null", "entry_missing", "not_a_mapping"],
)
def test_r9_successor_tampered_or_malformed_digest_refused(repo: Path, tamper: str) -> None:
    succ, i0 = _signed_single_feature_successor(repo)
    signoff = _signoff_json(succ)
    key = "audit/" + i0.name
    good = signoff["audit_digests"][key]
    assert good == _sha256(i0)
    if tamper == "wrong_hex":
        signoff["audit_digests"][key] = "sha256:" + "0" * 64
    elif tamper == "no_prefix":
        signoff["audit_digests"][key] = good.removeprefix("sha256:")
    elif tamper == "not_a_string":
        signoff["audit_digests"][key] = 12345
    elif tamper == "null":
        signoff["audit_digests"][key] = None
    elif tamper == "entry_missing":
        signoff["audit_digests"].pop(key)
    else:
        signoff["audit_digests"] = [good]
    _rewrite_signoff(succ, signoff)
    _assert_superseded_sibling_refused(repo)


def test_r9_real_writer_successor_with_digests_accepted(repo: Path) -> None:
    """Positive control: a legitimate per-volley successor written by the real
    writer records a sha256 digest for every listed audit and backs the
    superseded sibling, which finalizes SUCCESS."""
    succ, i0 = _signed_single_feature_successor(repo)
    signoff = _signoff_json(succ)
    impl = succ / "audit" / "claude-implementer-F001-i0.json"
    assert signoff["audit_digests"] == {
        "audit/" + impl.name: _sha256(impl),
        "audit/" + i0.name: _sha256(i0),
    }
    assert sorted(signoff["audit_digests"]) == sorted(signoff["audits"])
    _assert_superseded_sibling_finalizes(repo)


def test_r9_ordinary_finalize_accepts_signoff_carrying_audit_digests(repo: Path) -> None:
    """The ordinary (non-successor) finalize of an existing real-writer signoff
    that carries ``audit_digests`` still succeeds without clobbering it."""
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    sp = _write_valid_signoff(plan_dir, TOP_ID, auditor)
    assert json.loads(sp.read_text())["audit_digests"]["audit/" + auditor.name] == _sha256(auditor)
    before = sp.read_bytes()
    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=TOP_ID, feature_id="F001")
    assert fin.features_passes_flipped is True
    assert fin.signoff_repaired is False
    assert sp.read_bytes() == before


def test_r9_plan_validator_accepts_signoff_carrying_audit_digests(repo: Path) -> None:
    """``claude/shared/schemas/v1.0/validate.py`` (doctor / CI / plan-lock)
    schema-checks every ``audit/signoff*.json``; a real-writer signoff that
    carries ``audit_digests`` still validates there."""
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID)
    sp = _write_valid_signoff(plan_dir, TOP_ID, auditor)
    assert "audit_digests" in json.loads(sp.read_text())
    validator = HERE.parents[3] / "claude" / "shared" / "schemas" / "v1.0" / "validate.py"
    out = subprocess.run(
        [sys.executable, str(validator), str(plan_dir)], capture_output=True, text=True, check=False
    ).stdout
    assert f"✓ audit/{sp.name}" in out, out


def test_r9_repair_path_writes_audit_digests(repo: Path) -> None:
    """The finalizer's repair path goes through the real writer and so records
    digests too (and the repaired signoff then validates)."""
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=TOP_ID, feature_id="F001")
    assert fin.signoff_repaired is True
    data = json.loads(fin.signoff_path.read_text())
    assert data["audit_digests"]["audit/" + auditor.name] == _sha256(auditor)


# ── (2) newest-tie fail-closed ──


def test_r9_newest_completed_at_tie_refused(repo: Path) -> None:
    """i2 signed_off (listed, signoff iteration 2), then a redispatched i0
    ends blocked with the SAME completed_at second as i2 and the real writer
    refuses the blocked rewrite. Iteration/name must not break the newest tie:
    the latest cannot be determined, refused."""
    from dontpanic_orchestrate import nested_orchestration

    succ = _child_successor(repo, [_feature("F001", "Successor feature one.")])
    t = _base_time() - dt.timedelta(seconds=120)
    paths: list[Path] = []
    for i, status in enumerate(["needs_changes", "needs_changes", "signed_off"]):
        paths.extend(_volley(succ, "F001", i, status, t + dt.timedelta(seconds=10 * i)))
    _write_successor_signoff(succ, paths, iteration=2)
    i2 = paths[-1]
    _impl, i0 = _volley(succ, "F001", 0, "blocked", t + dt.timedelta(seconds=20))
    assert json.loads(i0.read_text())["completed_at"] == json.loads(i2.read_text())["completed_at"]
    (succ / "evidence" / "closeout-memo.md").write_text(
        "# Close-out\n\n## Return Condition\n\nstatus: blocked\n"
    )
    with pytest.raises(nested_orchestration.ChildCharterViolation):
        _write_valid_signoff(succ, _SUCCESSOR_ID, i0, iteration=0, volley_status="blocked", child=True)
    _assert_superseded_sibling_refused(repo)


def test_r9_older_completed_at_tie_with_unique_newest_accepted(repo: Path) -> None:
    """Older-tie control: i0 and i1 (needs_changes) share one completed_at
    second, but the newest (i2 signed_off, listed, fresh, digest-bound) is
    unique: accepted."""
    succ = _child_successor(repo, [_feature("F001", "Successor feature one.")])
    t = _base_time() - dt.timedelta(seconds=120)
    paths: list[Path] = []
    for i, (status, offset) in enumerate([("needs_changes", 0), ("needs_changes", 0), ("signed_off", 20)]):
        paths.extend(_volley(succ, "F001", i, status, t + dt.timedelta(seconds=offset)))
    stamps = [json.loads(p.read_text())["completed_at"] for p in paths[1::2]]
    assert stamps[0] == stamps[1] != stamps[2]
    _write_successor_signoff(succ, paths, iteration=2)
    _assert_superseded_sibling_finalizes(repo)


# ── (3) zone-less / date-only timestamps are refused ──


@pytest.mark.parametrize(
    ("value", "aware"),
    [
        ("2026-05-23T01:50:14Z", True),
        ("2026-05-23T01:50:14+00:00", True),
        ("2026-05-23T01:50:14-05:00", True),
        ("2026-05-23T01:50:14", False),
        ("2026-05-23", False),
        ("2026-05-23 01:50:14", False),
    ],
)
def test_r9_parse_iso_requires_explicit_offset(value: str, aware: bool) -> None:
    parsed = signed_off_finalizer._parse_iso(value)
    if aware:
        assert parsed is not None and parsed.utcoffset() is not None
    else:
        assert parsed is None


def test_r9_parse_iso_offset_is_honoured() -> None:
    assert signed_off_finalizer._parse_iso("2026-05-23T01:50:14-05:00") == dt.datetime(
        2026, 5, 23, 6, 50, 14, tzinfo=dt.timezone.utc
    )


def _past_naive(seconds: int = 300) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(seconds=seconds)


@pytest.mark.parametrize("form", ["naive", "date_only"])
def test_r9_successor_zone_less_completed_at_refused(repo: Path, form: str) -> None:
    """The listed latest envelope's completed_at has no offset (naive date-time
    or date only), the signoff is written AFTER by the real writer (digests
    match): refused, never read as UTC."""
    succ = _child_successor(repo, [_feature("F001", "Successor feature one.")])
    when = _past_naive()
    impl, aud = _volley(succ, "F001", 0, "signed_off", when)
    value = when.strftime("%Y-%m-%dT%H:%M:%S") if form == "naive" else (when - dt.timedelta(days=1)).date().isoformat()
    _set_completed_at(aud, value)
    _write_successor_signoff(succ, [impl, aud], iteration=0)
    assert json.loads(aud.read_text())["completed_at"] == value  # signed after; not overwritten
    _assert_superseded_sibling_refused(repo)


def test_r9_successor_naive_decided_at_refused(repo: Path) -> None:
    succ, _i0 = _signed_single_feature_successor(repo)
    signoff = _signoff_json(succ)
    signoff["decided_at"] = signoff["decided_at"].removesuffix("Z")
    assert "Z" not in signoff["decided_at"] and "+" not in signoff["decided_at"]
    _rewrite_signoff(succ, signoff)
    _assert_superseded_sibling_refused(repo)


@pytest.mark.parametrize("form", ["naive", "date_only"])
def test_r9_ordinary_zone_less_completed_at_signoff_stale(repo: Path, form: str) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    when = _past_naive()
    auditor = _write_envelopes(plan_dir, TOP_ID, completed_at=when)
    _set_completed_at(
        auditor,
        when.strftime("%Y-%m-%dT%H:%M:%S") if form == "naive" else (when - dt.timedelta(days=1)).date().isoformat(),
    )
    _clear_pre_merge(plan_dir, TOP_ID)
    _write_valid_signoff(plan_dir, TOP_ID, auditor)
    _assert_refused(plan_dir, TOP_ID, "signoff_stale")


def test_r9_ordinary_naive_decided_at_refused(repo: Path) -> None:
    """Ordinary path: a naive ``decided_at`` never reaches the freshness rule
    -- the vendored Signoff schema (``decided_at: AwareDatetime``) already
    refuses it as ``signoff_unreadable`` (unchanged; the check order is kept)."""
    plan_dir = _make_plan(repo, TOP_ID)
    auditor = _write_envelopes(plan_dir, TOP_ID, completed_at=_past_naive())
    _clear_pre_merge(plan_dir, TOP_ID)
    sp = _write_valid_signoff(plan_dir, TOP_ID, auditor)
    data = json.loads(sp.read_text())
    data["decided_at"] = data["decided_at"].removesuffix("Z")
    sp.write_text(json.dumps(data, indent=2) + "\n")
    _assert_refused(plan_dir, TOP_ID, "signoff_unreadable")


# ───────── HIGH-3 — transactional overwrite of an existing signoff/side-car pair ─────────


def _tmp_files(plan_dir: Path) -> list[str]:
    return [p.name for p in (plan_dir / "audit").iterdir() if p.name.endswith(".tmp")]


def test_r4_failed_overwrite_of_existing_pair_restores_previous_pair(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _make_child(repo, memo_status="satisfied")
    old_auditor = _write_envelopes(plan_dir, CHILD_ID, iteration=0)
    _clear_pre_merge(plan_dir, CHILD_ID)
    sp = _write_valid_signoff(plan_dir, CHILD_ID, old_auditor, iteration=0, child=True)
    side = _side_car(plan_dir, CHILD_ID)
    old_signoff, old_side = sp.read_bytes(), side.read_bytes()

    from dontpanic_orchestrate import nested_orchestration

    new_auditor = _write_envelopes(plan_dir, CHILD_ID, iteration=1)
    _newer(new_auditor, old_auditor)
    # The replacement is computed at a later clock tick, so a clobbered
    # side-car is observable even where it carries no iteration.
    monkeypatch.setattr(nested_orchestration, "_now_iso", lambda: "2099-01-01T00:00:00Z")
    _fail_writes_to(monkeypatch, sp)  # replacement signoff write fails

    with pytest.raises(OSError):
        _write_valid_signoff(plan_dir, CHILD_ID, new_auditor, iteration=1, child=True)

    # All-or-nothing: the previous consistent pair is intact (no new side-car
    # paired with the old signoff), and no temp files remain.
    assert sp.read_bytes() == old_signoff
    assert side.read_bytes() == old_side
    assert _tmp_files(plan_dir) == []
    # The leftover old signoff is never accepted as the i1 signoff.
    monkeypatch.undo()
    _assert_refused(plan_dir, CHILD_ID, "signoff_stale")


def test_r4_failed_sidecar_overwrite_of_existing_pair_restores_previous_pair(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _make_child(repo, memo_status="satisfied")
    old_auditor = _write_envelopes(plan_dir, CHILD_ID, iteration=0)
    sp = _write_valid_signoff(plan_dir, CHILD_ID, old_auditor, iteration=0, child=True)
    side = _side_car(plan_dir, CHILD_ID)
    old_signoff, old_side = sp.read_bytes(), side.read_bytes()
    new_auditor = _write_envelopes(plan_dir, CHILD_ID, iteration=1)
    _fail_writes_to(monkeypatch, side)

    with pytest.raises(OSError):
        _write_valid_signoff(plan_dir, CHILD_ID, new_auditor, iteration=1, child=True)

    assert sp.read_bytes() == old_signoff
    assert side.read_bytes() == old_side
    assert _tmp_files(plan_dir) == []


# ───────── MED-2 — present but invalid pending_stage fails closed ─────────


def _garbage_stage_plan(repo: Path) -> Path:
    plan_dir = _contradictory_plan(repo)
    state_path = gate_pause.gate_state_path(plan_dir)
    state = json.loads(state_path.read_text())
    state["pending_stage"] = "garbage"
    state["pause_gates"] = ["pre_merge"]
    state_path.write_text(json.dumps(state, indent=2) + "\n")
    return plan_dir


def test_r4_invalid_pending_stage_blocks_lifecycle_approval_in_shared_writer(repo: Path) -> None:
    plan_dir = _garbage_stage_plan(repo)
    before = _state_bytes(plan_dir)
    for gate in ("pre_merge", "pre_impl"):
        assert gate_pause.is_gate_approval_eligible(plan_dir, gate) is False, gate
        assert gate_pause.is_gate_currently_pending(plan_dir, gate) is False, gate
        assert gate_pause.approve_gate(plan_dir, gate, plan_id=_BOTH_GATES_ID) is False, gate
    assert _state_bytes(plan_dir) == before
    assert gate_pause.cleared_gates(plan_dir) == []


def test_r4_invalid_pending_stage_mcp_preview_and_confirm_refuse_pre_merge(repo: Path) -> None:
    from dontpanic_orchestrate import mcp_server

    plan_dir = _garbage_stage_plan(repo)
    before = _state_bytes(plan_dir)
    preview = mcp_server.dispatch_tool("approve_gate", {"plan": _BOTH_GATES_ID, "gate": "pre_merge"})
    assert preview["intent"]["would_clear"] is False, preview
    confirm = mcp_server.dispatch_tool(
        "approve_gate", {"plan": _BOTH_GATES_ID, "gate": "pre_merge", "confirm": True}
    )
    assert confirm["result"]["changed"] is False, confirm
    assert _state_bytes(plan_dir) == before


def test_r4_invalid_pending_stage_resume_all_does_not_clear_lifecycle_gates(repo: Path) -> None:
    plan_dir = _garbage_stage_plan(repo)
    state_path = gate_pause.gate_state_path(plan_dir)
    state = json.loads(state_path.read_text())
    state["active_breakers"] = ["breaker:no_progress"]
    state["pause_gates"] = ["pre_merge", "pre_impl", "breaker:no_progress"]
    state_path.write_text(json.dumps(state, indent=2) + "\n")

    newly = gate_pause.resume_all(
        plan_dir, plan_id=_BOTH_GATES_ID, declared_gates=["pre_impl", "pre_merge"]
    )

    assert newly == ["breaker:no_progress"]  # transients still clear
    assert not gate_pause.is_gate_cleared(plan_dir, "pre_merge")
    assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")


@pytest.mark.parametrize(
    "argv",
    [["approve", _BOTH_GATES_ID, "pre_merge"], ["resume", _BOTH_GATES_ID, "--gate", "pre_merge"]],
)
def test_r4_invalid_pending_stage_cli_refuses_pre_merge(
    repo: Path, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    from dontpanic_orchestrate import cli

    plan_dir = _garbage_stage_plan(repo)
    before = _state_bytes(plan_dir)
    assert cli.main(argv) == 2
    # Refused either by the shared pending-stage rule or by the CLI's
    # gate-state reconciliation (incompatible_pending_stage) — never cleared.
    assert "REFUSED" in capsys.readouterr().err
    assert _state_bytes(plan_dir) == before
    assert not gate_pause.is_gate_cleared(plan_dir, "pre_merge")


# ───────── MED-3 — transcript failure after a durable signoff ─────────


def test_r4_transcript_failure_after_durable_signoff_keeps_one_success_terminal(
    repo: Path, captured: list[Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_dir = _make_plan(repo, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    real_append = supervisor.transcript.append_terminal

    def _failing_terminal(plan_dir_arg: Path, feature_id: str, status: str, *a: Any, **kw: Any) -> Any:
        if status == "signed_off":
            raise OSError(28, "No space left on device (injected transcript fault)")
        return real_append(plan_dir_arg, feature_id, status, *a, **kw)

    monkeypatch.setattr(supervisor.transcript, "append_terminal", _failing_terminal)

    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert result.final_status == "signed_off", result
    signoff = json.loads(signoff_writer.signoff_path(plan_dir, TOP_ID).read_text())
    assert signoff["signoff"] is True
    # Exactly one terminal INBOX entry (the success), no crash entry, no
    # blocked transcript terminal, exactly one terminal notification.
    assert [e.headers.get("final_status") for e in _terminal_inbox(plan_dir)] == ["signed_off"]
    assert _crash_caught(plan_dir) == []
    assert _transcript_terminals(plan_dir) == []
    kinds = [getattr(e, "kind", None) for e in captured]
    terminal_statuses = [
        e.technical_metadata.get("final_status")
        for e in captured
        if getattr(e, "kind", None) == "volley_terminal"
    ]
    assert "blocked" not in terminal_statuses, kinds
    assert kinds.count("signoff") == 1, kinds
    assert "transcript terminal append failed" in capsys.readouterr().out


# ───────── MED-4 — CLI finalize: plan_unloadable + distinct exit codes ─────────


def test_r4_cli_finalize_unloadable_plan_refuses_plan_unloadable(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from dontpanic_orchestrate import cli

    plan_dir = _make_plan(repo, TOP_ID)
    _write_envelopes(plan_dir, TOP_ID)
    plan_md = plan_dir / "plan.md"
    plan_md.write_text(plan_md.read_text().replace("title: DP-003 signoff integrity synthetic\n", ""))
    before_features = (plan_dir / "features.json").read_bytes()

    rc = cli.main(["finalize", str(plan_dir), "--feature", "F001"])

    assert rc == signed_off_finalizer.REFUSAL_EXIT_CODES["plan_unloadable"] == 7
    assert "REFUSED (plan_unloadable)" in capsys.readouterr().err
    assert (plan_dir / "features.json").read_bytes() == before_features
    assert not signoff_writer.signoff_path(plan_dir, TOP_ID).exists()


def test_r4_every_refusal_code_has_a_distinct_documented_exit_code() -> None:
    import inspect
    import re

    from dontpanic_orchestrate import cli

    codes = signed_off_finalizer.REFUSAL_EXIT_CODES
    raised = set(
        re.findall(r'FinalizeError\(\s*"([a-z_]+)"', inspect.getsource(signed_off_finalizer))
    )
    assert raised, "no refusal codes found"
    assert raised <= set(codes), sorted(raised - set(codes))
    exits = list(codes.values())
    assert len(exits) == len(set(exits)), codes
    # 0 success, 2 usage, 6 plan drift and the unmapped fallback are reserved.
    reserved = {0, 2, 6, signed_off_finalizer.UNKNOWN_REFUSAL_EXIT_CODE}
    assert not reserved & set(exits), codes
    doc = cli._finalize_main.__doc__ or ""
    for code, exit_code in codes.items():
        assert re.search(rf"\b{exit_code}\s+— refused \({code}\)", doc), (code, exit_code)


@pytest.mark.parametrize(
    ("corrupt", "code"),
    [
        ("empty", "signoff_unreadable"),
        ("stale", "signoff_stale"),
        ("not_success", "signoff_not_success"),
    ],
)
def test_r4_cli_finalize_refusals_exit_with_their_distinct_code(
    repo: Path,
    captured: list[Any],
    capsys: pytest.CaptureFixture[str],
    corrupt: str,
    code: str,
) -> None:
    """Real dispatch (records the drift baseline + durable signoff), then a
    real refusal through ``dontpanic finalize`` exits with its own code."""
    from dontpanic_orchestrate import cli

    plan_dir = _make_plan(repo, TOP_ID)
    _clear_pre_merge(plan_dir, TOP_ID)
    assert supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1).final_status == "signed_off"
    # DPN-012: the volley wrote the plan-level signoff AND F001's own copy;
    # the finalizer selects F001's own copy, so corrupt both.
    for sp in (
        signoff_writer.signoff_path(plan_dir, TOP_ID),
        signoff_writer.feature_signoff_path(plan_dir, TOP_ID, "F001"),
    ):
        data = json.loads(sp.read_text())
        if corrupt == "empty":
            sp.write_text("")
        elif corrupt == "stale":
            data["decided_at"] = "2020-01-01T00:00:00Z"
            sp.write_text(json.dumps(data, indent=2) + "\n")
        else:
            data["signoff"] = False
            data["next_action"] = "remediate"
            sp.write_text(json.dumps(data, indent=2) + "\n")
    capsys.readouterr()

    rc = cli.main(["finalize", str(plan_dir), "--feature", "F001"])

    err = capsys.readouterr().err
    assert rc == signed_off_finalizer.REFUSAL_EXIT_CODES[code], (rc, err[-400:])
    assert f"REFUSED ({code})" in err
    assert _passes(plan_dir) is False


def test_r4_cli_finalize_blocked_child_exits_child_not_satisfied(
    repo: Path, captured: list[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    from dontpanic_orchestrate import cli

    plan_dir = _make_child(repo, memo_status="blocked")
    _clear_pre_merge(plan_dir, CHILD_ID)
    supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert json.loads(_side_car(plan_dir, CHILD_ID).read_text())["return_condition_status"] == "blocked"
    capsys.readouterr()

    rc = cli.main(["finalize", str(plan_dir), "--feature", "F001"])

    err = capsys.readouterr().err
    assert rc == signed_off_finalizer.REFUSAL_EXIT_CODES["child_not_satisfied"] == 15, err[-400:]
    assert _passes(plan_dir) is False


# ───────── DPN-012 — per-feature durable signoff evidence (finalizer:314) ─────────


def _r10_features() -> list[dict[str, Any]]:
    return [_feature("F001", "First independent feature."), _feature("F002", "Second independent feature.")]


def _r10_plan(repo: Path, *, child: bool) -> tuple[Path, str]:
    """Two independent features; a child plan gets a satisfied close-out memo."""
    if not child:
        return _make_plan(repo, TOP_ID, features=_r10_features()), TOP_ID
    if not (repo / "docs" / "plans" / PARENT_ID).is_dir():
        _make_plan(repo, PARENT_ID)
    plan_dir = _make_plan(repo, CHILD_ID, child=True, features=_r10_features())
    (plan_dir / "evidence").mkdir(parents=True, exist_ok=True)
    (plan_dir / "evidence" / "closeout-memo.md").write_text(
        "# Close-out\n\n## Return Condition\n\nstatus: satisfied\n"
    )
    return plan_dir, CHILD_ID


def _r10_volley(
    plan_dir: Path,
    plan_id: str,
    fid: str,
    *,
    iteration: int = 0,
    audit_status: str = "signed_off",
    offset: int = 0,
) -> Path:
    """Implementer + auditor envelopes for ``fid`` completed ``offset`` seconds
    after a past base time. Returns the auditor envelope."""
    impl = plan_dir / "audit" / f"claude-implementer-{fid}-i{iteration}.json"
    impl.parent.mkdir(parents=True, exist_ok=True)
    impl.write_text(json.dumps({"agent": "claude", "agent_role": "implementer", "iteration": iteration}))
    return _auditor_envelope_for(
        plan_dir,
        plan_id,
        fid,
        iteration=iteration,
        audit_status=audit_status,
        newer_than=None,
        completed_at=_base_time() + dt.timedelta(seconds=offset),
    )


def _r10_sign(
    plan_dir: Path,
    plan_id: str,
    auditor: Path,
    *,
    feature_id: str | None,
    iteration: int = 0,
    volley_status: str = "signed_off",
    child: bool = False,
    plan_level: bool = True,
) -> Path:
    """The REAL writer, exactly as the supervisor calls it for one volley."""
    loaded = plan_loader.load(plan_dir) if child else None
    kwargs: dict[str, Any] = {}
    if feature_id is not None:
        kwargs["feature_id"] = feature_id
    if not plan_level:
        kwargs["plan_level"] = False
    return signoff_writer.write_signoff(
        plan_id=plan_id,
        tier="trivial",
        iteration=iteration,
        agents_in_panel=["claude", "codex"],
        audit_paths=[auditor],
        plan_dir=plan_dir,
        volley_status=volley_status,
        child_charter=loaded.child_charter if loaded else None,
        commit_policy=loaded.commit_policy if loaded else None,
        **kwargs,
    )


def _r10_passes(plan_dir: Path, fid: str) -> bool:
    data = json.loads((plan_dir / "features.json").read_text())
    return bool(next(f for f in data["features"] if f["id"] == fid)["passes"])


def _r10_refs(plan_dir: Path, fid: str) -> list[str]:
    data = json.loads((plan_dir / "features.json").read_text())
    feat = next(f for f in data["features"] if f["id"] == fid)
    return [r.get("uri") for r in feat.get("evidence_refs") or []]


def _r10_tree(plan_dir: Path) -> dict[str, bytes]:
    """Every file under ``audit/`` (recursively), relative path → bytes."""
    audit = plan_dir / "audit"
    return {str(p.relative_to(audit)): p.read_bytes() for p in sorted(audit.rglob("*")) if p.is_file()}


def _r10_fsig(plan_dir: Path, plan_id: str, fid: str = "F001") -> Path:
    return signoff_writer.feature_signoff_path(plan_dir, plan_id, fid)


def _r10_fside(plan_dir: Path, plan_id: str, fid: str = "F001") -> Path:
    return signoff_writer.feature_charter_compliance_path(plan_dir, plan_id, fid)


def _r10_assert_refused(plan_dir: Path, plan_id: str, code: str, fid: str = "F001") -> None:
    """Finalize ``fid`` refuses with ``code``; no passes flip, no file under
    ``audit/`` (including ``feature-signoffs/``) created or changed."""
    before_tree = _r10_tree(plan_dir)
    before_features = (plan_dir / "features.json").read_bytes()
    with pytest.raises(signed_off_finalizer.FinalizeError) as exc:
        signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id=fid)
    assert exc.value.code == code, (exc.value.code, str(exc.value))
    assert _r10_passes(plan_dir, fid) is False
    assert (plan_dir / "features.json").read_bytes() == before_features
    assert _r10_tree(plan_dir) == before_tree


def _r10_two_volleys(plan_dir: Path, plan_id: str, *, child: bool) -> tuple[Path, Path]:
    """F001 volley signed_off → signoff(F001); then F002 volley signed_off →
    signoff(F002), which replaces the plan-level pair with F002's evidence."""
    a1 = _r10_volley(plan_dir, plan_id, "F001", offset=0)
    _r10_sign(plan_dir, plan_id, a1, feature_id="F001", child=child)
    a2 = _r10_volley(plan_dir, plan_id, "F002", offset=10)
    _r10_sign(plan_dir, plan_id, a2, feature_id="F002", child=child)
    plan_level = json.loads(signoff_writer.signoff_path(plan_dir, plan_id).read_text())
    assert plan_level["audits"] == [str(a2.relative_to(plan_dir))]
    return a1, a2


# (a) two-feature regression ─────────────────────────────────────────────


@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
def test_r10_two_feature_finalize_selects_each_features_own_signoff(repo: Path, child: bool) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=child)
    _r10_two_volleys(plan_dir, plan_id, child=child)
    _clear_pre_merge(plan_dir, plan_id)
    plan_sp = signoff_writer.signoff_path(plan_dir, plan_id)
    plan_side = signoff_writer.charter_compliance_path(plan_dir, plan_id)
    plan_before = plan_sp.read_bytes()
    side_before = plan_side.read_bytes() if child else None
    if child:
        assert _r10_fside(plan_dir, plan_id, "F001").is_file()
        assert _r10_fside(plan_dir, plan_id, "F002").is_file()

    for fid in ("F001", "F002"):
        fsig = _r10_fsig(plan_dir, plan_id, fid)
        fsig_before = fsig.read_bytes()
        fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id=fid)
        assert fin.features_passes_flipped is True, fid
        assert fin.signoff_repaired is False, fid
        assert fin.signoff_path == fsig, fid
        assert _r10_passes(plan_dir, fid) is True
        assert str(fsig.relative_to(plan_dir)) in _r10_refs(plan_dir, fid)
        assert fsig.read_bytes() == fsig_before

    assert plan_sp.read_bytes() == plan_before
    if child:
        assert plan_side.read_bytes() == side_before


def test_r10_two_feature_finalize_through_real_supervisor_volleys(
    repo: Path, captured: list[Any]
) -> None:
    """Real ``dispatch_volley`` for F001 then F002 (the second rewrites the
    plan-level signoff); finalizing F001 then F002 both succeed."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _clear_pre_merge(plan_dir, plan_id)
    assert supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1).final_status == "signed_off"
    f001_evidence = _r10_fsig(plan_dir, plan_id, "F001").read_bytes()
    assert supervisor.dispatch_volley(plan_dir, "F002", max_iterations=1).final_status == "signed_off"
    plan_level = json.loads(signoff_writer.signoff_path(plan_dir, plan_id).read_text())
    assert all("F002" in a for a in plan_level["audits"]), plan_level["audits"]
    assert _r10_fsig(plan_dir, plan_id, "F001").read_bytes() == f001_evidence

    for fid in ("F001", "F002"):
        fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id=fid)
        assert fin.features_passes_flipped is True, fid
        assert fin.signoff_repaired is False, fid
        assert fin.signoff_path == _r10_fsig(plan_dir, plan_id, fid)


# (b) legacy repair ──────────────────────────────────────────────────────


@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
def test_r10_legacy_plan_level_of_other_feature_repairs_only_feature_pair(
    repo: Path, child: bool
) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=child)
    a1 = _r10_volley(plan_dir, plan_id, "F001", offset=0)
    a2 = _r10_volley(plan_dir, plan_id, "F002", offset=10)
    _r10_sign(plan_dir, plan_id, a2, feature_id=None, child=child)  # pre-DPN-012 writer call
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()
    _clear_pre_merge(plan_dir, plan_id)
    plan_sp = signoff_writer.signoff_path(plan_dir, plan_id)
    plan_side = signoff_writer.charter_compliance_path(plan_dir, plan_id)
    plan_before = plan_sp.read_bytes()
    side_before = plan_side.read_bytes() if child else None

    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")

    assert fin.features_passes_flipped is True
    assert fin.signoff_repaired is True
    fsig = _r10_fsig(plan_dir, plan_id)
    assert fin.signoff_path == fsig
    data = json.loads(fsig.read_text())
    assert data["signoff"] is True and data["task_id"] == plan_id
    assert data["audits"] == [str(p.relative_to(plan_dir)) for p in [a1.parent / "claude-implementer-F001-i0.json", a1]]
    assert str(fsig.relative_to(plan_dir)) in _r10_refs(plan_dir, "F001")
    # The plan-level pair (F002's evidence) is byte-for-byte untouched.
    assert plan_sp.read_bytes() == plan_before
    if child:
        assert plan_side.read_bytes() == side_before
        side = json.loads(_r10_fside(plan_dir, plan_id).read_text())
        assert side["signoff_id"] == data["signoff_id"]
        assert side["return_condition_status"] == "satisfied"
    else:
        assert not _r10_fside(plan_dir, plan_id).exists()
    # Re-run is idempotent and now selects the repaired per-feature signoff.
    again = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert again.already_finalized is True and again.signoff_path == fsig


_R11_MISSING = object()


def _r11_legacy_branch_c(repo: Path, *, child: bool, completed_at: Any) -> tuple[Path, str]:
    """Branch (c) setup exactly as the r10 legacy-repair test, then rewrite
    F001's latest auditor envelope's ``completed_at`` in place (verdict stays
    signed_off). ``_R11_MISSING`` removes the key."""
    plan_dir, plan_id = _r10_plan(repo, child=child)
    a1 = _r10_volley(plan_dir, plan_id, "F001", offset=0)
    a2 = _r10_volley(plan_dir, plan_id, "F002", offset=10)
    _r10_sign(plan_dir, plan_id, a2, feature_id=None, child=child)  # pre-DPN-012 writer call
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()
    _clear_pre_merge(plan_dir, plan_id)
    env = json.loads(a1.read_text())
    if completed_at is _R11_MISSING:
        env.pop("completed_at", None)
    else:
        env["completed_at"] = completed_at
    a1.write_text(json.dumps(env))
    assert signed_off_finalizer._verdict_of(env) == signed_off_finalizer.SIGNED_OFF_VERDICT
    return plan_dir, plan_id


@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
@pytest.mark.parametrize(
    "completed_at",
    [_R11_MISSING, "2026-11-12T10:00:00", "2026-11-12"],
    ids=["missing", "zone_less", "date_only"],
)
def test_r11_legacy_repair_refused_when_envelope_completed_at_unusable(
    repo: Path, child: bool, completed_at: Any
) -> None:
    """CodeRabbit 4558784587 — branch (c) must not repair a per-feature
    signoff (and flip passes) from an envelope whose completed_at the next
    finalize's freshness check would refuse."""
    plan_dir, plan_id = _r11_legacy_branch_c(repo, child=child, completed_at=completed_at)
    plan_sp = signoff_writer.signoff_path(plan_dir, plan_id)
    plan_side = signoff_writer.charter_compliance_path(plan_dir, plan_id)
    plan_before = plan_sp.read_bytes()
    side_before = plan_side.read_bytes() if child else None

    _r10_assert_refused(plan_dir, plan_id, "signoff_stale")

    assert not _r10_fsig(plan_dir, plan_id).exists()
    assert not _r10_fside(plan_dir, plan_id).exists()
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()
    assert plan_sp.read_bytes() == plan_before
    if child:
        assert plan_side.read_bytes() == side_before


@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
def test_r11_legacy_repair_with_zone_aware_completed_at_still_repairs(repo: Path, child: bool) -> None:
    """Control: a valid zone-aware completed_at keeps the branch (c) repair."""
    plan_dir, plan_id = _r11_legacy_branch_c(
        repo, child=child, completed_at=_base_time().isoformat().replace("+00:00", "Z")
    )
    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert fin.signoff_repaired is True
    assert fin.features_passes_flipped is True
    assert fin.signoff_path == _r10_fsig(plan_dir, plan_id)
    assert _r10_passes(plan_dir, "F001") is True
    again = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert again.already_finalized is True


@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
def test_r12_legacy_repair_refused_when_envelope_completed_at_in_future(repo: Path, child: bool) -> None:
    """Sentinel 5886142259 — a zone-aware completed_at later than the
    finalizer's clock must not let branch (c) repair a per-feature signoff
    (and flip passes) that the next finalize's freshness check calls stale."""
    future = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(hours=1)
    plan_dir, plan_id = _r11_legacy_branch_c(
        repo, child=child, completed_at=future.isoformat().replace("+00:00", "Z")
    )
    plan_sp = signoff_writer.signoff_path(plan_dir, plan_id)
    plan_side = signoff_writer.charter_compliance_path(plan_dir, plan_id)
    plan_before = plan_sp.read_bytes()
    side_before = plan_side.read_bytes() if child else None

    _r10_assert_refused(plan_dir, plan_id, "signoff_stale")

    assert not _r10_fsig(plan_dir, plan_id).exists()
    assert not _r10_fside(plan_dir, plan_id).exists()
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()
    assert plan_sp.read_bytes() == plan_before
    if child:
        assert plan_side.read_bytes() == side_before
    with pytest.raises(signed_off_finalizer.FinalizeError) as exc:
        signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert "auditor envelope" in str(exc.value) and "predates" in str(exc.value)


@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
def test_r13_legacy_repair_stamps_guarded_decided_at_across_backward_clock_jump(
    repo: Path, child: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sentinel 5886471727 — branch (c) must stamp the decided_at its
    freshness guard checked (one clock read), so a backward clock step between
    guard and write cannot persist a signoff the next finalize calls stale."""
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    t = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    t_iso = t.strftime(fmt)
    plan_dir, plan_id = _r11_legacy_branch_c(
        repo, child=child, completed_at=(t - dt.timedelta(hours=1)).strftime(fmt)
    )
    calls: list[str] = []

    def fake_now_iso() -> str:
        value = t_iso if not calls else (t - dt.timedelta(hours=2)).strftime(fmt)
        calls.append(value)
        return value

    monkeypatch.setattr(signoff_writer, "_now_iso", fake_now_iso)

    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert fin.signoff_repaired is True
    assert fin.features_passes_flipped is True
    assert fin.signoff_path == _r10_fsig(plan_dir, plan_id)
    assert json.loads(_r10_fsig(plan_dir, plan_id).read_text())["decided_at"] == t_iso
    assert _r10_passes(plan_dir, "F001") is True
    assert calls == [t_iso]
    again = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert again.already_finalized is True


def test_r10_repair_with_no_signoff_writes_both_pairs(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=True)
    _r10_volley(plan_dir, plan_id, "F001")
    _clear_pre_merge(plan_dir, plan_id)

    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")

    assert fin.signoff_repaired is True and fin.features_passes_flipped is True
    assert fin.signoff_path == _r10_fsig(plan_dir, plan_id)
    assert signoff_writer.signoff_path(plan_dir, plan_id).read_bytes() == _r10_fsig(plan_dir, plan_id).read_bytes()
    assert (
        signoff_writer.charter_compliance_path(plan_dir, plan_id).read_bytes()
        == _r10_fside(plan_dir, plan_id).read_bytes()
    )


# (c) refusals that must survive ─────────────────────────────────────────


def test_r10_feature_signoff_same_path_overwritten_later_is_stale(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    a1, _a2 = _r10_two_volleys(plan_dir, plan_id, child=False)
    # Re-dispatch rewrote F001's -i0 envelope AFTER its per-feature signoff.
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    _auditor_envelope_for(
        plan_dir, plan_id, "F001", iteration=0, audit_status="signed_off",
        newer_than=None, completed_at=later,
    )
    assert a1.is_file()
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_stale")


def test_r10_feature_signoff_iteration_mismatch_is_stale(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _r10_two_volleys(plan_dir, plan_id, child=False)
    # A newer signed_off F001 verdict (i1) without a matching signoff.
    _r10_volley(plan_dir, plan_id, "F001", iteration=1, offset=20)
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_stale")


def test_r10_feature_signoff_listing_another_features_audit_is_stale(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _r10_two_volleys(plan_dir, plan_id, child=False)
    # F001's per-feature file now carries F002's (valid, same-iteration) signoff.
    _r10_fsig(plan_dir, plan_id, "F001").write_bytes(_r10_fsig(plan_dir, plan_id, "F002").read_bytes())
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_stale")


def test_r10_later_non_success_feature_signoff_refused_not_repaired(repo: Path) -> None:
    """F001 signed_off evidence is replaced by a later F001 volley whose
    signoff was blocked (auditor still signed_off); F002 then rewrites the
    plan-level signoff. Finalizing F001 is refused ``signoff_not_success`` —
    never repaired over."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    a1 = _r10_volley(plan_dir, plan_id, "F001", offset=0)
    _r10_sign(plan_dir, plan_id, a1, feature_id="F001")
    assert json.loads(_r10_fsig(plan_dir, plan_id).read_text())["signoff"] is True
    _r10_sign(plan_dir, plan_id, a1, feature_id="F001", volley_status="blocked")
    assert json.loads(_r10_fsig(plan_dir, plan_id).read_text())["signoff"] is False
    a2 = _r10_volley(plan_dir, plan_id, "F002", offset=10)
    _r10_sign(plan_dir, plan_id, a2, feature_id="F002")
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_not_success")


@pytest.mark.parametrize("how", ["decided_before_verdict", "older_iteration"])
def test_r10_stale_plan_level_listing_this_feature_still_refused_no_repair(
    repo: Path, how: str
) -> None:
    """No per-feature file; the plan-level signoff lists F001's audit but is
    stale → still ``signoff_stale`` and NO per-feature file is written."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    a0 = _r10_volley(plan_dir, plan_id, "F001", offset=0)
    sp = _r10_sign(plan_dir, plan_id, a0, feature_id=None)
    if how == "decided_before_verdict":
        data = json.loads(sp.read_text())
        data["decided_at"] = "2020-01-01T00:00:00Z"
        sp.write_text(json.dumps(data, indent=2) + "\n")
    else:
        _r10_volley(plan_dir, plan_id, "F001", iteration=1, offset=20)
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_stale")
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()


def test_r10_plan_level_listing_this_feature_by_unresolvable_path_still_refused(repo: Path) -> None:
    """A plan-level signoff naming an F001 envelope that no longer resolves
    (moved / deleted) is still this feature's — validated, never repaired."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    a0 = _r10_volley(plan_dir, plan_id, "F001", offset=0)
    sp = _r10_sign(plan_dir, plan_id, a0, feature_id=None)
    data = json.loads(sp.read_text())
    data["audits"] = ["/elsewhere/old-checkout/audit/codex-auditor-F001-i0.json"]
    sp.write_text(json.dumps(data, indent=2) + "\n")
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_stale")
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()


@pytest.mark.parametrize(
    ("corrupt", "code"),
    [
        ("empty", "signoff_unreadable"),
        ("torn", "signoff_unreadable"),
        ("not_object", "signoff_unreadable"),
        ("schema", "signoff_unreadable"),
        ("other_plan", "signoff_wrong_plan"),
    ],
)
def test_r10_unusable_plan_level_still_refused_no_repair(repo: Path, corrupt: str, code: str) -> None:
    """A plan-level signoff that cannot be shown to belong to other features
    (here: F002's, corrupted) is validated exactly as before — no repair."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _r10_volley(plan_dir, plan_id, "F001", offset=0)
    a2 = _r10_volley(plan_dir, plan_id, "F002", offset=10)
    sp = _r10_sign(plan_dir, plan_id, a2, feature_id=None)
    data = json.loads(sp.read_text())
    if corrupt == "empty":
        sp.write_text("")
    elif corrupt == "torn":
        sp.write_text(sp.read_text()[:40])
    elif corrupt == "not_object":
        sp.write_text(json.dumps([data]))
    elif corrupt == "schema":
        del data["signoff_id"]
        sp.write_text(json.dumps(data, indent=2) + "\n")
    else:
        data["task_id"] = "2026-11-12-499-some-other-plan"
        sp.write_text(json.dumps(data, indent=2) + "\n")
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, code)
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()


def test_r10_child_feature_sidecar_missing_refused(repo: Path) -> None:
    """Only F001 dispatched: the plan-level pair is F001's and valid, so the
    per-feature side-car is the ONLY thing missing → ``child_signoff_missing``."""
    plan_dir, plan_id = _r10_plan(repo, child=True)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    _r10_sign(plan_dir, plan_id, a1, feature_id="F001", child=True)
    assert signoff_writer.charter_compliance_path(plan_dir, plan_id).is_file()
    _r10_fside(plan_dir, plan_id).unlink()
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "child_signoff_missing")


def test_r10_child_feature_sidecar_bound_to_other_signoff_refused(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=True)
    _r10_two_volleys(plan_dir, plan_id, child=True)
    # F001's side-car replaced by F002's (bound to F002's signoff/audits).
    _r10_fside(plan_dir, plan_id, "F001").write_bytes(_r10_fside(plan_dir, plan_id, "F002").read_bytes())
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "child_signoff_stale")


def test_r10_feature_signoff_wrong_task_id_refused(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _r10_two_volleys(plan_dir, plan_id, child=False)
    fsig = _r10_fsig(plan_dir, plan_id)
    data = json.loads(fsig.read_text())
    data["task_id"] = "2026-11-12-499-some-other-plan"
    fsig.write_text(json.dumps(data, indent=2) + "\n")
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_wrong_plan")


def test_r10_torn_feature_signoff_refused_even_with_valid_plan_level(repo: Path) -> None:
    """Rule (a): an existing per-feature signoff is authoritative — a torn one
    is refused even though the plan-level signoff would validate."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    _r10_sign(plan_dir, plan_id, a1, feature_id="F001")
    _r10_fsig(plan_dir, plan_id).write_text("{")
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_unreadable")


# (d) writer ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("volley_status", ["signed_off", "blocked", "stopped_cap"])
def test_r10_writer_writes_feature_pair_for_every_outcome(repo: Path, volley_status: str) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=True)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    out = _r10_sign(plan_dir, plan_id, a1, feature_id="F001", volley_status=volley_status, child=True)
    assert out == signoff_writer.signoff_path(plan_dir, plan_id)
    fsig, fside = _r10_fsig(plan_dir, plan_id), _r10_fside(plan_dir, plan_id)
    assert fsig.parent == plan_dir / "audit" / "feature-signoffs"
    assert fsig.name == f"signoff-{plan_id}--F001.json"
    assert fside.name == f"charter-compliance-{plan_id}--F001.json"
    assert fsig.read_bytes() == out.read_bytes()
    assert fside.read_bytes() == signoff_writer.charter_compliance_path(plan_dir, plan_id).read_bytes()
    assert json.loads(fsig.read_text())["signoff"] is (volley_status == "signed_off")


def test_r10_writer_later_blocked_volley_replaces_feature_success_evidence(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    _r10_sign(plan_dir, plan_id, a1, feature_id="F001")
    _r10_sign(plan_dir, plan_id, a1, feature_id="F001", volley_status="blocked")
    data = json.loads(_r10_fsig(plan_dir, plan_id).read_text())
    assert data["signoff"] is False and data["next_action"] == "blocked_awaiting_human"


def _r10_fail_nth_write(monkeypatch: pytest.MonkeyPatch, n: int) -> list[Path]:
    real = signoff_writer._atomic_write_json
    calls: list[Path] = []

    def _faulty(path: Path, obj: dict[str, Any]) -> None:
        calls.append(Path(path))
        if len(calls) == n:
            raise OSError(28, "No space left on device (injected)")
        real(path, obj)

    monkeypatch.setattr(signoff_writer, "_atomic_write_json", _faulty)
    return calls


@pytest.mark.parametrize("previous", [True, False], ids=["overwrite", "fresh"])
@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_r10_writer_four_file_transaction_rolls_back(
    repo: Path, monkeypatch: pytest.MonkeyPatch, previous: bool, fail_at: int
) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=True)
    a0 = _r10_volley(plan_dir, plan_id, "F001", iteration=0)
    if previous:
        _r10_sign(plan_dir, plan_id, a0, feature_id="F001", child=True)
    four = [
        signoff_writer.signoff_path(plan_dir, plan_id),
        signoff_writer.charter_compliance_path(plan_dir, plan_id),
        _r10_fsig(plan_dir, plan_id),
        _r10_fside(plan_dir, plan_id),
    ]
    before = {p: (p.read_bytes() if p.is_file() else None) for p in four}
    assert all(v is not None for v in before.values()) is previous
    a1 = _r10_volley(plan_dir, plan_id, "F001", iteration=1, offset=5)
    calls = _r10_fail_nth_write(monkeypatch, fail_at)

    with pytest.raises(OSError):
        _r10_sign(plan_dir, plan_id, a1, feature_id="F001", iteration=1, child=True)

    assert len(calls) == fail_at
    if fail_at == 4:
        # The LAST write of the transaction is the plan-level signoff.
        assert calls[-1] == four[0]
    for p in four:
        assert (p.read_bytes() if p.is_file() else None) == before[p], (fail_at, p.name)
    if not previous:
        assert not signoff_writer.feature_signoff_dir(plan_dir).exists()
    leftovers = [p.name for p in (plan_dir / "audit").rglob("*.tmp")]
    assert leftovers == []


def test_r10_writer_without_feature_id_writes_only_plan_level_pair(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=True)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    before = set(_r10_tree(plan_dir))
    out = _r10_sign(plan_dir, plan_id, a1, feature_id=None, child=True)
    added = set(_r10_tree(plan_dir)) - before
    assert added == {f"signoff-{plan_id}.json", f"charter-compliance-{plan_id}.json"}
    assert out == signoff_writer.signoff_path(plan_dir, plan_id)
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()


def test_r10_writer_feature_only_mode_never_touches_plan_level_pair(repo: Path) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=True)
    _r10_volley(plan_dir, plan_id, "F001", offset=0)
    a2 = _r10_volley(plan_dir, plan_id, "F002", offset=10)
    _r10_sign(plan_dir, plan_id, a2, feature_id=None, child=True)
    plan_pair = {
        p: p.read_bytes()
        for p in (
            signoff_writer.signoff_path(plan_dir, plan_id),
            signoff_writer.charter_compliance_path(plan_dir, plan_id),
        )
    }
    a1 = plan_dir / "audit" / "codex-auditor-F001-i0.json"
    out = _r10_sign(plan_dir, plan_id, a1, feature_id="F001", child=True, plan_level=False)
    assert out == _r10_fsig(plan_dir, plan_id)
    assert _r10_fside(plan_dir, plan_id).is_file()
    for p, b in plan_pair.items():
        assert p.read_bytes() == b
    with pytest.raises(signoff_writer.SignoffWriteError):
        _r10_sign(plan_dir, plan_id, a1, feature_id=None, plan_level=False)


@pytest.mark.parametrize("bad", ["../x", "F-1", "", "a/b", "F1..2", ".F1", "F1\n", "F 1"])
def test_r10_writer_refuses_invalid_feature_id_and_writes_nothing(repo: Path, bad: str) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=True)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    before = _r10_tree(plan_dir)
    with pytest.raises(signoff_writer.SignoffWriteError):
        _r10_sign(plan_dir, plan_id, a1, feature_id=bad, child=True)
    assert _r10_tree(plan_dir) == before
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()
    for fn in (signoff_writer.feature_signoff_path, signoff_writer.feature_charter_compliance_path):
        with pytest.raises(signoff_writer.SignoffWriteError):
            fn(plan_dir, plan_id, bad)


def test_r10_real_feature_ids_are_accepted() -> None:
    """Every feature id committed under docs/plans is a valid per-feature id."""
    plans = HERE.parents[3] / "docs" / "plans"
    ids = set()
    for fj in plans.rglob("features.json"):
        try:
            data = json.loads(fj.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for f in (data.get("features") or []) if isinstance(data, dict) else []:
            if isinstance(f, dict) and isinstance(f.get("id"), str):
                ids.add(f["id"])
    assert ids
    for fid in ids:
        assert signoff_writer.feature_signoff_path(Path("/p"), "plan", fid).name == f"signoff-plan--{fid}.json"


# (e) closeout ignores the subdirectory ───────────────────────────────────


def test_r10_audit_paths_for_feature_ignores_feature_signoffs_dir(repo: Path) -> None:
    from dontpanic_orchestrate import closeout

    plan_dir, plan_id = _r10_plan(repo, child=True)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    _r10_sign(plan_dir, plan_id, a1, feature_id="F001", child=True)
    assert _r10_fsig(plan_dir, plan_id).is_file() and _r10_fside(plan_dir, plan_id).is_file()
    paths = closeout._audit_paths_for_feature(plan_dir, "F001")
    assert [p.name for p in paths] == ["claude-implementer-F001-i0.json", "codex-auditor-F001-i0.json"]
    assert closeout._audit_paths_for_feature(plan_dir, "F002") == []


# ───────── DPN-012b — hardening of per-feature signoff evidence (Sentinel #104 LOWs) ─────────


def _r11_non_success_plan_level_listing(plan_dir: Path, plan_id: str, entry: str) -> None:
    """F001 + F002 signed_off volleys; the plan-level signoff is a NON-success
    (blocked) record for F002, hand-edited to ALSO list ``entry`` (an alias of
    F001's auditor envelope). No per-feature evidence exists."""
    _r10_volley(plan_dir, plan_id, "F001", offset=0)
    a2 = _r10_volley(plan_dir, plan_id, "F002", offset=10)
    sp = _r10_sign(plan_dir, plan_id, a2, feature_id=None, volley_status="blocked")
    data = json.loads(sp.read_text())
    data["audits"] = [str(a2.relative_to(plan_dir)), entry]
    sp.write_text(json.dumps(data, indent=2) + "\n")
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()


def test_dpn012b_canonical_name_non_success_plan_level_baseline(repo: Path) -> None:
    """Baseline the alias cases must match: the canonical (unresolvable) name
    is this feature's (rule b) → ``signoff_not_success``, no repair."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _r11_non_success_plan_level_listing(
        plan_dir, plan_id, "/elsewhere/old-checkout/audit/codex-auditor-F001-i0.json"
    )
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_not_success")
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()


def test_dpn012b_lower_cased_name_listing_this_feature_is_rule_b(repo: Path) -> None:
    """Fix 1(a): a lower-cased envelope name names F001. The path does NOT
    exist (moved absolute prefix), so neither ``resolve()`` nor ``samefile``
    can match it on any volume — only the case-insensitive name match does."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    entry = "/elsewhere/old-checkout/audit/codex-auditor-f001-i0.json"
    assert not Path(entry).exists()
    _r11_non_success_plan_level_listing(plan_dir, plan_id, entry)
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_not_success")
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()


def test_dpn012b_entry_names_feature_is_case_insensitive() -> None:
    names = signed_off_finalizer._entry_names_feature
    assert names("audit/codex-auditor-f001-i0.json", "F001")
    assert names("audit/CODEX-AUDITOR-F001-I0.JSON", "F001")
    assert names("audit/codex-auditor-F001-i0.json", "f001")
    assert not names("audit/codex-auditor-f0010-i0.json", "F001")


def test_dpn012b_hard_link_alias_listing_this_feature_is_rule_b(repo: Path) -> None:
    """Fix 1(b): a hard link to F001's auditor envelope under a neutral name
    (``audit/alias.json``) is matched by ``samefile`` → this feature's."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    alias = plan_dir / "audit" / "alias.json"
    _r10_volley(plan_dir, plan_id, "F001", offset=0)
    os.link(plan_dir / "audit" / "codex-auditor-F001-i0.json", alias)
    _r11_non_success_plan_level_listing(plan_dir, plan_id, "audit/alias.json")
    assert alias.resolve() != (plan_dir / "audit" / "codex-auditor-F001-i0.json").resolve()
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_not_success")
    assert not signoff_writer.feature_signoff_dir(plan_dir).exists()


# Fix 2 — a stray regular FILE at audit/feature-signoffs ──────────────────


def _r11_stray_file(plan_dir: Path) -> Path:
    stray = signoff_writer.feature_signoff_dir(plan_dir)
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"stray, not a directory\n")
    return stray


@pytest.mark.parametrize("feature_id", ["F001", None], ids=["per_feature", "plan_level_only"])
def test_dpn012b_writer_stray_file_raises_signoff_write_error_writes_nothing(
    repo: Path, feature_id: str | None
) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=True)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    _r11_stray_file(plan_dir)
    before = _r10_tree(plan_dir)
    with pytest.raises(signoff_writer.SignoffWriteError, match="not a directory"):
        _r10_sign(plan_dir, plan_id, a1, feature_id=feature_id, child=True)
    assert _r10_tree(plan_dir) == before
    assert not signoff_writer.signoff_path(plan_dir, plan_id).exists()
    assert not signoff_writer.charter_compliance_path(plan_dir, plan_id).exists()


def test_dpn012b_supervisor_stray_file_is_caught_signoff_not_written(
    repo: Path, captured: list[Any]
) -> None:
    """The writer's refusal is the exception type the supervisor catches
    (``SignoffWriteError``): the volley ends ``blocked`` instead of crashing."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _clear_pre_merge(plan_dir, plan_id)
    stray = _r11_stray_file(plan_dir)
    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert result.final_status == "blocked"
    assert "SignoffWriteError" in result.reason
    assert stray.read_bytes() == b"stray, not a directory\n"
    assert not signoff_writer.signoff_path(plan_dir, plan_id).exists()


@pytest.mark.parametrize("state", ["no_signoff", "valid_plan_level"])
def test_dpn012b_finalizer_stray_file_refused_signoff_unreadable(repo: Path, state: str) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    if state == "valid_plan_level":
        _r10_sign(plan_dir, plan_id, a1, feature_id=None)
    stray = _r11_stray_file(plan_dir)
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_unreadable")
    assert stray.read_bytes() == b"stray, not a directory\n"


def test_dpn012b_repair_writer_error_becomes_signoff_unreadable(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``SignoffWriteError`` from the writer escapes the finalizer."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    _r10_volley(plan_dir, plan_id, "F001")
    _clear_pre_merge(plan_dir, plan_id)

    def _refuse(**_kwargs: Any) -> Path:
        raise signoff_writer.SignoffWriteError("injected writer refusal")

    monkeypatch.setattr(signoff_writer, "write_signoff", _refuse)
    _r10_assert_refused(plan_dir, plan_id, "signoff_unreadable")


# Fix 3 — a symlinked feature-signoffs/ directory ────────────────────────


def _r11_dir_bytes(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("target", ["dir_with_valid_evidence", "dangling"])
def test_dpn012b_finalizer_symlinked_feature_dir_refused(repo: Path, target: str) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=False)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    _r10_sign(plan_dir, plan_id, a1, feature_id="F001")
    real = signoff_writer.feature_signoff_dir(plan_dir)
    outside = repo.parent / "outside-feature-signoffs"
    os.rename(real, outside)
    if target == "dangling":
        os.symlink(repo.parent / "missing-feature-signoffs", real)
    else:
        os.symlink(outside, real)
        assert _r10_fsig(plan_dir, plan_id).is_file()  # valid evidence readable through it
    outside_before = _r11_dir_bytes(outside)
    _clear_pre_merge(plan_dir, plan_id)
    _r10_assert_refused(plan_dir, plan_id, "signoff_unreadable")
    assert _r11_dir_bytes(outside) == outside_before
    assert real.is_symlink()


@pytest.mark.parametrize("target", ["dir", "dangling"])
def test_dpn012b_writer_symlinked_feature_dir_refused_target_unchanged(repo: Path, target: str) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=True)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    outside = repo.parent / "outside-feature-signoffs"
    outside.mkdir()
    (outside / "keep.txt").write_bytes(b"untouched\n")
    link = signoff_writer.feature_signoff_dir(plan_dir)
    os.symlink(outside if target == "dir" else repo.parent / "missing-dir", link)
    before = _r10_tree(plan_dir)
    # Only the symlink refusal says "is a symlink; refusing" (the tmp dir name
    # itself contains "symlinked", so a bare "symlink" match proves nothing).
    with pytest.raises(signoff_writer.SignoffWriteError, match=r"is a symlink; refusing"):
        _r10_sign(plan_dir, plan_id, a1, feature_id="F001", child=True)
    assert _r11_dir_bytes(outside) == {"keep.txt": b"untouched\n"}
    assert sorted(os.listdir(outside)) == ["keep.txt"]
    assert _r10_tree(plan_dir) == before
    assert not signoff_writer.signoff_path(plan_dir, plan_id).exists()
    assert link.is_symlink()


# Fix 4 — feature ids that differ only by case collide ───────────────────


@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
def test_dpn012b_writer_case_colliding_feature_id_refused(repo: Path, child: bool) -> None:
    plan_dir, plan_id = _r10_plan(repo, child=child)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    _r10_sign(plan_dir, plan_id, a1, feature_id="F1", child=child)
    f1 = _r10_fsig(plan_dir, plan_id, "F1")
    assert f1.name in os.listdir(f1.parent)
    before = _r10_tree(plan_dir)
    with pytest.raises(signoff_writer.SignoffWriteError, match="case-collides"):
        _r10_sign(plan_dir, plan_id, a1, feature_id="f1", child=child)
    assert _r10_tree(plan_dir) == before
    assert f1.name in os.listdir(f1.parent)
    assert _r10_fsig(plan_dir, plan_id, "f1").name not in os.listdir(f1.parent)


def test_dpn012b_finalizer_case_colliding_feature_evidence_refused(repo: Path) -> None:
    """Finalizing ``F001`` while only the case-colliding ``f001`` per-feature
    evidence exists is refused ``signoff_unreadable`` naming the collision —
    never accepted as F001's (case-insensitive volume: rule a would read it)
    nor repaired around (case-sensitive volume: rule d would repair). Plan
    feature ids must match ``^F\\d{3}$``, so the loadable id is ``F001`` and
    the stray evidence is the lower-cased one."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    _r10_sign(plan_dir, plan_id, a1, feature_id="f001")
    signoff_writer.signoff_path(plan_dir, plan_id).unlink()
    stray_name = _r10_fsig(plan_dir, plan_id, "f001").name
    assert os.listdir(signoff_writer.feature_signoff_dir(plan_dir)) == [stray_name]
    _clear_pre_merge(plan_dir, plan_id)
    before_tree = _r10_tree(plan_dir)
    before_features = (plan_dir / "features.json").read_bytes()
    with pytest.raises(signed_off_finalizer.FinalizeError) as exc:
        signed_off_finalizer.finalize_signed_off_feature(
            plan_dir, plan_id=plan_id, feature_id="F001"
        )
    assert exc.value.code == "signoff_unreadable", (exc.value.code, str(exc.value))
    assert "case-collides" in str(exc.value) and stray_name in str(exc.value)
    assert _r10_passes(plan_dir, "F001") is False
    assert (plan_dir / "features.json").read_bytes() == before_features
    assert _r10_tree(plan_dir) == before_tree


# Item 6 (Thanos ruling) — branch (d) refuses an undatable auditor envelope ─

_DPN012B_FUTURE = object()


@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
@pytest.mark.parametrize(
    "completed_at",
    [None, "2026-11-12T10:00:00", "2026-11-12", "not-a-timestamp", _DPN012B_FUTURE],
    ids=["missing", "zone_less", "date_only", "unparseable", "future"],
)
def test_dpn012b_branch_d_undatable_auditor_envelope_refused_nothing_written(
    repo: Path, child: bool, completed_at: Any
) -> None:
    """No signoff anywhere (rule d) + a signed_off auditor envelope whose
    ``completed_at`` cannot be dated — or is later than the finalizer's clock
    (branch (c)'s full rule): refused ``signoff_stale`` before any repair — no
    plan-level or per-feature signoff / side-car written, no
    ``feature-signoffs/`` created, no ``passes`` flipped."""
    plan_dir, plan_id = _r10_plan(repo, child=child)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    data = json.loads(a1.read_text())
    if completed_at is None:
        del data["completed_at"]
    elif completed_at is _DPN012B_FUTURE:
        future = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(hours=1)
        data["completed_at"] = future.isoformat().replace("+00:00", "Z")
    else:
        data["completed_at"] = completed_at
    a1.write_text(json.dumps(data))
    # The edited envelope is still the one the finalizer selects.
    audit_paths = signed_off_finalizer.closeout._audit_paths_for_feature(plan_dir.resolve(), "F001")
    assert signed_off_finalizer._latest_auditor_path(audit_paths) == a1.resolve()
    assert signed_off_finalizer.closeout._latest_auditor_envelope(audit_paths) == data
    _clear_pre_merge(plan_dir, plan_id)
    plan_sig = signoff_writer.signoff_path(plan_dir, plan_id)
    plan_side = signoff_writer.charter_compliance_path(plan_dir, plan_id)
    fdir = signoff_writer.feature_signoff_dir(plan_dir)
    assert not plan_sig.exists() and not plan_side.exists() and not os.path.lexists(fdir)

    _r10_assert_refused(plan_dir, plan_id, "signoff_stale")

    assert not plan_sig.exists() and not plan_side.exists()
    assert not os.path.lexists(fdir)
    assert _r10_passes(plan_dir, "F002") is False


@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
def test_dpn012b_branch_d_past_zone_aware_completed_at_still_repairs(repo: Path, child: bool) -> None:
    """Control: no signoff anywhere (rule d) + a signed_off auditor envelope
    with an explicit zone-aware completed_at in the past — branch (d) still
    repairs both pairs and flips passes; a re-run is idempotent."""
    plan_dir, plan_id = _r10_plan(repo, child=child)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    data = json.loads(a1.read_text())
    data["completed_at"] = _base_time().isoformat().replace("+00:00", "Z")
    a1.write_text(json.dumps(data))
    _clear_pre_merge(plan_dir, plan_id)
    assert not signoff_writer.signoff_path(plan_dir, plan_id).exists()

    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")

    assert fin.signoff_repaired is True and fin.features_passes_flipped is True
    assert fin.signoff_path == _r10_fsig(plan_dir, plan_id)
    assert _r10_passes(plan_dir, "F001") is True
    assert signoff_writer.signoff_path(plan_dir, plan_id).is_file()
    again = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert again.already_finalized is True


@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
def test_dpn012b_branch_d_single_clock_read(
    repo: Path, child: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 6 (Codex finding at b1b9daa5) — branch (d) must stamp the
    decided_at its freshness guard checked (one clock read), so a backward
    clock step between guard and write cannot persist a plan-level /
    per-feature signoff the next finalize calls stale."""
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    t = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    t_iso = t.strftime(fmt)
    plan_dir, plan_id = _r10_plan(repo, child=child)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    data = json.loads(a1.read_text())
    data["completed_at"] = (t - dt.timedelta(hours=1)).strftime(fmt)
    a1.write_text(json.dumps(data))
    _clear_pre_merge(plan_dir, plan_id)
    plan_sig = signoff_writer.signoff_path(plan_dir, plan_id)
    assert not plan_sig.exists()
    assert not os.path.lexists(signoff_writer.feature_signoff_dir(plan_dir))
    calls: list[str] = []

    def fake_now_iso() -> str:
        value = t_iso if not calls else (t - dt.timedelta(hours=2)).strftime(fmt)
        calls.append(value)
        return value

    monkeypatch.setattr(signoff_writer, "_now_iso", fake_now_iso)
    # The guard must check the very value the repair stamps.
    checked: list[str] = []
    real_freshness_problem = signed_off_finalizer._freshness_problem

    def spy_freshness_problem(
        envelope: dict[str, Any], signoff: dict[str, Any], auditor_path: Path | None
    ) -> str | None:
        checked.append(signoff["decided_at"])
        return real_freshness_problem(envelope, signoff, auditor_path)

    monkeypatch.setattr(signed_off_finalizer, "_freshness_problem", spy_freshness_problem)

    fin = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert fin.signoff_repaired is True
    assert fin.features_passes_flipped is True
    assert fin.signoff_path == _r10_fsig(plan_dir, plan_id)
    assert json.loads(_r10_fsig(plan_dir, plan_id).read_text())["decided_at"] == t_iso
    assert json.loads(plan_sig.read_text())["decided_at"] == t_iso
    assert _r10_passes(plan_dir, "F001") is True
    assert calls == [t_iso]
    assert checked == [t_iso]
    again = signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert again.already_finalized is True


# ───────── DPN-012b review round 2 (Sentinel 5887156723) — no symlink is followed ─────────
#
# Every case asserts the refusal AND that nothing is written outside the plan
# tree: a sibling "outside" directory under tmp_path stays identical (files,
# directories and links), and no ``passes`` flips.


def _rr2_snapshot(root: Path) -> dict[str, Any]:
    """Every entry under ``root`` (links NOT followed): files → bytes, dirs →
    ``"<dir>"``, symlinks → ``("<link>", target)``."""
    snap: dict[str, Any] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            rel = str(p.relative_to(root))
            if p.is_symlink():
                snap[rel] = ("<link>", os.readlink(p))
            elif p.is_dir():
                snap[rel] = "<dir>"
            else:
                snap[rel] = p.read_bytes()
    return snap


def _rr2_outside(repo: Path) -> Path:
    outside = repo.parent / "rr2-outside"
    outside.mkdir()
    (outside / "keep.txt").write_bytes(b"untouched\n")
    return outside


def _rr2_finalize_refused(plan_dir: Path, plan_id: str, code: str) -> signed_off_finalizer.FinalizeError:
    before_features = (plan_dir / "features.json").read_bytes()
    with pytest.raises(signed_off_finalizer.FinalizeError) as exc:
        signed_off_finalizer.finalize_signed_off_feature(plan_dir, plan_id=plan_id, feature_id="F001")
    assert exc.value.code == code, (exc.value.code, str(exc.value))
    assert _r10_passes(plan_dir, "F001") is False
    assert (plan_dir / "features.json").read_bytes() == before_features
    return exc.value


@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
@pytest.mark.parametrize("actor", ["writer_per_feature", "writer_plan_level_only", "finalizer"])
def test_dpn012b_rr2_linked_audit_parent_refused_nothing_outside(
    repo: Path, actor: str, child: bool
) -> None:
    """(a) ``audit/`` itself is a symlink to a directory outside the plan tree
    (holding the plan's real audit envelopes + gate state). The per-feature
    write, the plan-level-only write and the finalizer all refuse; nothing
    is written through the link."""
    plan_dir, plan_id = _r10_plan(repo, child=child)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    _clear_pre_merge(plan_dir, plan_id)
    outside = _rr2_outside(repo)
    os.rename(plan_dir / "audit", outside / "audit")
    os.symlink(outside / "audit", plan_dir / "audit")
    assert a1.is_file()  # the envelope is still readable through the link
    before = _rr2_snapshot(outside)

    if actor == "finalizer":
        _rr2_finalize_refused(plan_dir, plan_id, "signoff_unreadable")
    else:
        fid = "F001" if actor == "writer_per_feature" else None
        with pytest.raises(signoff_writer.SignoffWriteError, match=r"is a symlink; refusing"):
            _r10_sign(plan_dir, plan_id, a1, feature_id=fid, child=child)

    assert _rr2_snapshot(outside) == before
    assert (plan_dir / "audit").is_symlink()
    assert _r10_passes(plan_dir, "F001") is False


@pytest.mark.parametrize("swapped", ["audit", "feature-signoffs"])
@pytest.mark.parametrize("child", [False, True], ids=["top", "child"])
def test_dpn012b_rr2_swap_race_link_after_check_writes_nothing_outside(
    repo: Path, monkeypatch: pytest.MonkeyPatch, swapped: str, child: bool
) -> None:
    """(b) A link swapped in AFTER the writer's up-front directory check and
    BEFORE any evidence byte lands: the hook wraps
    ``signoff_writer.build_signoff_dict``, which ``write_signoff`` calls after
    its refusal checks (and, at this head, after the evidence directories are
    opened no-follow and held) and before the first temp file is created. On
    its return the real ``audit/`` (or ``feature-signoffs/``) is renamed aside
    and a symlink to an outside directory is put in its place. Nothing may
    land outside: the write either refuses or lands in the directory it
    checked (now the renamed-aside one)."""
    plan_dir, plan_id = _r10_plan(repo, child=child)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    fdir = signoff_writer.feature_signoff_dir(plan_dir)
    if swapped == "feature-signoffs":
        fdir.mkdir()
    original = plan_dir / "audit" if swapped == "audit" else fdir
    aside = original.with_name(original.name + "-aside")
    outside = _rr2_outside(repo)
    before = _rr2_snapshot(outside)
    real_build = signoff_writer.build_signoff_dict
    swaps: list[Path] = []

    def _build_then_swap(**kwargs: Any) -> dict[str, Any]:
        payload = real_build(**kwargs)
        if not swaps:
            os.rename(original, aside)
            os.symlink(outside, original)
            swaps.append(original)
        return payload

    monkeypatch.setattr(signoff_writer, "build_signoff_dict", _build_then_swap)
    try:
        _r10_sign(plan_dir, plan_id, a1, feature_id="F001", child=child)
    except signoff_writer.SignoffWriteError:
        pass

    assert swaps == [original]
    assert _rr2_snapshot(outside) == before
    assert original.is_symlink() and Path(os.readlink(original)) == outside


@pytest.mark.parametrize("actor", ["finalizer", "writer"])
def test_dpn012b_rr2_linked_feature_signoff_file_refused(repo: Path, actor: str) -> None:
    """(c) The per-feature signoff FILE is a symlink to a valid signoff copy
    outside the tree. The finalizer refuses ``signoff_unreadable`` (never
    reads rule (a) evidence through it); the writer refuses rather than
    silently replacing the link; the outside target is unchanged."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    _r10_sign(plan_dir, plan_id, a1, feature_id="F001")
    _clear_pre_merge(plan_dir, plan_id)
    outside = _rr2_outside(repo)
    fsig = _r10_fsig(plan_dir, plan_id)
    os.rename(fsig, outside / fsig.name)
    os.symlink(outside / fsig.name, fsig)
    before = _rr2_snapshot(outside)

    if actor == "finalizer":
        _rr2_finalize_refused(plan_dir, plan_id, "signoff_unreadable")
    else:
        with pytest.raises(signoff_writer.SignoffWriteError, match=r"is a symlink; refusing"):
            _r10_sign(plan_dir, plan_id, a1, feature_id="F001")

    assert _rr2_snapshot(outside) == before
    assert fsig.is_symlink()
    assert _r10_passes(plan_dir, "F001") is False


@pytest.mark.parametrize("actor", ["finalizer", "writer"])
def test_dpn012b_rr2_linked_feature_side_car_file_refused(repo: Path, actor: str) -> None:
    """(d) Child plan: the per-feature charter-compliance side-car FILE is a
    symlink to a valid side-car outside the tree. The finalizer refuses
    ``signoff_unreadable`` (the no-follow read refuses the link itself —
    a link is not a missing side-car, so not ``child_signoff_missing``); the
    writer refuses; the outside target is unchanged."""
    plan_dir, plan_id = _r10_plan(repo, child=True)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    _r10_sign(plan_dir, plan_id, a1, feature_id="F001", child=True)
    _clear_pre_merge(plan_dir, plan_id)
    outside = _rr2_outside(repo)
    fside = _r10_fside(plan_dir, plan_id)
    os.rename(fside, outside / fside.name)
    os.symlink(outside / fside.name, fside)
    before = _rr2_snapshot(outside)

    if actor == "finalizer":
        _rr2_finalize_refused(plan_dir, plan_id, "signoff_unreadable")
    else:
        with pytest.raises(signoff_writer.SignoffWriteError, match=r"is a symlink; refusing"):
            _r10_sign(plan_dir, plan_id, a1, feature_id="F001", child=True)

    assert _rr2_snapshot(outside) == before
    assert fside.is_symlink()
    assert _r10_passes(plan_dir, "F001") is False


@pytest.mark.parametrize("actor", ["finalizer", "writer"])
def test_dpn012b_rr2_linked_plan_level_signoff_refused(repo: Path, actor: str) -> None:
    """(e) The plan-level ``signoff-<plan>.json`` is a symlink to a valid
    signoff outside the tree (no per-feature evidence). A plan-level-only
    write refuses and leaves the outside file unchanged; the finalizer's
    validation of it refuses ``signoff_unreadable``."""
    plan_dir, plan_id = _r10_plan(repo, child=False)
    a1 = _r10_volley(plan_dir, plan_id, "F001")
    sp = _r10_sign(plan_dir, plan_id, a1, feature_id=None)
    _clear_pre_merge(plan_dir, plan_id)
    assert not os.path.lexists(signoff_writer.feature_signoff_dir(plan_dir))
    outside = _rr2_outside(repo)
    os.rename(sp, outside / sp.name)
    os.symlink(outside / sp.name, sp)
    before = _rr2_snapshot(outside)

    if actor == "finalizer":
        _rr2_finalize_refused(plan_dir, plan_id, "signoff_unreadable")
    else:
        with pytest.raises(signoff_writer.SignoffWriteError, match=r"is a symlink; refusing"):
            _r10_sign(plan_dir, plan_id, a1, feature_id=None)

    assert _rr2_snapshot(outside) == before
    assert sp.is_symlink()
    assert _r10_passes(plan_dir, "F001") is False
