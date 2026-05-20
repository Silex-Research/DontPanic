"""dontpanic architecture hook — opt-in pre-commit installer.

Plan 2026-05-19-004 F005. Installs a ``.git/hooks/pre-commit`` script that,
on commit:

  1. When staged files match architecture-relevant globs, checks the stored
     ``architecture.json`` fingerprint against the current source tree.
  2. **Default (warn-only) mode**: prints a warning + the exact regen
     command. Does NOT block the commit. Does NOT mutate staged files.
  3. **--auto-regen mode**: regenerates the snapshot and ``git add``s
     ``docs/architecture/architecture.json`` before commit. On regen
     failure, falls back to warn-only (never blocks).

Both modes are explicit operator choices. The default mutation-free
behavior matches F004's discipline — DontPanic never auto-commits the
architecture map on the operator's behalf.

Install preserves any existing pre-commit hook by moving it to
``pre-commit.pre-dontpanic`` and chaining it from the wrapper. Uninstall
removes the DontPanic hook + restores the backup.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

HOOK_NAME = "pre-commit"
BACKUP_SUFFIX = ".pre-dontpanic"
SENTINEL = "# dontpanic-architecture-hook v1"

# Embedded bash template. The ``{python_bin}`` / ``{auto_regen}`` placeholders
# are substituted at install time. Keep this tight (~30 active lines) — the
# acceptance budget is <1s end-to-end on this codebase.
HOOK_TEMPLATE = """\
#!/bin/bash
{sentinel}
# auto_regen={auto_regen}
# Installed by `dontpanic architecture hook --install`. Do not edit by hand;
# re-install to change settings.
set -u

# 1. Chain any prior pre-commit hook the operator had in place.
HOOK_DIR="$(dirname "$0")"
PRIOR_HOOK="$HOOK_DIR/{hook_name}{backup_suffix}"
if [ -x "$PRIOR_HOOK" ]; then
  "$PRIOR_HOOK" "$@" || exit $?
fi

# 2. Need a repo root + a list of staged files.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
STAGED="$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null)"
if [ -z "$STAGED" ]; then exit 0; fi

