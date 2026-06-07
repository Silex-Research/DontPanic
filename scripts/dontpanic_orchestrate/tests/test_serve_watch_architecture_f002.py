"""Serve watch — architecture snapshots retrigger a rebuild (plan 2026-06-06-003 F002).

The serve watcher previously fingerprinted only plan files + the static dashboard
tree + the registry. A tracked project's architecture map is none of those, so a
regen (commit-hook or manual) left the Architecture tab stale until a manual
rebuild. F002 adds each tracked project's architecture.json to the fingerprint.
"""

from __future__ import annotations

from pathlib import Path

from dontpanic_orchestrate import architecture, dashboard
from dontpanic_orchestrate import projects_registry as pr


def _fp(tmp: Path):
    return dashboard._source_fingerprint(  # noqa: SLF001
        plans_root=tmp / "plans",
        dashboard_dir=tmp / "dash",
        state_out_dir=tmp / "dash" / "state",
    )


def test_appearing_architecture_map_changes_the_fingerprint(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs" / "architecture").mkdir(parents=True)
    pr.add_project("proj", str(repo))

    before = _fp(tmp_path)
    # the map is absent → represented as ("architecture/proj", 0, 0)
    assert any(e[0] == "architecture/proj" for e in before)

    (repo / "docs" / architecture.DEFAULT_OUTPUT_REL.name).parent.mkdir(parents=True, exist_ok=True)
    (repo / architecture.DEFAULT_OUTPUT_REL).write_text('{"nodes": []}', encoding="utf-8")
    after = _fp(tmp_path)

    assert before != after  # the serve would rebuild on this tick


def test_editing_architecture_map_changes_the_fingerprint(tmp_path):
    repo = tmp_path / "repo"
    arch = repo / architecture.DEFAULT_OUTPUT_REL
    arch.parent.mkdir(parents=True)
    arch.write_text('{"nodes": []}', encoding="utf-8")
    pr.add_project("proj", str(repo))

    before = _fp(tmp_path)
    # a regen rewrites the map with more content (size + mtime change)
    arch.write_text('{"nodes": [{"id": "a"}, {"id": "b"}]}', encoding="utf-8")
    after = _fp(tmp_path)

    assert before != after


def test_untracked_repos_do_not_appear(tmp_path):
    # No projects registered → no architecture/* entries (watcher stays minimal).
    fp = _fp(tmp_path)
    assert not any(e[0].startswith("architecture/") for e in fp)
