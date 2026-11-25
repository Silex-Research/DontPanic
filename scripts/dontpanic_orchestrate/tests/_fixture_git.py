"""Shared helpers for throwaway fixture git repos created by tests.

Operator machines may carry a global ``commit.gpgsign=true`` (e.g. 1Password
``op-ssh-sign``). A fixture repo that commits or tags without opting out then
fails whenever the signer is unavailable ("1Password: failed to fill whole
buffer"). :func:`disable_fixture_signing` writes the opt-out into the fixture
repo's OWN local config, so every later commit/tag in it — including ones made
by product code or hooks — never attempts to sign.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Inherited repo-location env vars would redirect ``git -C`` away from the
# fixture repo; drop them for these config writes only.
_REPO_LOCATION_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def disable_fixture_signing(repo: Path | str) -> None:
    """Set ``commit.gpgsign=false`` and ``tag.gpgsign=false`` in ``repo``'s
    local git config. Call right after ``git init`` on a throwaway repo."""
    env = {k: v for k, v in os.environ.items() if k not in _REPO_LOCATION_ENV}
    for key in ("commit.gpgsign", "tag.gpgsign"):
        subprocess.run(
            ["git", "-C", str(repo), "config", "--local", key, "false"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
