"""Plan 2026-06-08-001 (Plan B) — ADR/doc intent extractor + reconciler.

F001 extracts declared intent claims from decision docs (graceful absence);
F002 reconciles them against the as-built graph into a conservative diff keyed by
the Plan A taxonomy. The integration tests enter through the real build_view_state
surface and confirm the intent + diff layers Plan A reserved are now populated.

  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_architecture_intent_plan_b.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))
REPO_ROOT = HERE.parents[3]

from dontpanic_orchestrate import architecture_contract as C  # noqa: E402
from dontpanic_orchestrate import architecture_intent as I  # noqa: E402
from dontpanic_orchestrate import architecture_view_state as avs  # noqa: E402


# ── F001: ADR/doc intent extractor ──────────────────────────────────────


def test_extracts_declared_claims_from_real_adr():
    claims = I.extract_adr_claims(REPO_ROOT)
    assert claims, "repo has docs/adr/ADR-001 — expected at least one claim"
    adr1 = next(c for c in claims if c["id"] == "ADR-001")
    assert adr1["title"]
    assert adr1["status"] == "proposed"
    assert adr1["source_kind"] == "adr"
    assert adr1["evidence_basis"] == "declared"
    assert adr1["source_path"].endswith("ADR-001-external-capability-model.md")
    assert isinstance(adr1["references"], list) and adr1["references"]  # names symbols
    assert adr1["provenance"]["method"] == "adr_intent_extractor"


def test_absent_adr_dir_degrades_to_empty(tmp_path):
    assert I.extract_adr_claims(tmp_path) == []  # no docs/adr → empty, no crash


def test_filename_fallback_when_no_heading(tmp_path):
    d = tmp_path / "docs" / "adr"
    d.mkdir(parents=True)
    (d / "ADR-009-thing.md").write_text("Status: accepted\n\n## Decision\n\nuse widget_kind.\n")
    claims = I.extract_adr_claims(tmp_path)
    assert len(claims) == 1
    assert claims[0]["status"] == "accepted"
    assert "widget_kind" in claims[0]["references"]


# ── F002: as-built ↔ intent reconciler ──────────────────────────────────


def _claim(cid, refs, status="accepted"):
    return {"id": cid, "status": status, "references": refs}


def test_aligned_when_reference_resolves_to_as_built():
    nodes = [{"id": "module:x", "type": "module", "source_path": "scripts/dontpanic_orchestrate/foo.py"}]
    diff = I.reconcile_intent([_claim("ADR-001", ["foo"])], nodes)
    aligned = [d for d in diff if d["taxonomy"] == "aligned"]
    assert any(d["symbol"] == "foo" for d in aligned)


def test_documented_unimplemented_when_reference_resolves_to_nothing():
    diff = I.reconcile_intent([_claim("ADR-001", ["ghost_symbol"])], nodes=[])
    assert [d for d in diff if d["taxonomy"] == "documented_unimplemented" and d["symbol"] == "ghost_symbol"]


def test_superseded_claim_yields_stale_adr():
    diff = I.reconcile_intent([_claim("ADR-002", [], status="superseded")], nodes=[])
    assert [d for d in diff if d["taxonomy"] == "stale_adr" and d["claim_id"] == "ADR-002"]


def test_external_nodes_do_not_count_as_implemented():
    # an unresolved external endpoint must NOT make a claim look implemented.
    nodes = [{"id": "external:foo", "type": "external", "source_kind": "external",
              "unresolved": True, "title": "foo"}]
    diff = I.reconcile_intent([_claim("ADR-001", ["foo"])], nodes)
    assert all(d["taxonomy"] != "aligned" for d in diff)


def test_reconciler_is_deterministic_and_taxonomy_bounded():
    nodes = [{"id": "module:x", "type": "module", "source_path": "a/b.py"}]
    claims = [_claim("ADR-001", ["b", "missing"]), _claim("ADR-002", [], status="superseded")]
    a = I.reconcile_intent(claims, nodes)
    b = I.reconcile_intent(claims, nodes)
    assert a == b
    for entry in a:
        assert entry["taxonomy"] in C.DIFF_TAXONOMY


# ── integration: the real build_view_state surface ──────────────────────


def _build():
    return avs.build_view_state(avs.load_inputs(REPO_ROOT), repo_root=REPO_ROOT)


def test_real_build_populates_intent_and_diff_layers():
    vs = _build()
    layers = vs["layers"]
    assert layers["intent"]["populated"] is True
    claims = layers["intent"]["claims"]
    assert any(c["id"] == "ADR-001" and c["evidence_basis"] == "declared" for c in claims)
    # diff is populated + every entry is a bounded taxonomy value
    assert layers["diff"]
    for e in layers["diff"]:
        assert e["taxonomy"] in C.DIFF_TAXONOMY
    # coverage now reports the adr extractor honestly (covered, since ADR-001 exists)
    cov = {e["extractor"]: e for e in vs["coverage"]["extractors"]}
    assert cov["adr_intent_extractor"]["status"] == "covered"
