"""Guard-hardening F003 — operator-local config policy across worktrees
(plan 2026-06-11-001, operator policy D003).

Operator-local, gitignored config does not propagate into a fresh plan
worktree by checkout. The v1 policy:

* DEFAULT — declare explicitly: every allowlisted file that exists in
  repo_root but not in the worktree is reported (declare-missing, naming
  the copy affordance); an allowlisted file already present in the
  worktree whose content DIFFERS from repo_root's copy is reported
  (declare-divergent). Never silent divergence in either direction.
* OPT-IN — ``--copy-local-config`` copies ONLY allowlisted files from
  repo_root into the worktree at create time, reporting each copy, and
  REFUSES to overwrite different content (divergence is reported, never
  silently resolved).
* NO SYMLINKS, deterministic at both ends: a symlinked SOURCE is never
  copied (reported and skipped); a symlinked TARGET is divergent —
  reported by default, refused at copy time, never followed or
  dereferenced. No code path here creates a symlink.

Files NOT on the allowlist are never copied even if gitignored-local.
An allowlisted file absent from repo_root produces no notice and is
never copied (D011: the policy governs repo_root→worktree propagation
only; a worktree-only copy is left untouched and unreported in v1).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

# Pinned verbatim (locked acceptance): repo-root-relative, gitignored,
# operator-local, non-secret files. Initially exactly one entry.
LOCAL_CONFIG_ALLOWLIST: tuple[str, ...] = ("environments.json",)

COPY_FLAG = "--copy-local-config"


def _notice(kind: str, rel: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "file": rel, "message": message, **extra}


def local_config_report(
    repo_root: Path, worktree_path: Path, *, copy: bool = False
) -> list[dict[str, Any]]:
    """Check each allowlisted file and return explicit notices; with
    ``copy=True`` also perform the opt-in copy for missing targets.
    Pure with respect to everything except that one opt-in copy."""
    repo_root = Path(repo_root)
    worktree_path = Path(worktree_path)
    notices: list[dict[str, Any]] = []

    for rel in LOCAL_CONFIG_ALLOWLIST:
        src = repo_root / rel
        dst = worktree_path / rel

        if src.is_symlink():
            notices.append(
                _notice(
                    "symlinked_source_skipped",
                    rel,
                    f"{rel} in {repo_root} is a symlink — only regular files "
                    "are ever copied (no-symlink policy); skipped",
                )
            )
            continue
        if not src.is_file():
            # source-missing: nothing to declare or propagate (D011 pin)
            continue

        if dst.is_symlink():
            notices.append(
                _notice(
                    "divergent",
                    rel,
                    f"{rel} already exists in the worktree as a symlink — "
                    "treated as divergent, never followed or overwritten "
                    f"(copy {'refused' if copy else 'would be refused'})",
                    copy_refused=copy,
                )
            )
            continue

        if not dst.exists():
            if copy:
                shutil.copyfile(src, dst)
                notices.append(
                    _notice(
                        "copied",
                        rel,
                        f"copied {rel} from {repo_root} into the worktree "
                        f"({COPY_FLAG})",
                    )
                )
            else:
                notices.append(
                    _notice(
                        "missing",
                        rel,
                        f"{rel} exists in {repo_root} but not in the new "
                        f"worktree — operator-local config does not propagate "
                        f"by checkout; re-run create with {COPY_FLAG} or copy "
                        "it manually",
                    )
                )
            continue

        if dst.read_bytes() != src.read_bytes():
            notices.append(
                _notice(
                    "divergent",
                    rel,
                    f"{rel} in the worktree DIFFERS from {repo_root}'s copy — "
                    "divergence is reported, never silently resolved"
                    + (f"; copy refused ({COPY_FLAG} never overwrites)" if copy else ""),
                    copy_refused=copy,
                )
            )
        # identical content: silent

    return notices


__all__ = ["COPY_FLAG", "LOCAL_CONFIG_ALLOWLIST", "local_config_report"]
