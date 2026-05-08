"""F001 — git_state porcelain parser + read-only capture.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_git_state.py

Covers plan 2026-05-01-004 F001 acceptance:
  - parse_porcelain returns GitState with the 5 keys, each a list (possibly empty).
  - Per-status parametrized cases plus mixed, empty, JSON round-trip.
  - capture() returns None on not-a-git-repo (no exception).
  - Read-only proofs: argv whitelist, porcelain-snapshot identity, fs isolation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import git_state  # noqa: E402

# ────────────────────────────  parse_porcelain matrix  ────────────────────────────


# `git status --porcelain=v1 -z` emits NUL-terminated entries. Each entry is
# `XY <space> <path>` where X is the staged/index status and Y is the
# worktree status. Renames consume two entries (origin then dest); we don't
# detect renames in v0 (D005-style narrowing) — they appear as their R/D
# combo in the porcelain stream.
def _porcelain(*entries: str) -> str:
    """Build a NUL-terminated porcelain payload from entry strings."""
    return "".join(e + "\0" for e in entries)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # staged add
        (
            _porcelain("A  scripts/new_module.py"),
            {
                "staged": [{"path": "scripts/new_module.py", "status": "A"}],
                "unstaged_modified": [],
                "untracked": [],
                "deleted_staged": [],
                "deleted_unstaged": [],
            },
        ),
        # staged modify
        (
            _porcelain("M  scripts/edit.py"),
            {
                "staged": [{"path": "scripts/edit.py", "status": "M"}],
                "unstaged_modified": [],
                "untracked": [],
                "deleted_staged": [],
                "deleted_unstaged": [],
            },
        ),
        # unstaged modify
        (
            _porcelain(" M scripts/edit.py"),
            {
                "staged": [],
                "unstaged_modified": [{"path": "scripts/edit.py", "status": "M"}],
                "untracked": [],
                "deleted_staged": [],
                "deleted_unstaged": [],
            },
        ),
        # untracked
        (
            _porcelain("?? scripts/wip.py"),
            {
                "staged": [],
                "unstaged_modified": [],
                "untracked": ["scripts/wip.py"],
                "deleted_staged": [],
                "deleted_unstaged": [],
            },
        ),
        # deleted staged (D in index column)
        (
            _porcelain("D  scripts/gone.py"),
            {
                "staged": [],
                "unstaged_modified": [],
                "untracked": [],
                "deleted_staged": ["scripts/gone.py"],
                "deleted_unstaged": [],
            },
        ),
        # deleted unstaged (D in worktree column)
        (
            _porcelain(" D scripts/gone.py"),
            {
                "staged": [],
                "unstaged_modified": [],
                "untracked": [],
                "deleted_staged": [],
                "deleted_unstaged": ["scripts/gone.py"],
            },
        ),
    ],
    ids=[
        "staged_add",
        "staged_modify",
        "unstaged_modify",
        "untracked",
        "deleted_staged",
        "deleted_unstaged",
    ],
)
def test_parse_porcelain_single_status(raw: str, expected: dict) -> None:
    parsed = git_state.parse_porcelain(raw)
    assert parsed == expected


def test_parse_porcelain_empty() -> None:
    assert git_state.parse_porcelain("") == {
        "staged": [],
        "unstaged_modified": [],
        "untracked": [],
        "deleted_staged": [],
        "deleted_unstaged": [],
    }


def test_parse_porcelain_mixed() -> None:
    raw = _porcelain(
        "A  scripts/new.py",
        " M scripts/edit.py",
        "?? scripts/wip.py",
        "D  scripts/gone.py",
        " D scripts/lost.py",
        "M  scripts/staged_edit.py",
    )
    parsed = git_state.parse_porcelain(raw)
    assert parsed == {
        "staged": [
            {"path": "scripts/new.py", "status": "A"},
            {"path": "scripts/staged_edit.py", "status": "M"},
        ],
        "unstaged_modified": [{"path": "scripts/edit.py", "status": "M"}],
        "untracked": ["scripts/wip.py"],
        "deleted_staged": ["scripts/gone.py"],
        "deleted_unstaged": ["scripts/lost.py"],
    }


def test_parse_porcelain_index_and_worktree_modify() -> None:
    """`MM <path>` — same file staged AND modified-after-stage. Both columns fire."""
    raw = _porcelain("MM scripts/dual.py")
    parsed = git_state.parse_porcelain(raw)
    assert parsed["staged"] == [{"path": "scripts/dual.py", "status": "M"}]
    assert parsed["unstaged_modified"] == [{"path": "scripts/dual.py", "status": "M"}]


def test_parse_porcelain_paths_with_spaces() -> None:
    """NUL-delimited stream tolerates spaces in paths without escaping."""
    raw = _porcelain("A  scripts/has spaces.py", "?? other path/wip.py")
    parsed = git_state.parse_porcelain(raw)
    assert parsed["staged"] == [{"path": "scripts/has spaces.py", "status": "A"}]
    assert parsed["untracked"] == ["other path/wip.py"]


def test_parse_porcelain_json_roundtrip() -> None:
    """Pin the envelope shape: dict → JSON → dict is byte-identical."""
    raw = _porcelain("A  a.py", " M b.py", "?? c.py", "D  d.py", " D e.py")
    parsed = git_state.parse_porcelain(raw)
    rt = json.loads(json.dumps(parsed))
    assert rt == parsed


# ───────────────────────────  capture() integration  ───────────────────────────


def _init_git_repo(repo: Path) -> None:
    """Init a quiet git repo with deterministic identity."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)


