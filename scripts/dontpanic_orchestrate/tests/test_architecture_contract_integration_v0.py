"""Plan 2026-06-07-001 — contract enters the REAL view-state surface.

Per the QA-sufficiency contract, this builds the architecture view-state through
the same ``load_inputs`` → ``build_view_state`` path the dashboard build uses,
against the live repo, and asserts the F001-F004 contract is actually emitted
(not just that the pure helpers work in isolation).

  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_architecture_contract_integration_v0.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))
REPO_ROOT = HERE.parents[3]

from dontpanic_orchestrate import architecture_contract as C  # noqa: E402
from dontpanic_orchestrate import architecture_view_state as avs  # noqa: E402


def _build():
    inputs = avs.load_inputs(REPO_ROOT)
    return avs.build_view_state(inputs, repo_root=REPO_ROOT)


def test_real_build_stamps_contract_on_every_node_and_edge():
    vs = _build()
    assert vs["nodes"], "expected a non-empty real graph"
    for item in (*vs["nodes"], *vs["edges"]):
        assert item["source_kind"] in C.SOURCE_KINDS
        assert item["evidence_basis"] in C.EVIDENCE_BASES
        assert item["confidence"] in C.CONFIDENCE_LEVELS
        prov = item["provenance"]
        assert set(prov) == {"source_path", "resolved", "method"}


def test_real_build_emits_unresolved_edges_instead_of_dropping():
    vs = _build()
    unresolved_edges = [e for e in vs["edges"] if e.get("unresolved")]
    assert unresolved_edges, "F002: unresolved imports must be emitted, not dropped"
    for e in unresolved_edges:
        assert e["evidence_basis"] == "unresolved"
        assert e["confidence"] == "low"
        assert e["provenance"]["resolved"] is False
    # the endpoints exist as low-confidence external|unknown nodes
    ext = [
        n for n in vs["nodes"]
        if n["evidence_basis"] == "unresolved" and n["source_kind"] in ("external", "unknown")
    ]
    assert ext, "F002: unresolved endpoints must be visible nodes"


def test_real_build_has_resolved_high_confidence_imports():
    vs = _build()
    resolved_imports = [
        e for e in vs["edges"]
        if e["type"] == "import" and not e.get("unresolved")
    ]
    assert resolved_imports
    assert any(e["confidence"] == "high" for e in resolved_imports)


def test_real_build_carries_coverage_block_with_js_now_extracted():
    vs = _build()
    cov = vs["coverage"]
    assert cov["contract_version"] == "v0"
    statuses = {e["status"] for e in cov["extractors"]}
    assert statuses <= set(C.COVERAGE_STATUSES)
    assert any(e["status"] == "covered" for e in cov["extractors"])
    # Plan C slice 1 ships the JS import extractor → javascript is no longer a
    # missing kind and js_import_crawler is covered.
    missing_kinds = {m["evidence_kind"] for m in cov["missing_extractors"]}
    assert "javascript" not in missing_kinds
    assert any(e["extractor"] == "js_import_crawler" and e["status"] == "covered"
               for e in cov["extractors"])
    # HONESTY (audit 2026-06-08 B1#2): DontPanic itself ships UNEXTRACTED .tsx/.jsx
    # (docs/design React mockups, remotion skill assets), so the ceiling must stay
    # honestly capped — NOT "high". Removing javascript wholesale had wrongly
    # presented the map as fully covered.
    assert "typescript" in missing_kinds or "jsx" in missing_kinds
    assert cov["confidence_ceiling"] in {"low", "medium"}


def test_real_build_carries_layer_shell():
    vs = _build()
    layers = vs["layers"]
    assert layers["as_built"]["node_count"] == len(vs["nodes"])
    assert layers["as_built"]["edge_count"] == len(vs["edges"])
    # Plan A reserved intent/diff empty; Plan B (2026-06-08-001) populates them
    # from ADR/doc intent. The shell shape persists; the lists are now lists.
    assert isinstance(layers["intent"]["claims"], list)
    assert isinstance(layers["diff"], list)
    assert tuple(layers["diff_taxonomy"]) == C.DIFF_TAXONOMY


def test_render_view_state_is_stable_json():
    # The cache serializer must still round-trip the enriched shape.
    vs = _build()
    text = avs.render_view_state(vs)
    assert '"coverage"' in text and '"layers"' in text
    assert '"source_kind"' in text and '"evidence_basis"' in text
