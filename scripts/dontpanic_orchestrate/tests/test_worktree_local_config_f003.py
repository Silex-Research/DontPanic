"""Guard-hardening F003 — operator-local config policy across worktrees
(plan 2026-06-11-001, operator policy D003).

Default: declare missing/divergent allowlisted local config explicitly —
never silent divergence in either direction. Opt-in --copy-local-config
copies ONLY allowlisted files and refuses overwrites. NO symlinks at
either end. Files off the allowlist are never copied even if
gitignored-local. All on temp git repos, no network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import worktree_local_config as wlc  # noqa: E402
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
    (r / ".gitignore").write_text("environments.json\nother-local.json\n")
    plan = r / "docs" / "plans" / PLAN_ID
    plan.mkdir(parents=True)
    (plan / "plan.md").write_text("---\nid: x\n---\n")
    _git("add", ".", cwd=r)
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init", cwd=r)
    return r


def _kinds(notices: list[dict]) -> list[tuple[str, str]]:
    return [(n["kind"], n["file"]) for n in notices]


class TestAllowlistConstant:
    def test_allowlist_is_pinned_verbatim(self):
        """Initially exactly one entry: repo-root-relative environments.json,
        pinned as a module constant so tests and implementation cannot
        diverge."""
        assert wlc.LOCAL_CONFIG_ALLOWLIST == ("environments.json",)


class TestDeclareMissing:
    def test_missing_in_worktree_is_declared_with_copy_affordance(self, repo, tmp_path):
        (repo / "environments.json").write_text('{"env": "operator"}\n')
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        notices = wlc.local_config_report(repo, wt_dir)
        assert _kinds(notices) == [("missing", "environments.json")]
        assert "--copy-local-config" in notices[0]["message"]
        assert not (wt_dir / "environments.json").exists()  # default never copies

    def test_source_missing_produces_no_notice_and_never_copies(self, repo, tmp_path):
        """D011 disposition f-d2313c8b5658 discharge: allowlisted file absent
        from repo_root → nothing to declare or propagate, with or without
        the copy flag; a worktree-only copy is left untouched and unreported
        (the policy governs repo_root→worktree propagation only)."""
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        assert wlc.local_config_report(repo, wt_dir) == []
        assert wlc.local_config_report(repo, wt_dir, copy=True) == []
        assert not (wt_dir / "environments.json").exists()
        # worktree-only copy: untouched and unreported in v1
        (wt_dir / "environments.json").write_text('{"only": "here"}\n')
        assert wlc.local_config_report(repo, wt_dir) == []
        assert (wt_dir / "environments.json").read_text() == '{"only": "here"}\n'


class TestDeclareDivergent:
    def test_divergent_content_is_reported_by_default_no_flag(self, repo, tmp_path):
        (repo / "environments.json").write_text('{"env": "operator"}\n')
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        (wt_dir / "environments.json").write_text('{"env": "stale"}\n')
        notices = wlc.local_config_report(repo, wt_dir)
        assert _kinds(notices) == [("divergent", "environments.json")]
        # never silently resolved
        assert (wt_dir / "environments.json").read_text() == '{"env": "stale"}\n'

    def test_identical_content_is_silent(self, repo, tmp_path):
        (repo / "environments.json").write_text('{"env": "same"}\n')
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        (wt_dir / "environments.json").write_text('{"env": "same"}\n')
        assert wlc.local_config_report(repo, wt_dir) == []


class TestOptInCopy:
    def test_copy_flag_copies_allowlisted_file_and_reports(self, repo, tmp_path):
        (repo / "environments.json").write_text('{"env": "operator"}\n')
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        notices = wlc.local_config_report(repo, wt_dir, copy=True)
        assert _kinds(notices) == [("copied", "environments.json")]
        assert (wt_dir / "environments.json").read_text() == '{"env": "operator"}\n'

    def test_copy_refuses_to_overwrite_divergent_content(self, repo, tmp_path):
        (repo / "environments.json").write_text('{"env": "operator"}\n')
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        (wt_dir / "environments.json").write_text('{"env": "different"}\n')
        notices = wlc.local_config_report(repo, wt_dir, copy=True)
        assert _kinds(notices) == [("divergent", "environments.json")]
        assert notices[0]["copy_refused"] is True
        assert (wt_dir / "environments.json").read_text() == '{"env": "different"}\n'

    def test_not_on_allowlist_never_copied_even_gitignored(self, repo, tmp_path):
        (repo / "other-local.json").write_text("{}\n")  # gitignored, NOT allowlisted
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        notices = wlc.local_config_report(repo, wt_dir, copy=True)
        assert notices == []
        assert not (wt_dir / "other-local.json").exists()


class TestNoSymlinks:
    def test_symlinked_source_is_never_copied_reported_and_skipped(self, repo, tmp_path):
        real = tmp_path / "real-env.json"
        real.write_text('{"env": "elsewhere"}\n')
        (repo / "environments.json").symlink_to(real)
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        notices = wlc.local_config_report(repo, wt_dir, copy=True)
        assert _kinds(notices) == [("symlinked_source_skipped", "environments.json")]
        assert not (wt_dir / "environments.json").exists()

    def test_symlinked_target_is_divergent_refused_never_followed(self, repo, tmp_path):
        (repo / "environments.json").write_text('{"env": "operator"}\n')
        elsewhere = tmp_path / "elsewhere.json"
        elsewhere.write_text('{"env": "operator"}\n')  # even identical content
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        (wt_dir / "environments.json").symlink_to(elsewhere)
        # default: reported
        notices = wlc.local_config_report(repo, wt_dir)
        assert _kinds(notices) == [("divergent", "environments.json")]
        assert "symlink" in notices[0]["message"]
        # copy: refused, never followed/dereferenced/overwritten
        notices = wlc.local_config_report(repo, wt_dir, copy=True)
        assert notices[0]["copy_refused"] is True
        assert (wt_dir / "environments.json").is_symlink()
        assert elsewhere.read_text() == '{"env": "operator"}\n'

    def test_no_code_path_creates_symlinks(self, repo, tmp_path):
        import inspect

        src = inspect.getsource(wlc)
        assert "symlink_to" not in src and "os.symlink" not in src
        (repo / "environments.json").write_text("{}\n")
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        wlc.local_config_report(repo, wt_dir, copy=True)
        # no symlinked entries anywhere in the created tree
        for p in wt_dir.rglob("*"):
            assert not p.is_symlink()


class TestCreateWiring:
    def test_create_declares_missing_by_default(self, home, repo, capsys):
        from dontpanic_orchestrate import cli

        (repo / "environments.json").write_text('{"env": "operator"}\n')
        rc = cli._plan_worktree_main(["create", str(repo / "docs" / "plans" / PLAN_ID)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "environments.json" in out and "missing" in out.lower()
        binding = wt.get_binding(PLAN_ID)
        assert not (Path(binding["worktree_path"]) / "environments.json").exists()

    def test_create_copy_flag_copies_and_reports(self, home, repo, capsys):
        from dontpanic_orchestrate import cli

        (repo / "environments.json").write_text('{"env": "operator"}\n')
        rc = cli._plan_worktree_main(
            ["create", str(repo / "docs" / "plans" / PLAN_ID), "--copy-local-config"]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "copied" in out.lower()
        binding = wt.get_binding(PLAN_ID)
        assert (
            Path(binding["worktree_path"]) / "environments.json"
        ).read_text() == '{"env": "operator"}\n'

    def test_corrupt_registry_refuses_create_before_any_copy(self, home, repo, capsys):
        """Round-7 override residual discharge: the create-path corrupt-
        registry refusal precedes ALL filesystem creation AND the
        local-config copy."""
        from dontpanic_orchestrate import cli

        (repo / "environments.json").write_text('{"env": "operator"}\n')
        wt.registry_path().parent.mkdir(parents=True, exist_ok=True)
        wt.registry_path().write_text("corrupt{")
        rc = cli._plan_worktree_main(
            ["create", str(repo / "docs" / "plans" / PLAN_ID), "--copy-local-config"]
        )
        assert rc == 3
        assert "REFUSED" in capsys.readouterr().err
        worktrees_root = Path(home) / "worktrees"
        created = list(worktrees_root.rglob("environments.json")) if worktrees_root.exists() else []
        assert created == []  # no copy happened
        assert not list(worktrees_root.rglob("*/.git")) if worktrees_root.exists() else True
