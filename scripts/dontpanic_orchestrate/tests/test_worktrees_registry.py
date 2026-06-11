"""Worktree Isolation v0 (plan 2026-06-10-002) — F001 registry, F004
binding_health + status model, F006 create.

All tests run against temp git repos and a temp DONTPANIC_HOME; no network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import worktrees as wt  # noqa: E402


# ──────────────────────────────  fixtures  ──────────────────────────────


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
    monkeypatch.delenv("DONTPANIC_ACTOR", raising=False)
    return h


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo-a"
    r.mkdir()
    _git("init", "-q", "-b", "main", cwd=r)
    _git("config", "user.email", "t@example.com", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    (r / "README.md").write_text("x\n")
    _git("add", ".", cwd=r)
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init", cwd=r)
    plan = r / "docs" / "plans" / "2026-06-10-002-feat-worktree-isolation-v0"
    plan.mkdir(parents=True)
    (plan / "plan.md").write_text("---\nid: x\n---\n")
    return r


def _plan_dir(repo: Path) -> Path:
    return repo / "docs" / "plans" / "2026-06-10-002-feat-worktree-isolation-v0"


PLAN_ID = "2026-06-10-002-feat-worktree-isolation-v0"


# ──────────────────────────────  F001: registry  ──────────────────────────────


class TestRegistry:
    def _binding(self, repo: Path, **over):
        base = dict(
            plan_id=PLAN_ID,
            repo_root=str(repo),
            worktree_path=str(repo.parent / "wt"),
            branch=f"plan/{PLAN_ID}",
            base_ref="main",
            base_sha="0" * 40,
            owner_actor="tester@host",
            created_at="2026-06-11T00:00:00Z",
        )
        base.update(over)
        return base

    def test_round_trip(self, home, repo):
        wt.add_binding(self._binding(repo))
        got = wt.get_binding(PLAN_ID)
        assert got["worktree_path"] == str(repo.parent / "wt")
        assert wt.list_bindings()[0]["plan_id"] == PLAN_ID

    def test_double_bind_refused(self, home, repo):
        wt.add_binding(self._binding(repo))
        with pytest.raises(wt.WorktreeError, match="already bound"):
            wt.add_binding(self._binding(repo, worktree_path=str(repo.parent / "other")))

    def test_path_collision_refused(self, home, repo):
        wt.add_binding(self._binding(repo))
        with pytest.raises(wt.WorktreeError, match="claimed"):
            wt.add_binding(self._binding(repo, plan_id="other-plan"))

    def test_invalid_file_degrades_for_read_only(self, home, repo):
        wt.registry_path().write_text("{ not json")
        loaded = wt.load_registry()
        assert loaded.bindings == {} and loaded.corrupt is True

    def test_strict_load_raises_on_corrupt(self, home, repo):
        wt.registry_path().write_text("{ not json")
        with pytest.raises(wt.RegistryCorruptError):
            wt.load_registry_strict()

    def test_home_resolution_precedence(self, tmp_path, monkeypatch):
        a = tmp_path / "a"
        a.mkdir()
        monkeypatch.setenv("DONTPANIC_HOME", str(a))
        assert str(wt.registry_path()).startswith(str(a))

    def test_atomic_write_preserves_prior_entries(self, home, repo, monkeypatch):
        wt.add_binding(self._binding(repo))
        before = wt.registry_path().read_text()

        # kill the write mid-flight: make rename explode once
        real_replace = os.replace
        def boom(src, dst):
            raise OSError("disk full")
        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            wt.add_binding(self._binding(repo, plan_id="other", worktree_path=str(repo.parent / "w2")))
        monkeypatch.setattr(os, "replace", real_replace)
        # pre-existing content intact, no truncation
        assert wt.registry_path().read_text() == before
        assert wt.get_binding(PLAN_ID) is not None

    def test_owner_actor_resolution(self, home, monkeypatch):
        monkeypatch.setenv("DONTPANIC_ACTOR", "agent-7")
        assert wt.resolve_actor() == "agent-7"
        monkeypatch.delenv("DONTPANIC_ACTOR")
        assert "@" in wt.resolve_actor()


# ──────────────────────────────  F006: create  ──────────────────────────────


class TestCreate:
    def test_create_binds_and_checks_out_base_sha(self, home, repo):
        result = wt.create_worktree(_plan_dir(repo))
        b = wt.get_binding(PLAN_ID)
        assert b is not None
        p = Path(b["worktree_path"])
        assert p.is_dir() and (p / "README.md").is_file()
        assert b["branch"] == f"plan/{PLAN_ID}"
        assert len(b["base_sha"]) == 40
        # worktree is AT base_sha
        assert _git("rev-parse", "HEAD", cwd=p) == b["base_sha"]
        # path is repo-key qualified and outside the repo
        assert not str(p).startswith(str(repo))
        assert result["base_sha"] == b["base_sha"]

    def test_default_base_tracks_default_branch_not_invoking_head(self, home, repo):
        main_sha = _git("rev-parse", "main", cwd=repo)
        _git("checkout", "-qb", "divergent", cwd=repo)
        (repo / "z.txt").write_text("z\n")
        _git("add", ".", cwd=repo)
        _git("-c", "commit.gpgsign=false", "commit", "-qm", "div", cwd=repo)
        wt.create_worktree(_plan_dir(repo))
        assert wt.get_binding(PLAN_ID)["base_sha"] == main_sha

    def test_explicit_base_recorded(self, home, repo):
        sha = _git("rev-parse", "main", cwd=repo)
        wt.create_worktree(_plan_dir(repo), base="main")
        b = wt.get_binding(PLAN_ID)
        assert b["base_ref"] == "main" and b["base_sha"] == sha

    def test_unresolvable_base_refuses_before_creation(self, home, repo):
        with pytest.raises(wt.WorktreeError, match="base"):
            wt.create_worktree(_plan_dir(repo), base="no-such-ref")
        assert wt.get_binding(PLAN_ID) is None

    def test_double_bind_refused(self, home, repo):
        wt.create_worktree(_plan_dir(repo))
        with pytest.raises(wt.WorktreeError, match="already bound"):
            wt.create_worktree(_plan_dir(repo))

    def test_occupied_path_refused_untouched(self, home, repo):
        target = wt.worktree_target_path(repo, PLAN_ID)
        target.mkdir(parents=True)
        (target / "keep.txt").write_text("keep")
        with pytest.raises(wt.WorktreeError, match="exists"):
            wt.create_worktree(_plan_dir(repo))
        assert (target / "keep.txt").read_text() == "keep"
        assert wt.get_binding(PLAN_ID) is None

    def test_preexisting_branch_refused(self, home, repo):
        _git("branch", f"plan/{PLAN_ID}", cwd=repo)
        with pytest.raises(wt.WorktreeError, match="branch"):
            wt.create_worktree(_plan_dir(repo))

    def test_repo_root_from_plan_dir_not_invoking_cwd(self, home, repo, tmp_path, monkeypatch):
        other = tmp_path / "unrelated"
        other.mkdir()
        _git("init", "-q", "-b", "main", cwd=other)
        monkeypatch.chdir(other)
        wt.create_worktree(_plan_dir(repo))
        assert Path(wt.get_binding(PLAN_ID)["repo_root"]) == repo.resolve()

    def test_same_basename_repos_do_not_collide(self, home, tmp_path):
        paths = []
        for parent in ("p1", "p2"):
            r = tmp_path / parent / "same-name"
            r.mkdir(parents=True)
            _git("init", "-q", "-b", "main", cwd=r)
            _git("config", "user.email", "t@e.c", cwd=r)
            _git("config", "user.name", "t", cwd=r)
            (r / "f").write_text("x")
            _git("add", ".", cwd=r)
            _git("-c", "commit.gpgsign=false", "commit", "-qm", "i", cwd=r)
            paths.append(wt.worktree_target_path(r, "plan-x"))
        assert paths[0] != paths[1]

    def test_registry_write_failure_rolls_back(self, home, repo, monkeypatch):
        real = wt.add_binding
        def boom(*a, **k):
            raise OSError("registry write failed")
        monkeypatch.setattr(wt, "add_binding", boom)
        with pytest.raises(wt.WorktreeError, match="rolled back|registry"):
            wt.create_worktree(_plan_dir(repo))
        monkeypatch.setattr(wt, "add_binding", real)
        target = wt.worktree_target_path(repo, PLAN_ID)
        assert not target.exists()
        branches = _git("branch", "--list", f"plan/{PLAN_ID}", cwd=repo)
        assert branches == ""

    def test_target_inside_repo_refused(self, home, repo, monkeypatch):
        monkeypatch.setenv("DONTPANIC_HOME", str(repo / ".dp-home"))
        with pytest.raises(wt.WorktreeError, match="inside"):
            wt.create_worktree(_plan_dir(repo))

    def test_corrupt_registry_refuses_create(self, home, repo):
        wt.registry_path().parent.mkdir(parents=True, exist_ok=True)
        wt.registry_path().write_text("garbage{")
        with pytest.raises(wt.RegistryCorruptError):
            wt.create_worktree(_plan_dir(repo))


# ──────────────────────────────  F004: binding_health + model  ──────────────────────────────


class TestBindingHealth:
    def test_healthy(self, home, repo):
        wt.create_worktree(_plan_dir(repo))
        b = wt.get_binding(PLAN_ID)
        ok, reason = wt.binding_health(b)
        assert ok and reason is None

    def test_missing_path(self, home, repo):
        wt.create_worktree(_plan_dir(repo))
        b = dict(wt.get_binding(PLAN_ID), worktree_path=str(repo.parent / "gone"))
        ok, reason = wt.binding_health(b)
        assert not ok and "exist" in reason

    def test_not_a_worktree(self, home, repo, tmp_path):
        wt.create_worktree(_plan_dir(repo))
        plain = tmp_path / "plain"
        plain.mkdir()
        b = dict(wt.get_binding(PLAN_ID), worktree_path=str(plain))
        ok, reason = wt.binding_health(b)
        assert not ok

    def test_wrong_repo_same_branch(self, home, repo, tmp_path):
        # an unrelated repo at the recorded path, on the recorded branch name
        wt.create_worktree(_plan_dir(repo))
        b = wt.get_binding(PLAN_ID)
        impostor = tmp_path / "impostor"
        impostor.mkdir()
        _git("init", "-q", "-b", b["branch"], cwd=impostor)
        _git("config", "user.email", "t@e.c", cwd=impostor)
        _git("config", "user.name", "t", cwd=impostor)
        (impostor / "f").write_text("x")
        _git("add", ".", cwd=impostor)
        _git("-c", "commit.gpgsign=false", "commit", "-qm", "i", cwd=impostor)
        fake = dict(b, worktree_path=str(impostor))
        ok, reason = wt.binding_health(fake)
        assert not ok and ("belong" in reason or "worktree" in reason)

    def test_branch_drift(self, home, repo):
        wt.create_worktree(_plan_dir(repo))
        b = wt.get_binding(PLAN_ID)
        _git("checkout", "-qb", "elsewhere", cwd=Path(b["worktree_path"]))
        ok, reason = wt.binding_health(b)
        assert not ok and "branch" in reason

    def test_probe_error_is_unhealthy(self, home, repo, monkeypatch):
        wt.create_worktree(_plan_dir(repo))
        b = wt.get_binding(PLAN_ID)
        def boom(*a, **k):
            raise subprocess.SubprocessError("probe failed")
        monkeypatch.setattr(wt.subprocess, "run", boom)
        ok, reason = wt.binding_health(b)
        assert not ok


class TestStatusModel:
    def test_clean_dirty_untracked(self, home, repo):
        wt.create_worktree(_plan_dir(repo))
        rows = wt.build_status_model()
        row = rows["bindings"][0]
        assert row["dirty"] is False and row["untracked_count"] == 0
        p = Path(wt.get_binding(PLAN_ID)["worktree_path"])
        (p / "new.txt").write_text("n")
        row = wt.build_status_model()["bindings"][0]
        assert row["dirty"] is True and row["untracked_count"] == 1

    def test_untracked_dir_counts_as_one(self, home, repo):
        wt.create_worktree(_plan_dir(repo))
        p = Path(wt.get_binding(PLAN_ID)["worktree_path"])
        d = p / "newdir"
        d.mkdir()
        (d / "a").write_text("a")
        (d / "b").write_text("b")
        row = wt.build_status_model()["bindings"][0]
        assert row["untracked_count"] == 1

    def test_unhealthy_renders_nulls_with_reason(self, home, repo):
        wt.create_worktree(_plan_dir(repo))
        b = wt.get_binding(PLAN_ID)
        _git("checkout", "-qb", "drifted", cwd=Path(b["worktree_path"]))
        row = wt.build_status_model()["bindings"][0]
        assert row["dirty"] is None and row["untracked_count"] is None
        assert row["health_reason"] and "branch" in row["health_reason"]
        assert row["current_branch"] == "drifted"
        assert row["branch"] == b["branch"]

    def test_corrupt_registry_flag(self, home, repo):
        wt.registry_path().parent.mkdir(parents=True, exist_ok=True)
        wt.registry_path().write_text("oops{")
        model = wt.build_status_model()
        assert model["registry_corrupt"] is True and model["bindings"] == []

    def test_broken_binding_rendered_not_dropped(self, home, repo):
        wt.create_worktree(_plan_dir(repo))
        import shutil
        shutil.rmtree(wt.get_binding(PLAN_ID)["worktree_path"])
        rows = wt.build_status_model()["bindings"]
        assert len(rows) == 1 and rows[0]["health_reason"]
