"""F001 — capture git state at audit-envelope finalization (read-only).

Spec: plan 2026-05-01-004 F001. Two responsibilities:

  1. ``parse_porcelain(raw)`` — pure parser over ``git status --porcelain=v1 -z``
     output. NUL-terminated entries; each entry is two status chars (XY), a
     separator space, then the path. Renames/copies (R/C in column X) consume
     a second NUL-delimited path (the original); we skip the original and
     classify the new path by the worktree column only — F002 doesn't need
     rename detection in v0 (D005-style narrowing).

  2. ``capture(cwd)`` — runs ``git status --porcelain=v1 -z`` in ``cwd`` and
     returns the parsed ``GitState``, or ``None`` when ``cwd`` is not inside
     a git repo. **Strictly read-only**: only the porcelain command and an
     optional ``rev-parse --show-toplevel`` are allowed; no state-mutating
     git subcommands and no filesystem writes. Test acceptance (7a/7b/7c)
     proves this.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TypedDict

_LOGGER = logging.getLogger(__name__)


class StagedEntry(TypedDict):
    path: str
    status: str


class GitState(TypedDict):
    staged: list[StagedEntry]
    unstaged_modified: list[StagedEntry]
    untracked: list[str]
    deleted_staged: list[str]
    deleted_unstaged: list[str]


def _empty_state() -> GitState:
    return {
        "staged": [],
        "unstaged_modified": [],
        "untracked": [],
        "deleted_staged": [],
        "deleted_unstaged": [],
    }


def parse_porcelain(raw: str) -> GitState:
    """Parse ``git status --porcelain=v1 -z`` output into a ``GitState``.

    Entry format per the porcelain v1 spec: two status chars (X = index,
    Y = worktree), a single separator space, then the path. Entries are
    NUL-terminated. Rename/copy entries consume two NUL tokens (newpath
    then oldpath); we drop the oldpath and treat the rename as "newpath
    was modified in the index" by reading column X.
    """
    state = _empty_state()
    if not raw:
        return state

    tokens = raw.split("\0")
    # Trailing NUL produces an empty final token from str.split — drop it.
    if tokens and tokens[-1] == "":
        tokens.pop()

    i = 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if len(entry) < 4:
            # Malformed — XY + space + at least one path char.
            continue
        index_status = entry[0]
        worktree_status = entry[1]
        path = entry[3:]

        # Untracked entries report ``??`` and are exclusive — they don't
        # appear in any other bucket.
        if index_status == "?" and worktree_status == "?":
            state["untracked"].append(path)
            continue

        # Renames/copies consume the original path token. Drop it; we
        # classify only by index status of the new path below.
        if index_status in ("R", "C"):
            if i < len(tokens):
                i += 1  # discard oldpath

        # Index column (staged side).
        if index_status == "D":
            state["deleted_staged"].append(path)
        elif index_status not in (" ", "?"):
            state["staged"].append({"path": path, "status": index_status})

        # Worktree column (unstaged side).
        if worktree_status == "D":
            state["deleted_unstaged"].append(path)
        elif worktree_status not in (" ", "?"):
            state["unstaged_modified"].append({"path": path, "status": worktree_status})

    return state


def capture(cwd: Path) -> GitState | None:
    """Run ``git status --porcelain=v1 -z`` and parse. Returns ``None`` outside a git repo.

    Read-only by construction: the only git subcommands invoked are
    ``status --porcelain=v1 -z`` and ``rev-parse --show-toplevel`` (for repo
    detection). No state-mutating commands. No filesystem writes.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],  # noqa: S607  # PATH-relative git invocation per D001
            cwd=cwd,
            capture_output=True,
            check=False,
            text=True,
        )
    except (FileNotFoundError, OSError) as exc:
        _LOGGER.warning("git_state.capture: git unavailable in %s: %s", cwd, exc)
        return None

    if result.returncode != 0:
        # Not inside a git repo — expected, not an error.
        return None

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],  # noqa: S607  # PATH-relative git invocation per D001
            cwd=cwd,
            capture_output=True,
            check=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        _LOGGER.warning("git_state.capture: porcelain command failed in %s: %s", cwd, exc)
        return None

    return parse_porcelain(status.stdout)
