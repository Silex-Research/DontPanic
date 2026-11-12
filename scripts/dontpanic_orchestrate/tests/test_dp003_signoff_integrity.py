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

    # Side-car was written first; the signoff (and any temp file) is absent.
    assert signoff_writer.charter_compliance_path(plan_dir, CHILD_ID).is_file()
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
