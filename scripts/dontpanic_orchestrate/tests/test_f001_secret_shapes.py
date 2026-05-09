"""F001 — secret-shape regex coverage tests for sanitization_check.py.

Per D005, every secret-shape regex in sanitization_check.py carries a code-
comment citation. Per F001 acceptance, every regex must be pinned by a
matched POSITIVE example AND a near-miss NEGATIVE example that asserts the
boundary of the pattern. Together they catch (a) silent regex-shape rot if
a vendor changes its key format and (b) over-eager rules that would flag
placeholder strings in docs, env-example files, or commit fixtures.

The test file lives under scripts/dontpanic_orchestrate/tests/, which is in
ALLOWED_GLOBS — sanitization_check itself skips this directory, so we can
embed canonical-shape strings without tripping the scanner on commit.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_PATH = REPO_ROOT / "scripts" / "sanitization_check.py"


def _load():
    import sys

    spec = importlib.util.spec_from_file_location("sanitization_check", CHECK_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sanitization_check"] = mod
    spec.loader.exec_module(mod)
    return mod


# Positive / negative pairs per pattern. Each row pins one regex's boundary:
# the positive case is a canonical-shape string the scanner MUST flag; the
# negative case is a placeholder/lookalike that MUST NOT match. Synthetic
# strings only — no real credentials.
#
# 36-char alphanum body for GitHub tokens.
_GH_BODY_36 = "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
# 93-char body for Anthropic keys (then suffix "AA" → total 95 after prefix).
_ANTHROPIC_BODY_93 = ("a" * 31) + ("B" * 31) + ("0" * 31)
# OpenAI body: 20+ alphanums, T3BlbkFJ infix, 20+ alphanums.
_OPENAI_PREFIX_20 = "ABCDEFGHIJKLMNOPQRST"
_OPENAI_SUFFIX_20 = "abcdefghijklmnopqrst"

CASES = [
    # (regex_attr_name, positive_canonical_match, negative_placeholder_lookalike)
    (
        "_AWS_ACCESS_KEY_RE",
        "AKIAIOSFODNN7EXAMPLE",  # AWS docs canonical example shape
        "AKIA0000000000000000",  # all-zero placeholder — entropy lookahead rejects it
    ),
    (
        "_GH_PAT_RE",
        f"ghp_{_GH_BODY_36}",
        "ghp_PLACEHOLDER_NOT_REAL",  # underscore breaks [A-Za-z0-9] body
    ),
    (
        "_GH_FINE_GRAINED_RE",
        f"ghs_{_GH_BODY_36}",  # ghs_ = server-to-server, valid suffix in [osur]
        f"ghx_{_GH_BODY_36}",  # 'x' not in [osur] — must not match
    ),
    (
        "_ANTHROPIC_API_KEY_RE",
        f"sk-ant-api03-{_ANTHROPIC_BODY_93}AA",
        "sk-ant-PLACEHOLDER",  # no api03- segment, body too short
    ),
    (
        "_OPENAI_API_KEY_RE",
        f"sk-{_OPENAI_PREFIX_20}T3BlbkFJ{_OPENAI_SUFFIX_20}",
        "sk-PLACEHOLDER",  # missing T3BlbkFJ infix
    ),
    (
        "_SLACK_TOKEN_RE",
        "xoxb-1234567890ABCDEF",  # role 'b', 15-char body satisfies {10,}
        "xoxz-1234567890ABCDEF",  # 'z' not in [baprs] — must not match
    ),
    (
        "_PEM_PRIVATE_KEY_RE",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN CERTIFICATE-----",  # not a private key block
    ),
    (
        "_JWT_RE",
        # Three dot-separated base64url segments, each >=10 chars,
        # leading "eyJ" anchors on the JOSE header.
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "https://example.invalid/webhook",  # placeholder URL — no eyJ + 3 segments
    ),
    (
        "_DISCORD_WEBHOOK_RE",
        # Plan 2026-05-01-002 F004 — canonical Discord webhook URL shape.
        # 17-20 digit ID + 60+ url-safe-base64 token. Either discord.com or
        # discordapp.com hostname.
        (
            "https://discord.com/api/webhooks/12345678901234567890/"
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789Aa"
        ),
        "https://example.invalid/webhook",  # RFC 2606 reserved TLD — no match
    ),
]


@pytest.mark.parametrize("attr,positive,negative", CASES, ids=[c[0] for c in CASES])
def test_secret_regex_positive_match(attr: str, positive: str, negative: str) -> None:
    """Canonical-shape string MUST match — guards against regex rot."""
    mod = _load()
    rx = getattr(mod, attr)
    assert rx.search(positive), f"{attr} failed to match canonical positive {positive!r}"


@pytest.mark.parametrize("attr,positive,negative", CASES, ids=[c[0] for c in CASES])
def test_secret_regex_negative_no_match(attr: str, positive: str, negative: str) -> None:
    """Placeholder/lookalike MUST NOT match — guards against over-eager rules."""
    mod = _load()
    rx = getattr(mod, attr)
    assert not rx.search(negative), f"{attr} wrongly matched placeholder {negative!r}"


def test_secret_regexes_count_and_export() -> None:
    """sanitization_check.py exports exactly the 9 patterns enumerated:
    8 from plan 2026-05-01-003 F001 + Discord webhook from
    plan 2026-05-01-002 F004."""
    mod = _load()
    assert len(mod.SECRET_REGEXES) == 9
    expected_attrs = [c[0] for c in CASES]
    pattern_strs = {rx.pattern for rx in mod.SECRET_REGEXES}
    for attr in expected_attrs:
        rx = getattr(mod, attr)
        assert rx.pattern in pattern_strs, f"{attr} missing from SECRET_REGEXES tuple"


def test_scan_line_flags_violation_file_with_one_match_per_pattern(tmp_path) -> None:
    """End-to-end: a single synthetic file containing one positive per pattern
    must be flagged 8 times by scan_line."""
    mod = _load()
    lines = [pos for _, pos, _ in CASES]
    flagged = [mod.scan_line(line) for line in lines]
    assert all(rule is not None for rule in flagged), (
        f"some positives were not flagged: {list(zip(lines, flagged, strict=True))}"
    )
    assert sum(1 for r in flagged if r is not None) == 9


def test_scan_line_does_not_flag_placeholders() -> None:
    """False-positive guard: every negative case scans clean."""
    mod = _load()
    for attr, _, neg in CASES:
        assert mod.scan_line(neg) is None, f"{attr} negative case {neg!r} was incorrectly flagged"


# Acceptance-criteria placeholders, copied verbatim from the F001 spec. These
# are the canonical lookalikes a reviewer would type into a doc / env-example
# / fixture, and the scanner MUST stay quiet on each. Listed explicitly (not
# just via CASES) so a future regex change that re-introduces a placeholder
# match against any of these breaks this test specifically.
ACCEPTANCE_PLACEHOLDERS = [
    "AKIA0000000000000000",
    "AKIAAAAAAAAAAAAAAAAA",
    "sk-ant-PLACEHOLDER",
    "https://example.invalid/webhook",
]


@pytest.mark.parametrize("placeholder", ACCEPTANCE_PLACEHOLDERS)
def test_acceptance_placeholders_not_flagged(placeholder: str) -> None:
    """Each placeholder example listed in the F001 acceptance criteria must
    scan clean. Pins the boundary: if a regex is later widened in a way that
    matches doc-style placeholders, this test catches it."""
    mod = _load()
    assert mod.scan_line(placeholder) is None, (
        f"acceptance placeholder {placeholder!r} was incorrectly flagged"
    )
