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

# ── Secret-shape regexes (F001 / D005) ─────────────────────────────────────
# Distinct from PATTERNS: those guard repo-specific identifiers (literal
# strings); these flag canonical secret shapes from major vendors. Each
# regex carries a `# source:` citation per D005 — gitleaks default rules,
# vendor docs, or a tracked issue — so future review can verify the shape
# is current and the false-positive surface is understood.
#
# Anchors are deliberately loose (no \b boundaries) so embedded matches
# inside larger strings still flag — secrets in URLs / JSON / env exports
# don't always sit on word boundaries.

# AWS access key ID. Long-form prefix `AKIA` + 16 base32-uppercase chars.
# Lookaheads reject low-entropy placeholder bodies (e.g. `AKIA0000000000000000`,
# `AKIAAAAAAAAAAAAAAAAA`) by requiring at least one letter AND one digit —
# real AWS keys always mix both, while doc-style placeholders typically don't.
# source: https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml (rule: aws-access-token)
_AWS_ACCESS_KEY_RE = re.compile(r"AKIA(?=[0-9A-Z]*[A-Z])(?=[0-9A-Z]*[0-9])[0-9A-Z]{16}")

# GitHub personal access token (classic). `ghp_` prefix + 36 base62 chars.
# source: https://github.blog/changelog/2021-03-31-authentication-token-format-updates-are-generally-available/
_GH_PAT_RE = re.compile(r"ghp_[A-Za-z0-9]{36}")

# GitHub fine-grained tokens — OAuth (`gho_`), server-to-server (`ghs_`),
# user-to-server (`ghu_`), refresh (`ghr_`). Same 36-char body shape.
# source: https://github.blog/changelog/2021-03-31-authentication-token-format-updates-are-generally-available/
_GH_FINE_GRAINED_RE = re.compile(r"gh[osur]_[A-Za-z0-9]{36}")

# Anthropic API key. `sk-ant-api03-` prefix + 93 url-safe-base64 chars + `AA`.
# source: https://docs.anthropic.com/en/api/getting-started (key format)
_ANTHROPIC_API_KEY_RE = re.compile(r"sk-ant-api03-[A-Za-z0-9_\-]{93}AA")

# OpenAI API key (legacy/standard). Body contains `T3BlbkFJ` infix
# (base64 of "OpenAI"). The 20+/20+ bracket is intentional: OpenAI has
# rotated the surrounding length over time, so we anchor on the infix.
# source: https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml (rule: openai-api-key)
_OPENAI_API_KEY_RE = re.compile(r"sk-[A-Za-z0-9]{20,}T3BlbkFJ[A-Za-z0-9]{20,}")

# Slack tokens. `xox` + role-suffix + body. Covers bot/user/app/refresh/legacy.
# source: https://api.slack.com/authentication/token-types
_SLACK_TOKEN_RE = re.compile(r"xox[baprs]-[0-9a-zA-Z\-]{10,}")

# PEM private-key block opener. Catches RSA / EC / OPENSSH / generic.
# Assembled from parts so this file does not match its own check.
# source: https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml (rule: private-key)
_PEM_PRIVATE_KEY_RE = re.compile(
    "-----" + "BEGIN" + r" (?:RSA |EC |OPENSSH )?" + "PRIVATE KEY" + "-----"
)

# Generic JWT — three base64url segments separated by dots, leading
# `eyJ` (base64 of `{"`) anchors on the JOSE header to keep the false-
# positive surface narrow vs. any 3-segment dotted string.
# source: https://datatracker.ietf.org/doc/html/rfc7519 (JWT spec)
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")

SECRET_REGEXES: tuple[re.Pattern[str], ...] = (
    _AWS_ACCESS_KEY_RE,
    _GH_PAT_RE,
    _GH_FINE_GRAINED_RE,
    _ANTHROPIC_API_KEY_RE,
    _OPENAI_API_KEY_RE,
    _SLACK_TOKEN_RE,
    _PEM_PRIVATE_KEY_RE,
    _JWT_RE,
)

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
ALLOWED_GLOBS = ("scripts/dontpanic_orchestrate/tests/",)


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


def scan_line(line: str) -> str | None:
    """Return the name of the first matching rule, or None.

    Two rule families: campaign-ID literals (PATTERNS) and secret-shape
    regexes (SECRET_REGEXES). Both run against every non-allowlisted line.
    """
    for literal in PATTERNS:
        if literal in line:
            return f"campaign-id:{literal[:8]}…"
    for rx in SECRET_REGEXES:
        if rx.search(line):
            return f"secret-shape:{rx.pattern[:32]}…"
    return None


def main() -> int:
    leaks: list[tuple[str, int, str, str]] = []
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
            rule = scan_line(line)
            if rule is not None:
                leaks.append((rel, lineno, rule, line.strip()[:160]))
    if leaks:
        print("::error::Sanitization check failed:", file=sys.stderr)
        for rel, lineno, rule, line in leaks:
            print(f"  [{rule}] {rel}:{lineno}: {line}", file=sys.stderr)
        print(
            "\nFix: for campaign IDs, move the reference to an allowed location "
            "(docs/plans, tests, dashboard state) or replace with a placeholder "
            "(your-project-id). For secret shapes (AWS / GitHub / Anthropic / "
            "OpenAI / Slack / PEM / JWT), rotate the credential and remove from "
            "history. See scripts/sanitization_check.py for the allowlist.",
            file=sys.stderr,
        )
        return 1
    print(
        f"✓ no campaign IDs or secret shapes in sanitized surface "
        f"({len(tracked_files())} files scanned)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
