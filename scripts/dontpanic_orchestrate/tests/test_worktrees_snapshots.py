"""Worktree Isolation v0 F002 — gate-time binding snapshots.

The capture helper + the real lock_plan gate path on a bound temp plan, the
no-binding regression (additive), and the corrupt-registry fail-closed rule
for evidence paths.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import worktrees as wt  # noqa: E402
from dontpanic_orchestrate.sufficiency_gate import lock_plan  # noqa: E402

PLAN_ID = "2026-06-10-002-feat-worktree-isolation-v0"


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "dp-home"
    h.mkdir()
    monkeypatch.setenv("DONTPANIC_HOME", str(h))
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    return h


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-q", "-b", "main", cwd=r)
    _git("config", "user.email", "t@e.c", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    (r / "README.md").write_text("x\n")
    _git("add", ".", cwd=r)
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init", cwd=r)
    plan = r / "docs" / "plans" / PLAN_ID
    plan.mkdir(parents=True)
    # a draft plan with NO goal_type: the sufficiency gate is a silent no-op,
    # so lock_plan exercises the REAL lock body without any paid call.
    (plan / "plan.md").write_text(
        "---\nid: x\ntitle: t\nstatus: draft\n---\n\nbody\n"
    )
    return r


def _plan_dir(repo: Path) -> Path:
    return repo / "docs" / "plans" / PLAN_ID


def _snapshots(plan_dir: Path) -> list[dict]:
    path = plan_dir / "audit" / wt.SNAPSHOT_FILENAME
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestCaptureHelper:
    def test_bound_plan_snapshot_lands_with_recorded_values(self, home, repo):
        wt.create_worktree(_plan_dir(repo))
        binding = wt.get_binding(PLAN_ID)
        snap = wt.capture_binding_snapshot(_plan_dir(repo), "plan lock")
        assert snap["worktree_path"] == binding["worktree_path"]
        assert snap["base_ref"] == binding["base_ref"]
        assert snap["base_sha"] == binding["base_sha"]
        assert snap["branch"] == binding["branch"]
        assert snap["owner_actor"] == binding["owner_actor"]
        assert snap["command"] == "plan lock" and snap["captured_at"]
        rows = _snapshots(_plan_dir(repo))
        assert len(rows) == 1 and rows[0] == snap

    def test_unbound_plan_writes_nothing(self, home, repo):
        assert wt.capture_binding_snapshot(_plan_dir(repo), "plan lock") is None
        assert _snapshots(_plan_dir(repo)) == []

    def test_corrupt_registry_fails_closed(self, home, repo):
        wt.registry_path().parent.mkdir(parents=True, exist_ok=True)
        wt.registry_path().write_text("not-json{")
        with pytest.raises(wt.RegistryCorruptError):
            wt.capture_binding_snapshot(_plan_dir(repo), "plan lock")
        assert _snapshots(_plan_dir(repo)) == []


class TestGatePathWiring:
    def test_lock_plan_captures_snapshot_when_bound(self, home, repo):
        wt.create_worktree(_plan_dir(repo))
        lock_plan(_plan_dir(repo))
        rows = _snapshots(_plan_dir(repo))
        assert len(rows) == 1 and rows[0]["command"] == "plan lock"
        assert "status: active" in (_plan_dir(repo) / "plan.md").read_text()

    def test_lock_plan_unbound_behaves_exactly_as_today(self, home, repo):
        lock_plan(_plan_dir(repo))
        assert _snapshots(_plan_dir(repo)) == []
        assert "status: active" in (_plan_dir(repo) / "plan.md").read_text()

    def test_lock_plan_refuses_on_corrupt_registry_before_side_effects(self, home, repo):
        wt.registry_path().parent.mkdir(parents=True, exist_ok=True)
        wt.registry_path().write_text("corrupt{")
        with pytest.raises(wt.RegistryCorruptError):
            lock_plan(_plan_dir(repo))
        # no side effect: status untouched
        assert "status: draft" in (_plan_dir(repo) / "plan.md").read_text()

    def test_dispatch_seam_calls_capture(self, home, repo):
        # the supervisor wiring calls capture_binding_snapshot before
        # gate-state reconciliation; assert the call site exists and targets
        # the helper (source-level wiring guard, no live dispatch).
        import inspect
        from dontpanic_orchestrate import supervisor

        src = inspect.getsource(supervisor.dispatch_volley)
        assert "capture_binding_snapshot" in src
        # the capture CALL must precede the gate-state reconciliation CALL
        # (match the invocation with its paren — a comment upstream also
        # mentions the reconcile helper by name)
        assert src.index("_wt_capture(") < src.index("_reconcile_gate_state_or_raise(")