# 3. Match against architecture-relevant globs. Bail fast if nothing matches.
HAS_MATCH=0
while IFS= read -r f; do
  case "$f" in
    scripts/dontpanic_orchestrate/*) HAS_MATCH=1 ;;
    claude/shared/*) HAS_MATCH=1 ;;
    docs/plans/*/plan.md) HAS_MATCH=1 ;;
    docs/plans/*/features.json) HAS_MATCH=1 ;;
  esac
done <<EOF
$STAGED
EOF
if [ "$HAS_MATCH" = "0" ]; then exit 0; fi

# 4. Resolve a dontpanic invocation. Prefer installed binary; fall back to
#    the Python interpreter that installed this hook.
if command -v dontpanic >/dev/null 2>&1; then
  DP_RUN() {{ dontpanic "$@"; }}
else
  DP_RUN() {{ "{python_bin}" -m dontpanic_orchestrate "$@"; }}
fi

AUTO_REGEN="{auto_regen}"

if [ "$AUTO_REGEN" = "1" ]; then
  # Regen + stage. Failures fall back to warn-only (never block the commit).
  # Pass --repo-root explicitly so the CLI doesn't walk up from the installed
  # package and target the wrong tree (e.g., when the dev install lives in a
  # different checkout than the working repo).
  if (cd "$REPO_ROOT" && DP_RUN architecture regen --repo-root "$REPO_ROOT" --json-only) >/dev/null 2>&1; then
    (cd "$REPO_ROOT" && git add "docs/architecture/architecture.json") >/dev/null 2>&1 || true
    echo "[dontpanic] architecture.json regenerated + staged" >&2
  else
    echo "[dontpanic] architecture regen failed; commit continues. Run: dontpanic architecture regen" >&2
  fi
  exit 0
fi

# Default warn-only mode: check status, print regen command when stale/absent.
STATUS_JSON="$(cd "$REPO_ROOT" && DP_RUN architecture status --repo-root "$REPO_ROOT" --json 2>/dev/null)"
case "$STATUS_JSON" in
  *'"state": "stale"'*|*'"state": "absent"'*)
    echo "[dontpanic] architecture map appears stale or absent." >&2
    echo "[dontpanic] Run: dontpanic architecture regen" >&2
    ;;
esac
exit 0
"""


@dataclass(frozen=True)
class HookPaths:
    git_dir: Path
    hooks_dir: Path
    hook_path: Path
    backup_path: Path

    @classmethod
    def from_repo(cls, repo_root: Path) -> "HookPaths":
        repo_root = Path(repo_root).resolve()
        # Allow .git as a file (worktrees / submodules) by reading gitdir.
        git_dir = _resolve_git_dir(repo_root)
        hooks_dir = git_dir / "hooks"
        return cls(
            git_dir=git_dir,
            hooks_dir=hooks_dir,
            hook_path=hooks_dir / HOOK_NAME,
            backup_path=hooks_dir / f"{HOOK_NAME}{BACKUP_SUFFIX}",
        )


def _resolve_git_dir(repo_root: Path) -> Path:
    candidate = repo_root / ".git"
    if candidate.is_dir():
        return candidate
    if candidate.is_file():
        # Worktree / submodule pointer: `gitdir: <path>`
        text = candidate.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            target = Path(text[len("gitdir:") :].strip())
            if not target.is_absolute():
                target = (repo_root / target).resolve()
            return target
    raise FileNotFoundError(f"not a git repository: {repo_root}")


def is_dontpanic_hook(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="replace").splitlines()[:5]
    except OSError:
        return False
    return any(SENTINEL in line for line in head)


def build_hook_script(*, auto_regen: bool, python_bin: str | None = None) -> str:
    """Render the bash hook script with the install-time substitutions."""
    return HOOK_TEMPLATE.format(
        sentinel=SENTINEL,
        auto_regen="1" if auto_regen else "0",
        python_bin=python_bin or sys.executable,
        hook_name=HOOK_NAME,
        backup_suffix=BACKUP_SUFFIX,
    )


def install(
    repo_root: Path | str,
    *,
    auto_regen: bool = False,
    python_bin: str | None = None,
) -> dict[str, object]:
    """Install the DontPanic pre-commit hook.

    Preserves any non-DontPanic pre-commit hook by moving it to
    ``pre-commit.pre-dontpanic``. Re-running install is idempotent: an
    existing DontPanic hook is overwritten without re-backing up.
    """
    paths = HookPaths.from_repo(Path(repo_root))
    paths.hooks_dir.mkdir(parents=True, exist_ok=True)

    backed_up = False
    if paths.hook_path.exists() and not is_dontpanic_hook(paths.hook_path):
        # Don't clobber a prior backup — if one already exists, the operator
        # likely partially installed/uninstalled at some point. Surface that
        # by refusing to overwrite (acceptance #4 invariant: backup is
        # always the prior real hook).
        if paths.backup_path.exists():
            raise FileExistsError(
                f"refusing to overwrite existing backup at {paths.backup_path}; "
                "uninstall first or remove the backup manually."
            )
        shutil.move(str(paths.hook_path), str(paths.backup_path))
        backed_up = True

    script = build_hook_script(auto_regen=auto_regen, python_bin=python_bin)
    paths.hook_path.write_text(script, encoding="utf-8")
    _make_executable(paths.hook_path)

    return {
        "installed": True,
        "auto_regen": bool(auto_regen),
        "hook_path": str(paths.hook_path),
        "backed_up": backed_up,
        "backup_path": str(paths.backup_path) if backed_up else None,
    }


def uninstall(repo_root: Path | str) -> dict[str, object]:
    """Remove the DontPanic pre-commit hook and restore any backup."""
    paths = HookPaths.from_repo(Path(repo_root))
    removed = False
    restored = False
    if paths.hook_path.exists():
        if not is_dontpanic_hook(paths.hook_path):
            raise RuntimeError(
                f"refusing to remove {paths.hook_path}: not a DontPanic hook "
                "(missing sentinel). Remove manually if intended."
            )
        paths.hook_path.unlink()
        removed = True
    if paths.backup_path.exists():
        shutil.move(str(paths.backup_path), str(paths.hook_path))
        _make_executable(paths.hook_path)
        restored = True
    return {
        "uninstalled": removed,
        "restored_backup": restored,
        "hook_path": str(paths.hook_path),
    }


def status(repo_root: Path | str) -> dict[str, object]:
    """Report whether the hook is installed + whether auto-regen is on."""
    paths = HookPaths.from_repo(Path(repo_root))
    if not paths.hook_path.exists():
        return {"installed": False, "auto_regen": False, "hook_path": str(paths.hook_path)}
    if not is_dontpanic_hook(paths.hook_path):
        return {
            "installed": False,
            "foreign_hook_present": True,
            "auto_regen": False,
            "hook_path": str(paths.hook_path),
        }
    auto_regen = _detect_auto_regen(paths.hook_path)
    return {
        "installed": True,
        "auto_regen": auto_regen,
        "hook_path": str(paths.hook_path),
        "backup_present": paths.backup_path.exists(),
    }


def _detect_auto_regen(hook_path: Path) -> bool:
    try:
        for line in hook_path.read_text(encoding="utf-8", errors="replace").splitlines()[:10]:
            if line.startswith("# auto_regen="):
                return line.split("=", 1)[1].strip() == "1"
    except OSError:
        pass
    return False


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
