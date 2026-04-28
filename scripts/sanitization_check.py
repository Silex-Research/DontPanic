"""sanitization_check.py — fail if campaign-only IDs leak into sanitized files.

Runs in CI and locally. Looks for the campaign project ID (assembled from
parts so this script doesn't trip its own check) and the campaign billing
account; both are allowed only in: docs/plans (audit/evidence), tests
(fixtures), dashboard state, the campaign-convenience costs script, and
the CONTRIBUTING note that explicitly references the campaign.

Exit 0 = clean. Exit 1 = leak. Prints offending paths to stderr.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Patterns checked: campaign project ID, campaign billing account, and
# maintainer-personal identifiers. Each is assembled from parts so this
# file does not match its own check.
_PROJECT = "jarvis-" + "a6ee1"
_BILLING = "01EA42-" + "C7164E-" + "236F6E"
_MAINTAINER_USER = "bil" + "otto"  # appears in @gmail, @silexr, GitHub noreply
PATTERNS = [_PROJECT, _BILLING, _MAINTAINER_USER]

# Path-prefix allowlist (relative to repo root). Plan dirs retain
# historical IDs by design (audit/evidence integrity); test fixtures
# may use them as realistic data; vendored upstream code is out of scope.
ALLOWED_PREFIXES = (
    "docs/plans/",
    "dashboard/state/",
    ".git/",
    "claude/projects/",
    "claude/shared/",
    "memory/",
    "research/",
    ".pytest_cache/",
    ".secrets/",
    "scripts/maintainer/",  # gitignored, but defense-in-depth if it slips
)
# Specific files allowed to retain identifiers. The sanitization script
# itself contains the assembled patterns; CONTRIBUTING.md explicitly
# names the campaign project as "do NOT use this".
ALLOWED_FILES = {
    "scripts/sanitization_check.py",
    "CONTRIBUTING.md",
}
# Test fixtures may use historical IDs as test data.
ALLOWED_GLOBS = ("scripts/jarvis_orchestrate/tests/",)


def is_allowed(rel_path: str) -> bool:
    if rel_path in ALLOWED_FILES:
        return True
    if any(rel_path.startswith(p) for p in ALLOWED_PREFIXES):
        return True
    if any(rel_path.startswith(g) for g in ALLOWED_GLOBS):
        return True
    return False


def tracked_files() -> list[str]:
    """Files that would land in a `git add .` from a clean state.

    Includes:
      - committed (--cached)
      - untracked but not gitignored (--others --exclude-standard)

    Excludes ignored files (.secrets/, scripts/maintainer/, environments.json,
    .firebaserc) and submodule contents. This makes the check honest before
    staging — a leak in an unstaged new file is still surfaced.
    """
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in proc.stdout.splitlines() if line]


def main() -> int:
    pattern_re = re.compile("|".join(re.escape(p) for p in PATTERNS))
    leaks: list[tuple[str, int, str]] = []
    for rel in tracked_files():
        if is_allowed(rel):
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern_re.search(line):
                leaks.append((rel, lineno, line.strip()[:160]))
    if leaks:
        print("::error::Campaign IDs leaked into sanitized files:", file=sys.stderr)
        for rel, lineno, line in leaks:
            print(f"  {rel}:{lineno}: {line}", file=sys.stderr)
        print(
            "\nFix: either move the reference to an allowed location "
            "(docs/plans, tests, dashboard state) or replace with a placeholder "
            "(your-project-id). See scripts/sanitization_check.py for the allowlist.",
            file=sys.stderr,
        )
        return 1
    print(f"✓ no campaign IDs in sanitized surface ({len(tracked_files())} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