def test_capture_returns_none_outside_git_repo(tmp_path: Path) -> None:
    """Acceptance (5): not-a-git-repo case returns None, no exception."""
    assert git_state.capture(tmp_path) is None


def test_capture_real_repo_round_trip(tmp_path: Path) -> None:
    """End-to-end: real repo with each status, capture matches porcelain output."""
    _init_git_repo(tmp_path)
    # committed baseline
    (tmp_path / "committed.py").write_text("# committed\n")
    subprocess.run(["git", "add", "committed.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    # produce one of each status
    (tmp_path / "staged_add.py").write_text("# new\n")
    subprocess.run(["git", "add", "staged_add.py"], cwd=tmp_path, check=True)

    (tmp_path / "committed.py").write_text("# unstaged change\n")  # unstaged_modify

    (tmp_path / "untracked.py").write_text("# wip\n")  # untracked

    state = git_state.capture(tmp_path)
    assert state is not None
    assert {"path": "staged_add.py", "status": "A"} in state["staged"]
    assert {"path": "committed.py", "status": "M"} in state["unstaged_modified"]
    assert "untracked.py" in state["untracked"]


# ──────────────────────  read-only proofs (acceptance 7a-7c)  ──────────────────────


def test_read_only_proof_argv_whitelist() -> None:
    """7a: only allowed argv lists. Source-level grep against the module."""
    src = Path(git_state.__file__).read_text()
    # Allowed: ['git', 'status', '--porcelain=v1', '-z'] and
    # ['git', 'rev-parse', '--show-toplevel'] (repo detection).
    # Anything else with subprocess + 'git' is forbidden.
    forbidden_subcommands = (
        "'add'",
        '"add"',
        "'commit'",
        '"commit"',
        "'stash'",
        '"stash"',
        "'checkout'",
        '"checkout"',
        "'restore'",
        '"restore"',
        "'reset'",
        '"reset"',
        "'rm'",
        '"rm"',
        "'clean'",
        '"clean"',
        "'push'",
        '"push"',
        "'fetch'",
        '"fetch"',
    )
    for needle in forbidden_subcommands:
        assert needle not in src, f"git_state.py must not reference git subcommand {needle}"


def test_read_only_proof_porcelain_snapshot_identity(tmp_path: Path) -> None:
    """7b: porcelain output identical before/after capture()."""
    _init_git_repo(tmp_path)
    (tmp_path / "a.py").write_text("# a\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)
    (tmp_path / "b.py").write_text("# untracked\n")

    before = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    ).stdout

    git_state.capture(tmp_path)

    after = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    ).stdout

    assert before == after


def test_audit_writer_creates_git_state_sidecar(tmp_path: Path) -> None:
    """F001 acceptance (4): writing an audit envelope drops a git-state sidecar.

    Uses an existing valid audit fixture from plan 2026-05-01-005 evidence dir.
    Sidecar must land at <plan_dir>/evidence/git-state-{iteration}-{role}.json
    and round-trip to the same shape as a direct ``git_state.capture()`` call.
    """
    from dontpanic_orchestrate import audit_writer  # local import keeps test cohesive

    repo_root = HERE.parents[3]
    fixture_path = (
        repo_root
        / "docs"
        / "plans"
        / "2026-05-01-005-feat-target-context-platform-fix"
        / "evidence"
        / "f001"
        / "fixtures"
        / "case-c-golden-valid-struct-valid-prelude.json"
    )
    audit = json.loads(fixture_path.read_text())
    audit.pop("_fixture_notes", None)
    audit["agent"] = "claude"
    parts = audit["audit_id"].split("#")
    if len(parts) == 3:
        parts[1] = "claude"
        audit["audit_id"] = "#".join(parts)

    _init_git_repo(tmp_path)
    (tmp_path / "tracked.py").write_text("# tracked\n")
    subprocess.run(["git", "add", "tracked.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    (tmp_path / "wip.py").write_text("# wip\n")  # untracked

    out = audit_writer.write(audit, tmp_path, feature_id="F001")
    assert out.exists()

    sidecar = tmp_path / "evidence" / f"git-state-{audit['iteration']}-{audit['agent_role']}.json"
    assert sidecar.exists(), f"expected sidecar at {sidecar}"
    persisted = json.loads(sidecar.read_text())
    assert "wip.py" in persisted["untracked"]
    assert set(persisted.keys()) == {
        "staged",
        "unstaged_modified",
        "untracked",
        "deleted_staged",
        "deleted_unstaged",
    }


def test_audit_writer_skips_sidecar_outside_git_repo(tmp_path: Path) -> None:
    """F001 acceptance (5): not-a-git-repo path skips sidecar without raising."""
    from dontpanic_orchestrate import audit_writer

    repo_root = HERE.parents[3]
    fixture_path = (
        repo_root
        / "docs"
        / "plans"
        / "2026-05-01-005-feat-target-context-platform-fix"
        / "evidence"
        / "f001"
        / "fixtures"
        / "case-c-golden-valid-struct-valid-prelude.json"
    )
    audit = json.loads(fixture_path.read_text())
    audit.pop("_fixture_notes", None)
    audit["agent"] = "claude"
    parts = audit["audit_id"].split("#")
    if len(parts) == 3:
        parts[1] = "claude"
        audit["audit_id"] = "#".join(parts)

    out = audit_writer.write(audit, tmp_path, feature_id="F001")
    assert out.exists()

    sidecar_dir = tmp_path / "evidence"
    if sidecar_dir.exists():
        # Directory may be created elsewhere; the specific sidecar must not.
        assert not list(sidecar_dir.glob("git-state-*.json"))


def test_read_only_proof_filesystem_isolation(tmp_path: Path) -> None:
    """7c: capture() creates/modifies no files in the repo tree."""
    _init_git_repo(tmp_path)
    (tmp_path / "tracked.py").write_text("# tracked\n")
    subprocess.run(["git", "add", "tracked.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    (tmp_path / "wip.py").write_text("# wip\n")

    def snapshot(root: Path) -> dict[str, tuple[int, float]]:
        out: dict[str, tuple[int, float]] = {}
        for p in root.rglob("*"):
            if ".git" in p.parts:
                continue
            if p.is_file():
                st = p.stat()
                out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
        return out

    before = snapshot(tmp_path)
    git_state.capture(tmp_path)
    after = snapshot(tmp_path)

    assert before == after
