"""Plan 2026-05-30-001 F003 — repo onboarding managed block.

Covers the deterministic acceptance contract:
  AC1 — `projects add NAME PATH --onboard --dry-run` reports all intended writes
        without changing any file (registry, config, AGENTS.md, CLAUDE.md).
  AC2 — `--onboard` creates `.dontpanic/dontpanic.json` with explicit defaults
        in a shape that validates against `project_config.ProjectConfig`.
  AC3 — Missing AGENTS.md is created with the generated brief block.
  AC4 — Existing AGENTS.md content outside markers stays byte-for-byte unchanged.
  AC5 — A stale managed block is rewritten in place when hash/version differ.
  AC6 — A fresh managed block is left unchanged (re-onboard is a no-op).
  AC7 — CLAUDE.md is created/updated as a pointer without clobbering content;
        lowercase `.claude.md` is preserved and warned about when alone.
  AC8 — JSON and human output both report the planned actions.

All tests redirect `$DONTPANIC_HOME` to tmp so the operator's real home and any
on-disk registry are never touched.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f003_repo_onboarding.py
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    agent_brief,
    cli,
)
from dontpanic_orchestrate import global_config as gc  # noqa: E402
from dontpanic_orchestrate import project_config as pc  # noqa: E402
from dontpanic_orchestrate import projects_registry as pr  # noqa: E402
from dontpanic_orchestrate import repo_onboarding as ro  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """Reroute the DontPanic home so the projects registry writes to tmp."""
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic-home"))


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


@pytest.fixture
def repo(tmp_path) -> Path:
    """A bare project directory to onboard."""
    d = tmp_path / "myrepo"
    d.mkdir()
    return d


# ──────────────────────────────  module-level (writer)  ──────────────────────────────


def test_default_config_is_schema_compatible() -> None:
    """AC2 — the explicit-defaults dict validates against ProjectConfig.

    The key set is derived from ``ProjectConfig.model_fields`` (not hard-coded)
    so a field added to the schema later must also be spelled out here — the
    written config documents the full schema surface, never a partial subset."""
    cfg = ro.default_project_config_dict()
    # Spelled out, not bare {} — EVERY current schema field present.
    assert set(cfg) == set(pc.ProjectConfig.model_fields)
    # roles / runtime_evidence (and any future optional field) are explicit nulls.
    assert cfg["roles"] is None
    assert cfg["runtime_evidence"] is None
    model = pc.ProjectConfig.model_validate(cfg)
    assert model.implementer == pc.FALLBACK_IMPLEMENTER
    assert model.auditor == pc.FALLBACK_AUDITOR
    assert model.plans_dir == pc.DEFAULT_PLANS_DIR


def test_render_block_round_trips_and_hashes() -> None:
    block = ro.render_block(ro.BLOCK_AGENTS, "hello\nworld")
    m = ro.find_block(block, ro.BLOCK_AGENTS)
    assert m is not None
    assert m.group("generator") == ro.ONBOARDING_GENERATOR_VERSION
    # A freshly rendered identical body is detected as fresh.
    assert ro._block_is_fresh(m, "hello\nworld")
    # A changed body is detected as stale.
    assert not ro._block_is_fresh(m, "hello\nDIFFERENT")


def test_plan_only_reads_writes_nothing(repo) -> None:
    plan = ro.plan_onboarding(repo)
    assert not (repo / ro.AGENTS_FILENAME).exists()
    assert not (repo / ro.CLAUDE_FILENAME).exists()
    assert not pc.project_config_path(repo).exists()
    kinds = {a.kind: a.action for a in plan.actions}
    assert kinds == {"config": "create", "agents": "create", "claude": "create"}


# ──────────────────────────────  CLI dry-run (AC1)  ──────────────────────────────


def test_onboard_dry_run_changes_nothing(repo) -> None:
    rc, out, _ = _run(["projects", "add", "myrepo", str(repo), "--onboard", "--dry-run"])
    assert rc == 0
    # Reports intended writes.
    assert "would create" in out
    assert ro.AGENTS_FILENAME in out
    assert ro.CLAUDE_FILENAME in out
    # No file created, registry untouched.
    assert not (repo / ro.AGENTS_FILENAME).exists()
    assert not (repo / ro.CLAUDE_FILENAME).exists()
    assert not pc.project_config_path(repo).exists()
    assert pr.find_project("myrepo") is None


def test_onboard_dry_run_json(repo) -> None:
    rc, out, _ = _run(
        ["projects", "add", "myrepo", str(repo), "--onboard", "--dry-run", "--json"]
    )
    assert rc == 0
    payload = json.loads(out)
    assert payload["action"] == "dry_run"
    assert payload["onboard"]["dry_run"] is True
    actions = {a["kind"]: a["action"] for a in payload["onboard"]["actions"]}
    assert actions == {"config": "create", "agents": "create", "claude": "create"}


def test_onboard_and_init_config_are_mutually_exclusive(repo) -> None:
    """--init-config scaffolds a bare `{}` and would suppress --onboard's richer
    config write, leaving the empty stub. The combination is rejected (exit 2),
    and crucially no empty config is left behind."""
    rc, _, err = _run(
        ["projects", "add", "myrepo", str(repo), "--onboard", "--init-config"]
    )
    assert rc == 2
    assert "mutually exclusive" in err
    # No half-applied state: registry untouched and no bare {} config written.
    assert pr.find_project("myrepo") is None
    assert not pc.project_config_path(repo).exists()


def test_dry_run_missing_path_refused(tmp_path) -> None:
    rc, _, err = _run(
        ["projects", "add", "myrepo", str(tmp_path / "nope"), "--onboard", "--dry-run"]
    )
    assert rc == 2
    assert "does not exist" in err


# ──────────────────────────────  CLI apply: fresh repo  ──────────────────────────────


def test_onboard_creates_all_files(repo) -> None:
    """AC2/AC3/AC7 — config + AGENTS.md + CLAUDE.md created; registry written."""
    rc, out, _ = _run(["projects", "add", "myrepo", str(repo), "--onboard"])
    assert rc == 0
    assert pr.find_project("myrepo") is not None

    cfg_path = pc.project_config_path(repo)
    assert cfg_path.is_file()
    loaded = json.loads(cfg_path.read_text())
    assert loaded == ro.default_project_config_dict()
    # Loadable through the project_config schema (no degrade-to-None).
    assert pc.load_project_config(repo) is not None

    agents = (repo / ro.AGENTS_FILENAME).read_text()
    assert "DontPanic operating brief" in agents
    assert ro.find_block(agents, ro.BLOCK_AGENTS) is not None

    claude = (repo / ro.CLAUDE_FILENAME).read_text()
    assert ro.AGENTS_FILENAME in claude
    assert ro.find_block(claude, ro.BLOCK_CLAUDE) is not None


def test_onboard_json_reports_actions(repo) -> None:
    """AC8 — JSON output reports the applied onboarding actions."""
    rc, out, _ = _run(["projects", "add", "myrepo", str(repo), "--onboard", "--json"])
    assert rc == 0
    payload = json.loads(out)
    assert payload["action"] == "added"
    assert payload["onboard"]["dry_run"] is False
    actions = {a["kind"]: a["action"] for a in payload["onboard"]["actions"]}
    assert actions == {"config": "create", "agents": "create", "claude": "create"}


# ──────────────────────────  existing files: content preserved  ──────────────────────────


def test_existing_agents_content_preserved_byte_for_byte(repo) -> None:
    """AC4 — existing AGENTS.md content outside markers is unchanged; the managed
    block is appended."""
    original = "# My repo rules\n\nDo not break the build.\n"
    (repo / ro.AGENTS_FILENAME).write_text(original)

    rc, _, _ = _run(["projects", "add", "myrepo", str(repo), "--onboard"])
    assert rc == 0
    new_text = (repo / ro.AGENTS_FILENAME).read_text()
    # Original content preserved exactly as a prefix.
    assert new_text.startswith(original)
    # Managed block appended.
    assert ro.find_block(new_text, ro.BLOCK_AGENTS) is not None
    assert "DontPanic operating brief" in new_text


def test_existing_claude_pointer_does_not_clobber(repo) -> None:
    """AC7 — existing CLAUDE.md content kept; pointer block appended."""
    original = "# Project CLAUDE\n\nAlways run tests.\n"
    (repo / ro.CLAUDE_FILENAME).write_text(original)
    rc, _, _ = _run(["projects", "add", "myrepo", str(repo), "--onboard"])
    assert rc == 0
    new_text = (repo / ro.CLAUDE_FILENAME).read_text()
    assert new_text.startswith(original)
    assert ro.find_block(new_text, ro.BLOCK_CLAUDE) is not None


def test_crlf_content_preserved_byte_for_byte(repo) -> None:
    """AC4 — onboarding operates in the byte domain: CRLF line endings and a
    missing trailing newline in existing content survive untouched (a text-mode
    read/write would silently normalize `\\r\\n` → `\\n`)."""
    # CRLF endings, no trailing newline — both would be mangled by read_text.
    original = b"# CRLF repo\r\n\r\nLine without trailing newline"
    agents = repo / ro.AGENTS_FILENAME
    agents.write_bytes(original)

    ro.apply_onboarding(repo, dry_run=False)
    new_bytes = agents.read_bytes()
    # Original bytes preserved verbatim as a prefix; CRLF intact, nothing re-encoded.
    assert new_bytes.startswith(original)
    assert b"\r\n" in new_bytes
    assert ro.find_block(new_bytes.decode("utf-8"), ro.BLOCK_AGENTS) is not None


def test_non_utf8_content_outside_markers_preserved(repo) -> None:
    """AC4 — non-UTF-8 bytes outside the markers neither crash onboarding nor get
    re-encoded; a text-mode read would raise UnicodeDecodeError on this input."""
    # 0xFF is invalid UTF-8; a Latin-1 'ÿ' precedes a valid block region.
    original = b"# legacy notes \xff\xfe rules\n"
    agents = repo / ro.AGENTS_FILENAME
    agents.write_bytes(original)

    ro.apply_onboarding(repo, dry_run=False)
    new_bytes = agents.read_bytes()
    assert new_bytes.startswith(original)
    assert b"\xff\xfe" in new_bytes


def test_stale_block_replace_preserves_surrounding_bytes(repo) -> None:
    """AC4/AC5 — replacing a stale block leaves the exact bytes before/after the
    markers (including CRLF) untouched."""
    before = b"# Keep before\r\n"
    after = b"\r\n# Keep after\r\n"
    stale = ro.render_block(ro.BLOCK_AGENTS, "OLD STALE BODY").encode("utf-8")
    agents = repo / ro.AGENTS_FILENAME
    agents.write_bytes(before + stale + after)

    ro.apply_onboarding(repo, dry_run=False)
    new_bytes = agents.read_bytes()
    assert new_bytes.startswith(before)
    assert new_bytes.endswith(after)
    assert b"OLD STALE BODY" not in new_bytes


def test_existing_config_not_clobbered(repo) -> None:
    """A pre-existing per-project config is left untouched (noop)."""
    cfg_path = pc.project_config_path(repo)
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text('{"implementer": "codex"}\n')

    plan = ro.apply_onboarding(repo, dry_run=False)
    assert json.loads(cfg_path.read_text()) == {"implementer": "codex"}
    config_action = next(a for a in plan.actions if a.kind == "config")
    assert config_action.action == "noop"


# ──────────────────────────  stale vs fresh managed block  ──────────────────────────


def test_stale_block_updated_in_place(repo) -> None:
    """AC5 — a managed block whose hash differs from the current render is
    replaced in place, leaving surrounding content untouched."""
    # Seed AGENTS.md with a stale managed block (body differs from current) plus
    # bracketing prose that must survive.
    before = "# Keep me before\n"
    after = "\n# Keep me after\n"
    stale_block = ro.render_block(ro.BLOCK_AGENTS, "OLD STALE BODY")
    (repo / ro.AGENTS_FILENAME).write_text(before + stale_block + after)

    plan = ro.apply_onboarding(repo, dry_run=False)
    agents_action = next(a for a in plan.actions if a.kind == "agents")
    assert agents_action.action == "update"

    new_text = (repo / ro.AGENTS_FILENAME).read_text()
    assert "# Keep me before" in new_text
    assert "# Keep me after" in new_text
    assert "OLD STALE BODY" not in new_text
    assert "DontPanic operating brief" in new_text
    # Exactly one managed block remains (replace, not append).
    assert new_text.count(ro._MARK_END) == 1


def test_fresh_block_left_unchanged(repo) -> None:
    """AC6 — re-onboarding a current managed block is a no-op (byte-identical)."""
    ro.apply_onboarding(repo, dry_run=False)
    first = (repo / ro.AGENTS_FILENAME).read_text()

    plan = ro.apply_onboarding(repo, dry_run=False)
    second = (repo / ro.AGENTS_FILENAME).read_text()
    assert first == second
    agents_action = next(a for a in plan.actions if a.kind == "agents")
    assert agents_action.action == "noop"


def test_version_bump_marks_block_stale(repo, monkeypatch) -> None:
    """A generator-version bump alone (body unchanged) makes a block stale."""
    ro.apply_onboarding(repo, dry_run=False)
    monkeypatch.setattr(ro, "ONBOARDING_GENERATOR_VERSION", "9.9")
    plan = ro.plan_onboarding(repo)
    agents_action = next(a for a in plan.actions if a.kind == "agents")
    assert agents_action.action == "update"


def test_brief_change_marks_block_stale(repo) -> None:
    """A change in the brief body (different content_hash) makes the AGENTS block
    stale — the block tracks the live brief, not a hand-copied string."""
    ro.apply_onboarding(repo, dry_run=False)
    # Inject a brief with different text → different agents-body → stale.
    mutated = agent_brief.RenderedBrief(
        generator_version=agent_brief.GENERATOR_VERSION,
        content_hash="deadbeef",
        text="TOTALLY DIFFERENT BRIEF TEXT\n",
    )
    plan = ro.plan_onboarding(repo, brief=mutated)
    agents_action = next(a for a in plan.actions if a.kind == "agents")
    assert agents_action.action == "update"


# ──────────────────────────  lowercase .claude.md handling  ──────────────────────────


def test_lowercase_claude_preserved_and_warned(repo) -> None:
    """AC7 — when only lowercase .claude.md exists, it is preserved untouched, an
    uppercase CLAUDE.md is created, and a warning is reported."""
    lower = repo / ro.LOWER_CLAUDE_FILENAME
    lower_content = "lowercase agent notes\n"
    lower.write_text(lower_content)

    plan = ro.apply_onboarding(repo, dry_run=False)
    # Lowercase untouched.
    assert lower.read_text() == lower_content
    # Uppercase created with the pointer block.
    assert (repo / ro.CLAUDE_FILENAME).is_file()
    warn = next((a for a in plan.actions if a.kind == "claude-lowercase"), None)
    assert warn is not None and warn.action == "warn"


def test_no_lowercase_warning_when_uppercase_present(repo) -> None:
    (repo / ro.LOWER_CLAUDE_FILENAME).write_text("x\n")
    (repo / ro.CLAUDE_FILENAME).write_text("y\n")
    plan = ro.plan_onboarding(repo)
    assert not any(a.kind == "claude-lowercase" for a in plan.actions)


def test_block_is_fresh_rejects_in_marker_tamper() -> None:
    """F003 codex finding: _block_is_fresh must not trust the marker hash alone.
    A block whose body is edited between the markers (marker hash untouched) is
    NOT fresh — the on-disk body must itself hash to the stored marker hash."""
    body = "OPERATING BRIEF BODY"
    block = ro.render_block("agent-brief", body)
    fresh_match = ro.find_block(block, "agent-brief")
    assert fresh_match is not None
    assert ro._block_is_fresh(fresh_match, body) is True

    # Tamper the body inside the markers, leaving the BEGIN marker (hash=) intact.
    tampered = block.replace(body, "MALICIOUS INJECTED TEXT")
    assert tampered != block
    tampered_match = ro.find_block(tampered, "agent-brief")
    assert tampered_match is not None
    # marker hash unchanged, but on-disk body no longer hashes to it -> not fresh
    assert tampered_match.group("hash") == fresh_match.group("hash")
    assert ro._block_is_fresh(tampered_match, body) is False


def test_apply_onboarding_rewrites_in_marker_tampered_block(repo) -> None:
    """End-to-end: re-onboarding heals an in-marker tamper, evicting injected
    text and restoring the canonical generated body (F003 codex finding). Before
    the fix, the marker hash alone was trusted, so a tampered body was judged
    'fresh' (noop) and the injection survived re-onboarding."""
    ro.apply_onboarding(repo, dry_run=False)
    agents = repo / ro.AGENTS_FILENAME
    canonical = agents.read_text()
    # "operating brief" appears in the generated body heading; tamper inside the
    # markers while leaving the BEGIN marker (hash=) untouched.
    assert "operating brief" in canonical
    tampered = canonical.replace("operating brief", "MALICIOUS INJECTED TEXT", 1)
    assert tampered != canonical
    agents.write_text(tampered)

    plan = ro.apply_onboarding(repo, dry_run=False)
    healed = agents.read_text()
    assert "MALICIOUS INJECTED TEXT" not in healed
    assert healed == canonical
    agents_action = next(a for a in plan.actions if a.kind == "agents")
    assert agents_action.action == "update"
