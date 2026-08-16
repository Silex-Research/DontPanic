"""Plan 2026-08-09-001 F001 — repo_hygiene observation over an injected GitRunner.

Acceptance: 14+ temp-repo cases covering clean, dirty-tracked, dirty-untracked,
ahead-of-remote, no-upstream, merged-into-default, detached HEAD, zero-commit,
no-remote, and cap-tripped repos. Detached-HEAD / zero-commit / no-remote each
carry a populated tree section when dirty and branches=None. Only a non-repo
cwd returns None overall. No case raises.

Run: PYTHONPATH=scripts /opt/homebrew/bin/pytest \\
  scripts/dontpanic_orchestrate/tests/test_repo_hygiene_observe.py -q
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dontpanic_orchestrate import repo_hygiene as rh


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def init_repo(path: Path, *, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    run_git(path, "config", "user.email", "test@example.com")
    run_git(path, "config", "user.name", "Test")
    run_git(path, "config", "commit.gpgsign", "false")
    return path


def commit_file(repo: Path, rel: str, content: str, msg: str = "commit") -> str:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    run_git(repo, "add", rel)
    run_git(repo, "commit", "-q", "-m", msg)
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


def add_origin_and_push(repo: Path, bare: Path) -> None:
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    run_git(repo, "remote", "add", "origin", str(bare))
    run_git(repo, "push", "-u", "origin", "main")
    run_git(repo, "remote", "set-head", "origin", "main")


def repo_with_origin(tmp_path: Path, name: str = "repo") -> Path:
    repo = init_repo(tmp_path / name)
    commit_file(repo, "README.md", "base\n", "init")
    add_origin_and_push(repo, tmp_path / f"{name}.git")
    return repo


# ── 14+ temp-repo cases ──────────────────────────────────────────────────────


def test_non_repo_cwd_returns_none(tmp_path: Path) -> None:
    assert rh.observe(tmp_path) is None


def test_clean_repo_tree_clean_branches_populated(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.tree is not None
    assert obs.tree.dirty is False
    assert obs.branches is not None
    assert obs.branches_partial is False
    names = {b.name for b in obs.branches.branches}
    assert "main" in names


def test_dirty_tracked_populates_tree(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    (repo / "README.md").write_text("edited\n")
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.tree is not None
    assert obs.tree.dirty is True
    assert "README.md" in obs.tree.unstaged_modified
    assert obs.branches is not None


def test_dirty_untracked_populates_tree(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    (repo / "wip.py").write_text("# wip\n")
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.tree is not None
    assert obs.tree.dirty is True
    assert "wip.py" in obs.tree.untracked
    assert obs.branches is not None


def test_dirty_staged_populates_tree(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    (repo / "staged.py").write_text("# staged\n")
    run_git(repo, "add", "staged.py")
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.tree is not None
    assert obs.tree.dirty is True
    assert "staged.py" in obs.tree.staged


def test_ahead_of_remote_counts_commits(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    commit_file(repo, "ahead.txt", "local only\n", "local")
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.branches is not None
    main = next(b for b in obs.branches.branches if b.name == "main")
    assert main.upstream is not None
    assert main.ahead is not None and main.ahead >= 1


def test_no_upstream_branch_recorded(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    run_git(repo, "checkout", "-q", "-b", "lonely")
    commit_file(repo, "lonely.txt", "no remote\n", "lonely")
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.branches is not None
    lonely = next(b for b in obs.branches.branches if b.name == "lonely")
    assert lonely.upstream is None
    assert lonely.ahead is None


def test_merged_into_default_records_sha(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    run_git(repo, "checkout", "-q", "-b", "merged-feat")
    tip = commit_file(repo, "feat.txt", "merged\n", "feat")
    run_git(repo, "checkout", "-q", "main")
    run_git(repo, "merge", "--no-ff", "-m", "merge feat", "merged-feat")
    run_git(repo, "push", "origin", "main")
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.branches is not None
    merged = next(b for b in obs.branches.branches if b.name == "merged-feat")
    assert merged.merged_into_default_at is not None
    default_sha = obs.branches.default_sha
    assert merged.merged_into_default_at == default_sha
    # The feature tip is an ancestor; it is not the default tip after --no-ff.
    assert tip != default_sha


def test_detached_head_reports_dirty_tree_and_no_branches(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    run_git(repo, "checkout", "--detach", "HEAD")
    (repo / "detached.txt").write_text("dirty while detached\n")
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.tree is not None
    assert obs.tree.dirty is True
    assert "detached.txt" in obs.tree.untracked
    assert obs.branches is None


def test_zero_commit_reports_dirty_tree_and_no_branches(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "empty")
    (repo / "first.txt").write_text("no commits yet\n")
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.tree is not None
    assert obs.tree.dirty is True
    assert "first.txt" in obs.tree.untracked
    assert obs.branches is None


def test_no_remote_reports_dirty_tree_and_no_branches(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "local-only")
    commit_file(repo, "README.md", "solo\n", "init")
    (repo / "wip.txt").write_text("uncommitted\n")
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.tree is not None
    assert obs.tree.dirty is True
    assert "wip.txt" in obs.tree.untracked
    assert obs.branches is None


def test_cap_tripped_sets_branches_partial(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    for i in range(4):
        run_git(repo, "branch", f"extra-{i}")
    # main + 4 extras = 5 heads; cap at 3 trips.
    obs = rh.observe(repo, max_branches=3)
    assert obs is not None
    assert obs.branches is not None
    assert obs.branches_partial is True
    assert obs.branches.partial is True
    assert len(obs.branches.branches) == 3


def test_clean_detached_still_populates_tree(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    run_git(repo, "checkout", "--detach", "HEAD")
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.tree is not None
    assert obs.tree.dirty is False
    assert obs.branches is None


def test_observe_never_raises_on_degenerate_inputs(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-dir"
    assert rh.observe(missing) is None
    file_cwd = tmp_path / "a-file"
    file_cwd.write_text("not a dir\n")
    assert rh.observe(file_cwd) is None


def test_worktree_list_marks_checked_out_elsewhere(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    run_git(repo, "branch", "other")
    other = tmp_path / "wt-other"
    run_git(repo, "worktree", "add", str(other), "other")
    obs = rh.observe(repo)
    assert obs is not None
    assert obs.branches is not None
    assert "other" in obs.branches.checked_out_elsewhere
    other_info = next(b for b in obs.branches.branches if b.name == "other")
    assert other_info.checked_out_in_worktree is True


def test_injected_runner_records_only_allowlisted_subcommands(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path)
    log: list[tuple[str, ...]] = []
    runner = rh.GitRunner(repo, argv_log=log)
    obs = rh.observe(repo, runner=runner)
    assert obs is not None
    assert log
    for argv in log:
        rh.GitRunner.assert_allowed(argv)
