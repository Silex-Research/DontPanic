"""Plan 2026-06-09-001 F003/F004 — tier-0/1 graph + tiered coverage.

Pins: containment tree connectivity, per-language heuristic edges for every
tier-1 matrix language, tier precedence (no heuristic counterparts for
parser-served languages), manifest-inferred annotations, non-empty graphs,
the shared truncation signal, the per-language map domain, the code
aggregation rule, filesystem/non-code satisfaction rules, the rollup
lattice, and the operator-facing notes.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import architecture_baseline as ab  # noqa: E402


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    root.mkdir(parents=True, exist_ok=True)
    return root


_TIER1_SAMPLES = {
    "swift": ("a.swift", "import Foundation\n"),
    "kotlin": ("a.kt", "import kotlin.io\n"),
    "typescript": ("a.ts", "import x from './b'\n"),
    "jsx": ("a.jsx", "import React from 'react'\n"),
    "go": ("a.go", 'import "fmt"\n'),
    "rust": ("a.rs", "use std::io;\n"),
}


# ──────────────────────────────  F003: graph  ──────────────────────────────


def test_heuristic_edge_for_every_tier1_language(tmp_path: Path):
    for lang, (fname, content) in _TIER1_SAMPLES.items():
        root = _make_repo(tmp_path / lang, {fname: content})
        graph = ab.build_baseline_graph(root)
        heuristic = [e for e in graph["edges"] if e["type"] == "heuristic_import"]
        assert heuristic, f"{lang}: a detected tier-1 language with imports must yield heuristic edges"
        assert all(e["evidence_basis"] in ("inferred", "unresolved") for e in heuristic)


def test_tier_precedence_no_heuristic_for_parser_served(tmp_path: Path):
    root = _make_repo(
        tmp_path,
        {"m.py": "import os\n", "n.js": "import x from './y'\n"},
    )
    graph = ab.build_baseline_graph(root)
    assert not [e for e in graph["edges"] if e["type"] == "heuristic_import"], (
        "python/javascript are parser-served — never duplicate heuristic counterparts"
    )


def test_relative_import_resolves(tmp_path: Path):
    root = _make_repo(
        tmp_path, {"a.ts": "import b from './b'\n", "b.ts": "export default 1\n"}
    )
    graph = ab.build_baseline_graph(root)
    edges = [e for e in graph["edges"] if e["type"] == "heuristic_import"]
    assert any(e["resolved"] for e in edges), "relative target present -> resolved endpoint"


def test_containment_tree_connects_all_fs_nodes(tmp_path: Path):
    root = _make_repo(
        tmp_path,
        {"src/deep/Cargo.toml": "", "docs/x.md": "# d", "Dockerfile": ""},
    )
    graph = ab.build_baseline_graph(root)
    contains = {e["to"]: e["from"] for e in graph["edges"] if e["type"] == "contains"}
    fs_nodes = [n for n in graph["nodes"] if n["id"].startswith("fs:") and n["id"] != "fs:."]
    for node in fs_nodes:
        cursor = node["id"]
        hops = 0
        while cursor != "fs:." and hops < 100:
            assert cursor in contains, f"{node['id']}: disconnected from the root tree"
            cursor = contains[cursor]
            hops += 1
        assert cursor == "fs:.", "every tier-0 node reaches the repo root via contains"


def test_empty_repo_yields_nonempty_graph(tmp_path: Path):
    root = tmp_path / "empty"
    root.mkdir()
    graph = ab.build_baseline_graph(root)
    assert any(n["id"] == "fs:." for n in graph["nodes"]), "repo-root node always present"


def test_infra_nodes_emitted(tmp_path: Path):
    root = _make_repo(tmp_path, {"Dockerfile": "", "deploy/main.tf": ""})
    graph = ab.build_baseline_graph(root)
    infra_nodes = [n for n in graph["nodes"] if n.get("source_kind") == "infra"]
    assert len(infra_nodes) >= 2


def test_manifest_inferred_frameworks_are_annotations_not_nodes(tmp_path: Path):
    root = _make_repo(
        tmp_path, {"package.json": '{"dependencies": {"react": "^18.0.0"}}'}
    )
    graph = ab.build_baseline_graph(root)
    manifest = next(n for n in graph["nodes"] if n.get("source_kind") == "manifest")
    assert manifest["annotations"]["app_frameworks"] == ["react"]
    assert not [n for n in graph["nodes"] if n.get("type") == "app_framework"], (
        "never fabricated standalone framework nodes"
    )


def test_shared_truncation_signal(tmp_path: Path):
    files = {f"d{i}/f{i}.swift": "import A\n" for i in range(40)}
    root = _make_repo(tmp_path, files)
    profile = ab.detect_project(root, scan_cap=10)
    graph = ab.build_baseline_graph(root, profile, scan_cap=10)
    coverage = ab.build_baseline_coverage(profile, graph)
    assert profile["scan_truncated"] and graph["scan_truncated"] and coverage["scan_truncated"], (
        "ONE scan_truncated signal across detector, graph, and coverage"
    )


def test_graph_deterministic_and_pure(tmp_path: Path):
    root = _make_repo(tmp_path, {"a.swift": "import A\n", "Cargo.toml": ""})
    g1 = ab.build_baseline_graph(root)
    g2 = ab.build_baseline_graph(root)
    assert g1 == g2
    assert not (root / ".cache").exists(), "no cache/state writes"


# ──────────────────────────────  F004: coverage  ──────────────────────────────


def _coverage_for(tmp_path: Path, files: dict[str, str], **kwargs):
    root = _make_repo(tmp_path, files)
    profile = ab.detect_project(root, **kwargs)
    graph = ab.build_baseline_graph(root, profile, **kwargs)
    return ab.build_baseline_coverage(profile, graph)


def test_per_language_map_domain(tmp_path: Path):
    cov = _coverage_for(tmp_path / "a", {"m.py": "import os\n", "a.swift": "import A\n"})
    assert set(cov["per_language"]) == {"python", "swift"}, "detected languages ONLY"
    assert "not_found" not in cov["per_language"].values(), (
        "not_found is reserved/unused in the per-language domain"
    )
    empty = _coverage_for(tmp_path / "b", {})
    assert empty["per_language"] == {}, "empty repo -> empty map"


def test_code_aggregation_rule(tmp_path: Path):
    pure_py = _coverage_for(tmp_path / "p", {"m.py": "import os\n"})
    assert pure_py["per_evidence_type"]["code"]["status"] == "covered"
    mixed = _coverage_for(tmp_path / "m", {"m.py": "import os\n", "a.swift": "import A\n"})
    assert mixed["per_evidence_type"]["code"]["status"] == "partial", (
        "any detected language lacking tier-2 caps code at partial, never covered"
    )
    assert mixed["per_language"] == {"python": "covered", "swift": "missing_extractor"}
    none = _coverage_for(tmp_path / "n", {})
    assert none["per_evidence_type"]["code"]["status"] == "not_found"


def test_filesystem_satisfaction_rule(tmp_path: Path):
    empty = _coverage_for(tmp_path / "e", {})
    assert empty["per_evidence_type"]["filesystem"]["status"] == "covered", (
        "filesystem is satisfied structurally by the tier-0 inventory (repo-root node)"
    )
    files = {f"d{i}/f{i}.swift": "import A\n" for i in range(40)}
    capped = _coverage_for(tmp_path / "t", files, scan_cap=10)
    assert capped["per_evidence_type"]["filesystem"]["status"] == "partial"


def test_non_code_satisfaction_triple(tmp_path: Path):
    cov = _coverage_for(tmp_path / "x", {"Cargo.toml": "", "Dockerfile": ""})
    assert cov["per_evidence_type"]["manifest"]["status"] == "covered"
    assert cov["per_evidence_type"]["infra"]["status"] == "covered"
    assert cov["per_evidence_type"]["adr"]["status"] == "not_found", (
        "an undetected class reads not_found, never covered"
    )
    statuses = {v["status"] for k, v in cov["per_evidence_type"].items()}
    assert "missing_extractor" not in statuses, (
        "non-code classes are never missing_extractor in C0 — tier-0 IS their extractor"
    )


def test_runtime_reserved_never_demotes(tmp_path: Path):
    cov = _coverage_for(tmp_path / "r", {"m.py": "import os\n"})
    assert cov["per_evidence_type"]["runtime"] == {
        "status": "not_found",
        "tier": 3,
        "reserved": True,
    }
    assert cov["rollup"] == "covered", "reserved runtime must not demote the rollup"


def test_rollup_lattice_pins(tmp_path: Path):
    assert _coverage_for(tmp_path / "1", {})["rollup"] == "limited"
    assert _coverage_for(tmp_path / "2", {"a.swift": "import A\n"})["rollup"] == "limited"
    assert _coverage_for(tmp_path / "3", {"m.py": "import os\n"})["rollup"] == "covered"
    assert (
        _coverage_for(tmp_path / "4", {"m.py": "import os\n", "a.swift": "import A\n"})["rollup"]
        == "partial"
    )
    # Root-level .py so python IS detected before the cap trips — the repo is
    # otherwise covered and ONLY truncation demotes it.
    files = {"m.py": "import os\n"}
    files.update({f"d{i}/f{i}.py": "import os\n" for i in range(40)})
    assert _coverage_for(tmp_path / "5", files, scan_cap=10)["rollup"] == "partial", (
        "scan_truncated demotes an otherwise-covered rollup to partial"
    )


def test_low_confidence_notes_rendered(tmp_path: Path):
    cov = _coverage_for(tmp_path / "n1", {"a.swift": "// no imports at all\n"})
    assert "Dependency confidence is low. No Swift extractor installed." in cov["notes"], (
        "the note is emitted even when the language produced zero heuristic edges"
    )
    pure = _coverage_for(tmp_path / "n2", {"m.py": "import os\n"})
    assert pure["notes"] == [], "no note for fully parser-backed repos"


def test_unknown_language_note(tmp_path: Path):
    cov = _coverage_for(tmp_path / "u", {"main.zig": "const x = 1;\n"})
    assert ab.UNKNOWN_LANGUAGE_NOTE in cov["notes"]
    assert cov["unrecognized_extensions"] == [".zig"]
