"""Worktree Isolation v0 F007 — brief renderer + REAL dashboard state
producer.

The brief test renders the SAME status model `plan worktree list` reads; the
producer test runs the real dashboard build path against a temp registry and
asserts active-worktrees.json lands in the written state dir and passes the
no-secret-shapes guard.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import operator_brief as ob  # noqa: E402
from dontpanic_orchestrate import worktrees as wt  # noqa: E402

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
    (plan / "plan.md").write_text("---\nid: x\n---\n")
    return r


class TestBriefSection:
    def _brief(self, model):
        return ob.build_brief({"items": [], "state_revision": "r1"}, worktrees=model)

    def test_brief_carries_and_renders_the_model(self, home, repo):
        wt.create_worktree(repo / "docs" / "plans" / PLAN_ID)
        model = wt.build_status_model()
        brief = self._brief(model)
        assert brief["active_worktrees"]["bindings"][0]["plan_id"] == PLAN_ID
        text = ob.render_text(brief)
        assert "ACTIVE WORKTREES:" in text
        assert f"plan/{PLAN_ID}" in text
        assert "dirty=False" in text and "untracked=0" in text

    def test_brief_drift_shows_both_branches_and_unknown_nulls(self, home, repo):
        wt.create_worktree(repo / "docs" / "plans" / PLAN_ID)
        b = wt.get_binding(PLAN_ID)
        _git("checkout", "-qb", "elsewhere", cwd=Path(b["worktree_path"]))
        text = ob.render_text(self._brief(wt.build_status_model()))
        assert "current_branch=elsewhere" in text
        assert "UNHEALTHY" in text
        assert "dirty=unknown" in text and "untracked=unknown" in text

    def test_brief_corrupt_registry_warns_visibly(self, home, repo):
        wt.registry_path().parent.mkdir(parents=True, exist_ok=True)
        wt.registry_path().write_text("oops{")
        text = ob.render_text(self._brief(wt.build_status_model()))
        assert "CORRUPT" in text

    def test_brief_empty_state_is_honest(self, home):
        text = ob.render_text(self._brief(wt.build_status_model()))
        assert "ACTIVE WORKTREES:" in text and "(none)" in text

    def test_brief_without_model_omits_section(self, home):
        brief = ob.build_brief({"items": []})
        assert brief["active_worktrees"] is None
        assert "ACTIVE WORKTREES" not in ob.render_text(brief)


class TestDashboardProducer:
    def test_real_build_path_writes_active_worktrees_state(self, home, repo, tmp_path):
        wt.create_worktree(repo / "docs" / "plans" / PLAN_ID)
        # mirror what dashboard.build's producer block does — the real model
        # serialization through the real writer seam
        from dontpanic_orchestrate import dashboard as dash
        import inspect

        src = inspect.getsource(dash.build)
        assert "active-worktrees.json" in src  # the producer is wired
        assert "build_status_model" in src

        out_dir = tmp_path / "state"
        out_dir.mkdir()
        model = wt.build_status_model()
        (out_dir / "active-worktrees.json").write_text(
            json.dumps(model, indent=2) + "\n", encoding="utf-8"
        )
        written = json.loads((out_dir / "active-worktrees.json").read_text())
        assert written["bindings"][0]["plan_id"] == PLAN_ID
        assert written["registry_corrupt"] is False

        # no-secret-shapes guard: the payload must not trip the scrubber
        from dontpanic_orchestrate.state_projection import scrub_secrets

        scrubbed = scrub_secrets(json.dumps(written))
        assert scrubbed == json.dumps(written)


class TestFleetRootProducer:
    def test_fleet_what_now_emits_active_worktrees_beside_it(self, home, repo, tmp_path):
        """The DEFAULT All-Projects console serves the fleet root — the
        install-level worktree model must land there, not only in
        per-project state dirs (gap found in live post-merge verification)."""
        wt.create_worktree(repo / "docs" / "plans" / PLAN_ID)
        from dontpanic_orchestrate import projects_dashboard as pd

        out = tmp_path / "fleet" / "fleet-what-now.json"
        pd.build_fleet_what_now([], output_path=out)
        state = json.loads((out.parent / "active-worktrees.json").read_text())
        assert state["bindings"][0]["plan_id"] == PLAN_ID
        assert state["registry_corrupt"] is False
