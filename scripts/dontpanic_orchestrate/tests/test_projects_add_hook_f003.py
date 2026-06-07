"""`projects add` auto-installs the pre-commit architecture hook (plan 2026-06-06-003 F003).

Registering a project now installs a chained pre-commit hook that regenerates +
stages the architecture map on commit — so the committed map stays fresh without
a human remembering to run regen. Opt-out via --no-hooks; best-effort on non-git
paths; never clobbers a prior hook.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from dontpanic_orchestrate import architecture_hook, cli


def _git_init(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(p)], check=True)  # noqa: S607,S603
    return p


def test_projects_add_installs_the_hook_by_default(tmp_path):
    repo = _git_init(tmp_path / "repo")
    rc = cli.main(["projects", "add", "proj", str(repo)])
    assert rc == 0
    assert architecture_hook.status(repo)["installed"] is True


def test_no_hooks_opts_out(tmp_path):
    repo = _git_init(tmp_path / "repo2")
    rc = cli.main(["projects", "add", "projtwo", str(repo), "--no-hooks"])
    assert rc == 0
    assert architecture_hook.status(repo)["installed"] is False


def test_non_git_path_is_graceful_and_creates_no_dot_git(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    rc = cli.main(["projects", "add", "projthree", str(plain)])
    assert rc == 0  # registration still succeeds
    assert not (plain / ".git").exists()  # must NOT fabricate a .git in a non-repo


def test_prior_pre_commit_hook_is_preserved(tmp_path):
    repo = _git_init(tmp_path / "repo4")
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho prior-hook\n", encoding="utf-8")
    hook.chmod(0o755)

    rc = cli.main(["projects", "add", "projfour", str(repo)])
    assert rc == 0
    backup = repo / ".git" / "hooks" / "pre-commit.pre-dontpanic"
    assert backup.exists() and "prior-hook" in backup.read_text(encoding="utf-8")
    assert architecture_hook.status(repo)["installed"] is True
