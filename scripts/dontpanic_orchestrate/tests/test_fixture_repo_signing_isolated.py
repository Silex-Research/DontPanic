"""Fixture git repos must never attempt commit/tag signing.

Operator Macs may carry a global ``commit.gpgsign=true`` backed by a signer
(1Password ``op-ssh-sign``) that can fail. Each fixture-repo builder must write
``commit.gpgsign=false`` / ``tag.gpgsign=false`` into the temp repo's OWN local
config. These tests are independent of the host signer: they configure a
signer that always fails in the temp repo's local config, prove it does fail
when signing is forced (control), then prove a plain commit/tag succeeds.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.tests import test_git_state as _git_state_tests  # noqa: E402
from dontpanic_orchestrate.tests import (  # noqa: E402
    test_invocation_ledger_canonical as _ledger_tests,
)
from dontpanic_orchestrate.tests import test_repo_hygiene_observe as _hygiene_tests  # noqa: E402
from dontpanic_orchestrate.tests._fixture_git import disable_fixture_signing  # noqa: E402

# Public-key literal only (no private material); the failing signer never reads it.
_FAKE_SIGNING_KEY = "key::ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixtureOnlyNotARealKey fixture"


def _shared_helper(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    disable_fixture_signing(repo)


def _ledger_git_init(repo: Path) -> None:
    _ledger_tests._git_init(repo)


def _hygiene_init_repo(repo: Path) -> None:
    _hygiene_tests.init_repo(repo)


def _git_state_init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git_state_tests._init_git_repo(repo)


BUILDERS: dict[str, Callable[[Path], None]] = {
    "shared_helper": _shared_helper,
    "invocation_ledger._git_init": _ledger_git_init,
    "repo_hygiene_observe.init_repo": _hygiene_init_repo,
    "git_state._init_git_repo": _git_state_init,
}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
    }
    return subprocess.run(
        ["git", "-C", str(repo), *args], env=env, capture_output=True, text=True, check=False
    )


def _install_failing_signer(repo: Path, tmp_path: Path) -> None:
    signer = tmp_path / "failing-signer.sh"
    signer.write_text("#!/bin/sh\necho 'fixture signer: cannot sign' >&2\nexit 1\n")
    signer.chmod(0o755)
    for key, value in (
        ("user.name", "Fixture"),
        ("user.email", "fixture@example.invalid"),
        ("gpg.format", "ssh"),
        ("gpg.ssh.program", str(signer)),
        ("user.signingkey", _FAKE_SIGNING_KEY),
    ):
        assert _git(repo, "config", "--local", key, value).returncode == 0


@pytest.mark.parametrize("builder", list(BUILDERS), ids=list(BUILDERS))
def test_fixture_repo_local_config_disables_signing(builder: str, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    BUILDERS[builder](repo)

    commit_cfg = _git(repo, "config", "--local", "commit.gpgsign")
    tag_cfg = _git(repo, "config", "--local", "tag.gpgsign")
    assert commit_cfg.stdout.strip() == "false", commit_cfg
    assert tag_cfg.stdout.strip() == "false", tag_cfg


@pytest.mark.parametrize("builder", list(BUILDERS), ids=list(BUILDERS))
def test_fixture_repo_commits_and_tags_with_failing_signer(builder: str, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    BUILDERS[builder](repo)
    _install_failing_signer(repo, tmp_path)

    # Control: the locally configured signer really fails when signing is forced.
    forced = _git(repo, "-c", "commit.gpgsign=true", "commit", "--allow-empty", "-q", "-m", "forced")
    assert forced.returncode != 0, forced
    assert "cannot sign" in forced.stderr or "failed" in forced.stderr.lower(), forced

    # With the fixture's local opt-out, no signing is attempted.
    plain = _git(repo, "commit", "--allow-empty", "-q", "-m", "x")
    assert plain.returncode == 0, plain.stderr
    tag = _git(repo, "tag", "-a", "fixture-tag", "-m", "t")
    assert tag.returncode == 0, tag.stderr
