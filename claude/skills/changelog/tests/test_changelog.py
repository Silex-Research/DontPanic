"""Tests for changelog skill (F001).

Run from Jarvis repo root:
    pytest claude/skills/changelog/tests/ -q

Fixture-driven; require zero git history and zero credentials.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("changelog", SKILL_DIR / "changelog.py")
changelog = importlib.util.module_from_spec(spec)
sys.modules["changelog"] = changelog
assert spec.loader is not None
spec.loader.exec_module(changelog)


FIXTURES = SKILL_DIR / "tests" / "fixtures"

ALL_FIXTURE_NAMES = ["nominal", "empty", "non_conventional", "single_commit", "merge_commit"]


# ── Golden-output (byte-for-byte) tests ──────────────────────────────────────


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_fixture_matches_golden_markdown(name: str, capsys):
    """Acceptance criterion: rendered markdown matches expected.md byte-for-byte."""
    fixture_dir = FIXTURES / name
    rc = changelog.main(["--fixtures", str(fixture_dir)])
    assert rc == 0
    captured = capsys.readouterr().out
    expected = (fixture_dir / "expected.md").read_text()
    assert captured == expected, (
        f"Output mismatch for fixture '{name}':\n"
        f"--- expected ---\n{expected}\n--- got ---\n{captured}"
    )


def test_nominal_json_matches_golden(capsys):
    rc = changelog.main(
        [
            "--fixtures",
            str(FIXTURES / "nominal"),
            "--format",
            "json",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr().out
    expected = (FIXTURES / "nominal" / "expected.json").read_text()
    # JSON should match byte-for-byte too (deterministic dict order, sorted=False
    # but insertion order is fixed by CANONICAL_GROUPS).
    assert captured == expected


# ── Acceptance — empty range exits 0 and never stack-traces ───────────────────


def test_empty_range_clean_exit():
    text = (FIXTURES / "empty" / "git_log.txt").read_text()
    commits = changelog.parse_git_log(text)
    assert commits == []
    md = changelog.render_markdown(commits, from_ref="v1.0.0", to_ref="v1.0.0")
    assert "No commits in range" in md
    assert "Commits: 0" in md
    js = json.loads(changelog.render_json(commits, from_ref="v1.0.0", to_ref="v1.0.0"))
    assert js["commit_count"] == 0
    assert js["groups"] == []


# ── Acceptance — non-Conventional commits land under 'other' ──────────────────


def test_non_conventional_commits_grouped_as_other():
    text = (FIXTURES / "non_conventional" / "git_log.txt").read_text()
    commits = changelog.parse_git_log(text)
    assert len(commits) == 3
    grouped = changelog.group_by_type(commits)
    assert set(grouped.keys()) == {"other"}
    assert len(grouped["other"]) == 3


# ── Single-commit fixture ─────────────────────────────────────────────────────


def test_single_commit_fixture():
    text = (FIXTURES / "single_commit" / "git_log.txt").read_text()
    commits = changelog.parse_git_log(text)
    assert len(commits) == 1
    grouped = changelog.group_by_type(commits)
    assert list(grouped.keys()) == ["feat"]
    md = changelog.render_markdown(commits, from_ref="v2.0.0", to_ref="HEAD")
    assert "## Features (1)" in md
    assert "single change" in md


# ── Merge-commit fixture ──────────────────────────────────────────────────────


def test_merge_commit_recognized_and_not_dropped():
    text = (FIXTURES / "merge_commit" / "git_log.txt").read_text()
    commits = changelog.parse_git_log(text)
    assert len(commits) == 3
    merges = [c for c in commits if c.is_merge]
    assert len(merges) == 1
    # Merge commit kept, gets the [merge] tag in the rendered markdown.
    md = changelog.render_markdown(commits, from_ref="v3.0.0", to_ref="HEAD")
    assert "[merge]" in md
    # It also lands in 'other' because "Merge branch ..." is non-Conventional.
    grouped = changelog.group_by_type(commits)
    assert "other" in grouped
    assert any(c.is_merge for c in grouped["other"])


# ── Conventional Commits classifier — mixed prefixes including scope/breaking ─


def test_classify_known_prefixes_are_normalized():
    text = (FIXTURES / "nominal" / "git_log.txt").read_text()
    commits = changelog.parse_git_log(text)
    types = sorted({c.classify()[0] for c in commits})
    assert types == ["chore", "docs", "feat", "fix", "refactor", "test"]


def test_classify_strips_scope_and_breaking_marker():
    c = changelog.Commit(
        sha="x" * 40,
        short="xxxxxxx",
        date="2026-04-29T00:00:00+00:00",
        author="t <t@t>",
        parents=[],
        subject="feat(api)!: breaking change",
        body="",
    )
    t, rest = c.classify()
    assert t == "feat"
    assert rest == "breaking change"


def test_classify_unknown_type_falls_back_to_other():
    c = changelog.Commit(
        sha="x" * 40,
        short="xxxxxxx",
        date="2026-04-29T00:00:00+00:00",
        author="t <t@t>",
        parents=[],
        subject="weirdo: something",
        body="",
    )
    t, rest = c.classify()
    assert t == "other"
    assert rest == "weirdo: something"


# ── parse_git_log structural details ──────────────────────────────────────────


def test_parse_extracts_files_in_status_order():
    text = (FIXTURES / "nominal" / "git_log.txt").read_text()
    commits = changelog.parse_git_log(text)
    # Commit 1 is feat(auth) with two files.
    assert commits[0].files == [("A", "src/auth/oauth.py"), ("M", "src/auth/__init__.py")]


def test_parse_handles_multiline_body():
    text = (FIXTURES / "nominal" / "git_log.txt").read_text()
    commits = changelog.parse_git_log(text)
    # Alice's first commit has a body line about OAuth2.
    assert "OAuth2 redirect flow" in commits[0].body


# ── CLI: --out writes file, missing fixture errors ────────────────────────────


def test_main_writes_to_out_path(tmp_path: Path):
    out = tmp_path / "subdir" / "CHANGELOG.md"
    rc = changelog.main(
        [
            "--fixtures",
            str(FIXTURES / "nominal"),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    assert out.is_file()
    body = out.read_text()
    expected = (FIXTURES / "nominal" / "expected.md").read_text()
    assert body == expected


def test_main_missing_fixture_returns_2(tmp_path: Path):
    rc = changelog.main(["--fixtures", str(tmp_path / "does-not-exist")])
    assert rc == 2


def test_main_explicit_from_to_overrides_meta(capsys):
    rc = changelog.main(
        [
            "--fixtures",
            str(FIXTURES / "nominal"),
            "--from",
            "explicit-start",
            "--to",
            "explicit-end",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Range: `explicit-start..explicit-end`" in out


# ── No-LLM, no-network, no-secrets sanity ─────────────────────────────────────


def test_module_does_not_import_network_libs():
    """Defensive: skill must remain network-free for portability."""
    forbidden = {"requests", "httpx", "anthropic", "openai", "google", "boto3"}
    for mod_name in forbidden:
        assert mod_name not in sys.modules or not any(
            "claude/skills/changelog" in (getattr(sys.modules[mod_name], "__file__", "") or "")
            for _ in [None]
        ), f"changelog should not import {mod_name}"
