"""Plan 2026-06-06-007 F001 — architecture graph levels + clusters.

The interactive component map consumes a normalized graph model. F001
adds two keys to the view-state alongside the existing
nodes/edges/freshness:

  * ``clusters`` — directory-derived groups forming a tree (root =
    "System"), each carrying its direct node ids + parent/child links +
    a numeric ``level``.
  * ``levels``   — the distinct depths, each listing the cluster ids at
    that depth (L0 = System).

The ``.mmd`` slices written by ``architecture_levels.write_levels`` are
an OPTIONAL, cache-only diffable export for docs/git review — NEVER the
page's render source.

Run targeted:
  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_architecture_levels_f007.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import architecture_levels as levels  # noqa: E402
from dontpanic_orchestrate import architecture_view_state as avs  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────


def _architecture() -> dict:
    def mod(path: str, name: str, imports=()) -> dict:
        return {
            "path": path,
            "name": name,
            "public_symbols": [],
            "imports": list(imports),
            "summary": "",
        }

    return {
        "schema_version": "1.0",
        "generated_at": "2026-06-06T00:00:00Z",
        "source_fingerprint": {
            "algo": "sha256",
            "files_count": 2,
            "file_hashes_root": "b" * 64,
            "file_hashes": {},
            "computed_at": "2026-06-06T00:00:00Z",
        },
        "modules": [
            mod(
                "scripts/dontpanic_orchestrate/cli.py",
                "dontpanic_orchestrate.cli",
                imports=["dontpanic_orchestrate.supervisor"],
            ),
            mod(
                "scripts/dontpanic_orchestrate/supervisor.py",
                "dontpanic_orchestrate.supervisor",
            ),
        ],
        "plans": [],
        "schemas": [],
    }


def _view_state(tmp_path: Path) -> dict:
    inputs = avs.BuildInputs(
        project_name=None,
        project_display_name=None,
        architecture_path=tmp_path / "architecture.json",
        architecture=_architecture(),
        flows=None,
        flows_path=None,
        status={"state": "fresh"},
    )
    return avs.build_view_state(inputs, repo_root=tmp_path)


# ── cluster_key derivation ──────────────────────────────────────────────


def test_cluster_key_is_the_source_directory():
    assert (
        levels.cluster_key("scripts/dontpanic_orchestrate/cli.py")
        == "scripts/dontpanic_orchestrate"
    )


def test_cluster_key_of_root_level_file_is_root():
    assert levels.cluster_key("README.md") == ""


def test_cluster_key_is_none_without_source_path():
    assert levels.cluster_key(None) is None
    assert levels.cluster_key("") is None


# ── clusters + levels emitted into the view-state ───────────────────────


def test_view_state_carries_clusters_and_levels(tmp_path):
    vs = _view_state(tmp_path)
    assert "clusters" in vs and isinstance(vs["clusters"], list)
    assert "levels" in vs and isinstance(vs["levels"], list)
    assert len(vs["clusters"]) > 0


def test_clusters_form_a_directory_tree_rooted_at_system(tmp_path):
    vs = _view_state(tmp_path)
    by_id = {c["id"]: c for c in vs["clusters"]}

    root = by_id["cluster:"]
    assert root["title"] == "System"
    assert root["level"] == 0
    assert root["parent_id"] is None

    leaf = by_id["cluster:scripts/dontpanic_orchestrate"]
    assert leaf["title"] == "dontpanic_orchestrate"
    assert leaf["level"] == 2
    assert leaf["parent_id"] == "cluster:scripts"
    # Both module nodes live directly in this cluster.
    assert "module:scripts/dontpanic_orchestrate/cli.py" in leaf["node_ids"]
    assert "module:scripts/dontpanic_orchestrate/supervisor.py" in leaf["node_ids"]

    # Parent links its child.
    assert "cluster:scripts/dontpanic_orchestrate" in by_id["cluster:scripts"]["child_cluster_ids"]


def test_nodes_without_source_path_attach_to_root():
    # External / derived nodes carry no source_path and fold into System.
    nodes = [
        {"id": "external:openai", "type": "external"},
        {"id": "module:a/b.py", "type": "module", "source_path": "a/b.py"},
    ]
    clusters, _ = levels.build_clusters_and_levels(nodes)
    by_id = {c["id"]: c for c in clusters}
    assert by_id["cluster:"]["node_ids"] == ["external:openai"]
    assert by_id["cluster:a"]["node_ids"] == ["module:a/b.py"]


def test_levels_list_groups_clusters_by_depth(tmp_path):
    vs = _view_state(tmp_path)
    by_level = {lvl["level"]: lvl for lvl in vs["levels"]}
    assert by_level[0]["cluster_ids"] == ["cluster:"]
    assert "cluster:scripts/dontpanic_orchestrate" in by_level[2]["cluster_ids"]


def test_clusters_are_deterministic(tmp_path):
    a = _view_state(tmp_path)
    b = _view_state(tmp_path)
    assert a["clusters"] == b["clusters"]
    assert a["levels"] == b["levels"]


def test_empty_architecture_still_emits_empty_clusters_levels(tmp_path):
    inputs = avs.BuildInputs(
        project_name=None,
        project_display_name=None,
        architecture_path=tmp_path / "architecture.json",
        architecture=None,
        flows=None,
        flows_path=None,
        status=None,
    )
    vs = avs.build_view_state(inputs, repo_root=tmp_path)
    assert vs["clusters"] == []
    assert vs["levels"] == []


# ── .mmd export (optional, cache-only, never the render source) ─────────


def test_write_levels_emits_diffable_mmd_into_cache(tmp_path):
    vs = _view_state(tmp_path)
    out_dir = tmp_path / "state"
    written = levels.write_levels(vs, out_dir=out_dir)
    assert written, "expected at least one .mmd slice"
    for p in written:
        assert p.suffix == ".mmd"
        # Cache-only: never escapes out_dir.
        assert out_dir in p.parents
        text = p.read_text(encoding="utf-8")
        assert text.startswith("flowchart")


def test_write_levels_is_byte_stable(tmp_path):
    vs = _view_state(tmp_path)
    first = {
        p.name: p.read_text(encoding="utf-8")
        for p in levels.write_levels(vs, out_dir=tmp_path / "a")
    }
    second = {
        p.name: p.read_text(encoding="utf-8")
        for p in levels.write_levels(vs, out_dir=tmp_path / "b")
    }
    assert first == second


def test_write_levels_noop_when_no_clusters(tmp_path):
    assert levels.write_levels({"clusters": [], "levels": []}, out_dir=tmp_path) == []
