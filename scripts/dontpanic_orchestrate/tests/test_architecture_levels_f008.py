"""Navigable architecture — per-level Mermaid generator (plan 2026-06-06-004 F008, spec §9).

Pins: the flat graph is replaced by bounded, legible per-level slices; clusters derive from path
prefixes; per-node freshness colours drift vs fresh from source_fingerprint; the slices are
deterministic + diff-able; and drift is computed honestly from current file hashes.
"""

from __future__ import annotations

import hashlib

from dontpanic_orchestrate import architecture_levels as al


SNAPSHOT = {
    "schema_version": "1.0",
    "generated_at": "2026-06-06T00:00:00Z",
    "plans": [{"id": "p1"}, {"id": "p2"}],
    "schemas": [{"name": "operator-triage"}],
    "modules": [
        {"path": "scripts/orch/a.py", "name": "a", "imports": ["scripts.orch.b"], "public_symbols": ["A"], "summary": "a"},
        {"path": "scripts/orch/b.py", "name": "b", "imports": [], "public_symbols": ["B"], "summary": "b"},
        {"path": "dashboard/lib/x.js", "name": "x", "imports": ["scripts.orch.a"], "public_symbols": [], "summary": "x"},
    ],
    "source_fingerprint": {
        "algo": "sha256",
        "file_hashes": {"scripts/orch/a.py": "deadbeef", "scripts/orch/b.py": "cafef00d"},
    },
}


def test_clusters_derive_from_path_prefix():
    assert al.cluster_key("scripts/orch/a.py") == "scripts/orch"
    assert al.cluster_key("dashboard/lib/x.js") == "dashboard/lib"
    assert al.cluster_key("top.py") == "(root)"


def test_build_levels_emits_bounded_legible_slices():
    levels = al.build_levels(SNAPSHOT)
    assert {"L0", "L1", "L2"} <= set(levels)
    # one L3 per cluster
    assert "L3-scripts/orch" in levels and "L3-dashboard/lib" in levels
    # every slice is a small mermaid graph, never the whole 3-cluster plane at once
    for name, mmd in levels.items():
        assert mmd.startswith(("%%", "graph", "flowchart")) or "graph" in mmd.splitlines()[1]
        assert mmd.count("-->") < 25  # bounded


def test_per_node_freshness_colours_drift_vs_fresh():
    drifted = {"scripts/orch/a.py"}
    l2 = al.level_clusters(SNAPSHOT, drifted)
    # the cluster containing the drifted module is marked drift; the other stays fresh
    assert ":::drift" in l2
    assert ":::fresh" in l2
    l3 = al.level_subgraph(SNAPSHOT, "scripts/orch", drifted)
    # a.py drifted → drift class; b.py clean → fresh class
    assert "a_py" in l3.replace("/", "_") or "a.py" in l3
    assert ":::drift" in l3 and ":::fresh" in l3


def test_classdefs_present_so_colours_render():
    l2 = al.level_clusters(SNAPSHOT)
    assert "classDef fresh" in l2 and "classDef drift" in l2


def test_levels_are_deterministic():
    assert al.build_levels(SNAPSHOT) == al.build_levels(SNAPSHOT)


def test_compute_drift_reads_current_hashes(tmp_path):
    # write b.py matching its recorded hash; leave a.py mismatching → a.py drifts
    snap = {
        "source_fingerprint": {"algo": "sha256", "file_hashes": {
            "a.py": "0" * 64,  # wrong on purpose
            "b.py": hashlib.sha256(b"bee").hexdigest(),
        }},
        "modules": [],
    }
    (tmp_path / "a.py").write_text("changed", encoding="utf-8")
    (tmp_path / "b.py").write_bytes(b"bee")
    drifted = al.compute_drift(snap, tmp_path)
    assert "a.py" in drifted
    assert "b.py" not in drifted


def test_write_levels_writes_diffable_mmd_files(tmp_path):
    written = al.write_levels(SNAPSHOT, tmp_path)
    assert written  # at least L0/L1/L2 + clusters
    names = {p.name for p in written}
    assert "L0.mmd" in names and "L1.mmd" in names and "L2.mmd" in names
    # files are real mermaid text, regenerated deterministically
    again = al.write_levels(SNAPSHOT, tmp_path)
    assert [p.read_text() for p in written] == [p.read_text() for p in again]


def test_dense_cluster_paginates_into_bounded_slices():
    # a 60-file package must split into ≤25-node pages — ELK fixes layout, not legibility
    mods = [{"path": f"pkg/m{i}.py", "name": f"m{i}", "imports": [], "public_symbols": []} for i in range(60)]
    levels = al.build_levels({"modules": mods, "plans": [], "schemas": []})
    pages = [k for k in levels if k.startswith("L3-pkg")]
    assert len(pages) >= 3  # 60 / 25 → 3 pages
    for key, mmd in levels.items():
        if key.startswith("L3-"):
            assert mmd.count(":::") <= al._MAX_NODES  # EVERY slice stays legible


def test_write_levels_computes_drift_from_repo_root_by_default(tmp_path):
    (tmp_path / "x.py").write_text("changed", encoding="utf-8")  # ≠ recorded hash
    snap = {
        "modules": [{"path": "x.py", "name": "x", "imports": []}],
        "plans": [], "schemas": [],
        "source_fingerprint": {"algo": "sha256", "file_hashes": {"x.py": "0" * 64}},
    }
    written = al.write_levels(snap, tmp_path / "out", repo_root=tmp_path)
    # drift was computed from source_fingerprint without the caller passing `drifted`
    assert any(":::drift" in p.read_text() for p in written)


def test_empty_or_plans_only_snapshot_does_not_crash():
    # quantre-style: plans but zero modules
    levels = al.build_levels({"plans": [{"id": "p"}], "modules": [], "schemas": []})
    assert "L0" in levels and "L1" in levels
    assert not any(k.startswith("L3-") for k in levels)  # no clusters → no subgraphs
