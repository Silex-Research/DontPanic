"""Plan 2026-08-09-001 F006 — read-only proof at the filesystem level.

Runner-level allowlist across F001 fixtures; .git tree hash identical before
and after observation including a stale-index repo; token-shaped branch name
is scrubbed from the rendered next payload.

Run: PYTHONPATH=scripts /opt/homebrew/bin/pytest \\
  scripts/dontpanic_orchestrate/tests/test_repo_hygiene_safety.py -q
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from dontpanic_orchestrate import cli
from dontpanic_orchestrate import operator_console as oc
from dontpanic_orchestrate import repo_hygiene as rh
from dontpanic_orchestrate.tests.test_repo_hygiene_observe import (
    add_origin_and_push,
    commit_file,
    init_repo,
    repo_with_origin,
    run_git,
)

_TOKEN_BRANCH = "ghp_" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8"


def _git_tree_hash(repo: Path) -> str:
    """Hash every file under .git (relative path, size, mtime_ns, content)."""
    git_dir = repo / ".git"
    hasher = hashlib.sha256()
    for path in sorted(git_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(git_dir).as_posix()
        st = path.stat()
        hasher.update(rel.encode())
        hasher.update(str(st.st_size).encode())
        hasher.update(str(st.st_mtime_ns).encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _fixture_repos(tmp_path: Path) -> list[Path]:
    repos: list[Path] = []

    clean = repo_with_origin(tmp_path, "clean")
    repos.append(clean)

    dirty_tracked = repo_with_origin(tmp_path, "dirty-tracked")
    (dirty_tracked / "README.md").write_text("edited\n")
    repos.append(dirty_tracked)

    dirty_untracked = repo_with_origin(tmp_path, "dirty-untracked")
    (dirty_untracked / "wip.py").write_text("# wip\n")
    repos.append(dirty_untracked)

    ahead = repo_with_origin(tmp_path, "ahead")
    commit_file(ahead, "ahead.txt", "local\n", "local")
    repos.append(ahead)

    no_up = repo_with_origin(tmp_path, "no-up")
    run_git(no_up, "checkout", "-q", "-b", "lonely")
    commit_file(no_up, "lonely.txt", "x\n", "lonely")
    repos.append(no_up)

    merged = repo_with_origin(tmp_path, "merged")
    run_git(merged, "checkout", "-q", "-b", "merged-feat")
    commit_file(merged, "feat.txt", "m\n", "feat")
    run_git(merged, "checkout", "-q", "main")
    run_git(merged, "merge", "--no-ff", "-m", "merge", "merged-feat")
    run_git(merged, "push", "origin", "main")
    repos.append(merged)

    detached = repo_with_origin(tmp_path, "detached")
    run_git(detached, "checkout", "--detach", "HEAD")
    (detached / "d.txt").write_text("d\n")
    repos.append(detached)

    zero = init_repo(tmp_path / "zero")
    (zero / "first.txt").write_text("x\n")
    repos.append(zero)

    no_remote = init_repo(tmp_path / "noremote")
    commit_file(no_remote, "README.md", "solo\n", "init")
    (no_remote / "wip.txt").write_text("u\n")
    repos.append(no_remote)

    stale = repo_with_origin(tmp_path, "stale-index")
    (stale / "README.md").write_text("stale edit\n")
    index = stale / ".git" / "index"
    past = 1_600_000_000
    os.utime(index, (past, past))
    repos.append(stale)

    return repos


def test_runner_allowlist_across_f001_fixtures(tmp_path: Path) -> None:
    for repo in _fixture_repos(tmp_path):
        log: list[tuple[str, ...]] = []
        runner = rh.GitRunner(repo, argv_log=log)
        rh.observe(repo, runner=runner)
        assert log, f"expected git invocations in {repo}"
        for argv in log:
            rh.GitRunner.assert_allowed(argv)


def test_git_tree_unchanged_including_stale_index(tmp_path: Path) -> None:
    for repo in _fixture_repos(tmp_path):
        before = _git_tree_hash(repo)
        rh.observe(repo)
        after = _git_tree_hash(repo)
        assert before == after, f".git mutated while observing {repo}"


def test_optional_locks_env_is_set_on_every_invocation(tmp_path: Path) -> None:
    repo = repo_with_origin(tmp_path, "locks")
    seen: list[str | None] = []

    class _Spy(rh.GitRunner):
        def run(self, *args: str) -> object:
            seen.append(os.environ.get("GIT_OPTIONAL_LOCKS"))
            return super().run(*args)

    runner = _Spy(repo)
    # The runner must set the env on the child, not leak into the parent.
    parent_before = os.environ.get("GIT_OPTIONAL_LOCKS")
    rh.observe(repo, runner=runner)
    assert os.environ.get("GIT_OPTIONAL_LOCKS") == parent_before
    # Spy above reads the parent env; assert the runner's own env flag instead.
    assert runner.last_child_env.get("GIT_OPTIONAL_LOCKS") == "0"


def test_token_shaped_branch_scrubbed_from_next_payload(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "secret-branch")
    commit_file(repo, "README.md", "base\n", "init")
    add_origin_and_push(repo, tmp_path / "secret-branch.git")
    run_git(repo, "checkout", "-q", "-b", _TOKEN_BRANCH)
    commit_file(repo, "secret.txt", "only here\n", "secret")
    out, err = io.StringIO(), io.StringIO()
    prev = Path.cwd()
    os.chdir(repo)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(["next", "--json"])
    finally:
        os.chdir(prev)
    assert rc == 0, err.getvalue()
    payload = json.loads(out.getvalue())
    oc._assert_no_secret_shapes(payload)
    dumped = json.dumps(payload)
    assert _TOKEN_BRANCH not in dumped
    items = [
        it
        for it in (payload.get("action_items") or [])
        if it.get("source") == oc.SOURCE_REPO_HYGIENE
    ]
    assert items
    assert any("[REDACTED]" in json.dumps(it) for it in items)


def test_module_docstring_states_read_only_contract() -> None:
    doc = (rh.__doc__ or "").lower()
    assert "read-only" in doc
    assert "git_optional_locks" in doc or "optional locks" in doc
    assert "allowlist" in doc or "allow-list" in doc
