"""Plan 2026-06-07-001 — architecture evidence contract v0 (F001-F004).

Pure-logic tests for the contract module: per-node/edge stamping + confidence
precedence (F001), unresolved classification (F002), extractor coverage with the
load-bearing missing_extractor case (F003), and the as_built/intent/diff shell
(F004).

  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_architecture_contract_v0.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dontpanic_orchestrate import architecture_contract as C  # noqa: E402


# ── F001: per-node/edge contract + confidence precedence ────────────────


def test_stamp_module_node_is_observed_high():
    nodes = [{"id": "module:a", "type": "module", "source_path": "a.py"}]
    C.apply_evidence_contract(nodes, [])
    n = nodes[0]
    assert n["source_kind"] == "code"
    assert n["evidence_basis"] == "observed"
    assert n["confidence"] == "high"  # observed + resolved (has source_path)
    assert n["provenance"] == {
        "source_path": "a.py",
        "resolved": True,
        "method": "python_import_crawler",
    }


def test_stamp_command_node_is_declared_medium():
    nodes = [{"id": "command:x", "type": "command", "source_path": "cli.py"}]
    C.apply_evidence_contract(nodes, [])
    assert nodes[0]["evidence_basis"] == "declared"
    assert nodes[0]["confidence"] == "medium"  # declared + cites source_path


def test_unresolved_node_is_low_regardless_of_type():
    nodes = [
        {
            "id": "external:foo",
            "type": "external",
            "evidence_basis": "unresolved",
            "source_kind": "external",
            "unresolved": True,
        }
    ]
    C.apply_evidence_contract(nodes, [])
    assert nodes[0]["confidence"] == "low"
    assert nodes[0]["provenance"]["resolved"] is False


def test_resolved_import_edge_is_high_unresolved_edge_is_low():
    edges = [
        {"id": "e1", "type": "import", "from": "a", "to": "b"},
        {"id": "e2", "type": "import", "from": "a", "to": "ext", "unresolved": True},
    ]
    C.apply_evidence_contract([], edges)
    assert edges[0]["confidence"] == "high" and edges[0]["provenance"]["resolved"]
    assert edges[1]["confidence"] == "low"
    assert edges[1]["evidence_basis"] == "unresolved"
    assert edges[1]["provenance"]["resolved"] is False


def test_every_node_and_edge_carries_all_four_fields():
    nodes = [{"id": "n", "type": "schema", "source_path": "s.json"}]
    edges = [{"id": "e", "type": "calls", "from": "a", "to": "b"}]
    C.apply_evidence_contract(nodes, edges)
    for item in (*nodes, *edges):
        assert {"source_kind", "evidence_basis", "confidence", "provenance"} <= set(item)
        assert item["source_kind"] in C.SOURCE_KINDS
        assert item["evidence_basis"] in C.EVIDENCE_BASES
        assert item["confidence"] in C.CONFIDENCE_LEVELS


def test_stamping_is_idempotent():
    nodes = [{"id": "module:a", "type": "module", "source_path": "a.py"}]
    C.apply_evidence_contract(nodes, [])
    first = dict(nodes[0])
    C.apply_evidence_contract(nodes, [])
    assert nodes[0] == first


# ── F002: unresolved classification ─────────────────────────────────────


def test_stdlib_and_third_party_classify_external():
    fp = {"dontpanic_orchestrate", "models"}
    assert C.classify_unresolved_endpoint("pathlib", fp) == "external"
    assert C.classify_unresolved_endpoint("pydantic", fp) == "external"
    assert C.classify_unresolved_endpoint("collections.abc", fp) == "external"


def test_first_party_unresolved_classifies_unknown():
    fp = {"dontpanic_orchestrate", "models"}
    # a first-party ref that did not resolve = genuine missing evidence
    assert C.classify_unresolved_endpoint("dontpanic_orchestrate.ghost", fp) == "unknown"
    assert C.classify_unresolved_endpoint("models.absent", fp) == "unknown"


def test_is_stdlib_recognizes_stdlib():
    assert C.is_stdlib("json")
    assert C.is_stdlib("collections.abc")
    assert not C.is_stdlib("pydantic")


# ── F003: extractor coverage + missing_extractor honesty ────────────────


def test_coverage_reports_covered_and_not_found(tmp_path):
    nodes = [
        {"id": "m", "type": "module"},
        {"id": "p", "type": "plan"},
    ]
    cov = C.compute_coverage(tmp_path, nodes)
    by = {e["extractor"]: e for e in cov["extractors"]}
    assert by["python_import_crawler"]["status"] == "covered"
    assert by["plan_index"]["status"] == "covered"
    assert by["json_schema_scan"]["status"] == "not_found"  # no schema nodes
    for s in cov["extractors"]:
        assert s["status"] in C.COVERAGE_STATUSES


def test_missing_extractor_drives_ceiling_down(tmp_path):
    # A repo with Swift source but no Swift extractor must NOT render confident.
    (tmp_path / "App.swift").write_text("// swift")
    nodes = [{"id": "m", "type": "module"}]
    cov = C.compute_coverage(tmp_path, nodes)
    kinds = {m["evidence_kind"] for m in cov["missing_extractors"]}
    assert "swift" in kinds
    assert all(m["status"] == "missing_extractor" for m in cov["missing_extractors"])
    assert cov["confidence_ceiling"] == "low"


def test_clean_python_repo_can_reach_high_ceiling(tmp_path):
    # No unextracted-language markers + every extractor covered → high ceiling.
    nodes = [
        {"id": "m", "type": "module"},
        {"id": "s", "type": "schema"},
        {"id": "p", "type": "plan"},
        {"id": "c", "type": "capability"},
        {"id": "pg", "type": "page"},
        {"id": "md", "type": "metadata"},
    ]
    cov = C.compute_coverage(tmp_path, nodes)
    assert cov["missing_extractors"] == []
    assert cov["confidence_ceiling"] == "high"


def test_not_applicable_kind_does_not_lower_ceiling(tmp_path):
    # gradle absent in a pure-Python repo → simply not listed as missing.
    nodes = [{"id": "m", "type": "module"}]
    cov = C.compute_coverage(tmp_path, nodes)
    kinds = {m["evidence_kind"] for m in cov["missing_extractors"]}
    assert "gradle" not in kinds  # not_applicable, not missing_extractor


# ── F004: as_built / intent / diff shell ────────────────────────────────


def test_layer_shell_shape():
    nodes = [{"id": "a"}, {"id": "b"}]
    edges = [{"id": "e"}]
    shell = C.build_layer_shell(nodes, edges)
    assert shell["as_built"] == {"node_count": 2, "edge_count": 1, "is_current": True}
    assert shell["intent"]["claims"] == [] and shell["intent"]["populated"] is False
    assert shell["diff"] == []
    assert tuple(shell["diff_taxonomy"]) == C.DIFF_TAXONOMY
    # the diff taxonomy names are the exact contract enum (no reword)
    assert "implemented_undocumented" in shell["diff_taxonomy"]
    assert "documented_unimplemented" in shell["diff_taxonomy"]
    assert "unknown_confidence" in shell["diff_taxonomy"]
