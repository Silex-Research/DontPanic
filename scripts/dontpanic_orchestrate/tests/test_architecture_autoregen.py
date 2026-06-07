"""Architecture auto-refresh — regen-on-build, cache-only (plan 2026-06-06-003 F001).

A tracked project with a missing/stale architecture map must self-heal during the
dashboard build — regenerating into the dashboard CACHE so the Architecture tab
renders, without ever touching the tracked repo's working tree (no surprise git
changes). Replaces the "NO SYSTEM MAP YET → run this command" human card.
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import dashboard as D


def _make_repo(root: Path) -> Path:
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    (root / "src" / "b.py").write_text("import a\n", encoding="utf-8")
    (root / "docs" / "plans").mkdir(parents=True)
    return root


def test_missing_map_self_heals_into_cache_without_touching_repo(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    out = tmp_path / "cache"
    out.mkdir()

    D.build(
        plans_root=repo / "docs" / "plans",
        out_dir=out,
        check_architecture=True,
        repo_root=repo,
        project_name="repo",
    )

    # regenerated into the dashboard cache…
    assert (out / "architecture.json").is_file()
    # …and the tracked repo's working tree is UNTOUCHED (cache-only contract)
    assert not (repo / "docs" / "architecture" / "architecture.json").exists()
    # …and the view-state the tab reads now has a map (was empty before the fix)
    vs = json.loads((out / "architecture-view-state.json").read_text(encoding="utf-8"))
    assert len(vs.get("nodes", [])) >= 1


def test_fresh_map_is_not_regenerated(tmp_path):
    # When the committed snapshot is already current, the build must NOT regen
    # (the fingerprint check keeps steady-state builds cheap).
    repo = _make_repo(tmp_path / "repo")
    # generate + commit the snapshot into the repo so status() reports "fresh"
    from dontpanic_orchestrate import architecture

    architecture.regen(repo, with_html=False)
    assert architecture.status(repo)["state"] == "fresh"

    out = tmp_path / "cache"
    out.mkdir()
    D.build(
        plans_root=repo / "docs" / "plans",
        out_dir=out,
        check_architecture=True,
        repo_root=repo,
        project_name="repo",
    )
    # fresh → no cache regen copy written (build reads the committed snapshot)
    assert not (out / "architecture.json").exists()


def test_build_never_raises_when_repo_unreadable(tmp_path):
    # Best-effort: a non-existent repo_root must not crash the build.
    out = tmp_path / "cache"
    out.mkdir()
    rep = D.build(
        plans_root=tmp_path / "nope" / "plans",
        out_dir=out,
        check_architecture=True,
        repo_root=tmp_path / "nope",
        project_name="ghost",
    )
    assert rep is not None  # build completed despite missing repo
