"""Plan 2026-06-08-002 (Plan C slice 1) — JavaScript/TS import extractor.

F001 extracts the dashboard ES module graph (relative imports → as-built nodes +
edges; unresolved/vendor imports stay visible). F002 lifts the coverage ceiling:
javascript is no longer a missing extractor. Integration enters through the real
build_view_state surface.

  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_architecture_js_extractor_plan_c.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))
REPO_ROOT = HERE.parents[3]

from dontpanic_orchestrate import architecture_contract as C  # noqa: E402
from dontpanic_orchestrate import architecture_js as JS  # noqa: E402
from dontpanic_orchestrate import architecture_view_state as avs  # noqa: E402


# ── F001: JS/TS import extractor ─────────────────────────────────────────


def test_extracts_real_dashboard_modules_and_edges():
    nodes, edges = JS.extract_js_modules(REPO_ROOT)
    mods = [n for n in nodes if n["type"] == "js_module"]
    assert len(mods) > 10  # the dashboard ships dozens of ES modules
    assert all(n["source_path"].startswith("dashboard/") for n in mods)
    assert any(e["type"] == "import" and not e.get("unresolved") for e in edges)  # resolved import


def test_absent_dashboard_degrades_to_empty(tmp_path):
    assert JS.extract_js_modules(tmp_path) == ([], [])  # no dashboard/ → empty, no crash


def test_relative_resolves_and_bare_specifier_is_unresolved_external(tmp_path):
    d = tmp_path / "dashboard" / "lib"
    d.mkdir(parents=True)
    (d / "b.js").write_text("export const x = 1;\n")
    (d / "a.js").write_text("import { x } from './b.js';\nimport 'vendorlib';\n")
    nodes, edges = JS.extract_js_modules(tmp_path)
    a, b = JS.js_module_id("dashboard/lib/a.js"), JS.js_module_id("dashboard/lib/b.js")
    # resolved relative import → a real module→module edge
    assert any(e["from"] == a and e["to"] == b and not e.get("unresolved") for e in edges)
    # bare specifier → unresolved external endpoint, never dropped
    ext = JS.external_id("vendorlib")
    assert any(n["id"] == ext and n["unresolved"] and n["source_kind"] == "external" for n in nodes)
    assert any(e["from"] == a and e["to"] == ext and e["unresolved"] for e in edges)


def test_unresolved_relative_import_is_visible_not_dropped(tmp_path):
    d = tmp_path / "dashboard"
    d.mkdir(parents=True)
    (d / "a.js").write_text("import './does-not-exist.js';\n")
    nodes, edges = JS.extract_js_modules(tmp_path)
    assert any(n.get("unresolved") and n["source_kind"] == "unknown" for n in nodes)


def test_extractor_is_deterministic(tmp_path):
    d = tmp_path / "dashboard"
    d.mkdir(parents=True)
    (d / "a.js").write_text("import './b.js';\n")
    (d / "b.js").write_text("export function f() {}\n")
    assert JS.extract_js_modules(tmp_path) == JS.extract_js_modules(tmp_path)


# ── F002: coverage ceiling lift (real build_view_state surface) ──────────


def _build():
    return avs.build_view_state(avs.load_inputs(REPO_ROOT), repo_root=REPO_ROOT)


def test_real_build_includes_contract_stamped_js_modules():
    vs = _build()
    mods = [n for n in vs["nodes"] if n["type"] == "js_module"]
    assert mods, "build_view_state should include the dashboard JS modules"
    m = mods[0]
    assert m["source_kind"] == "code"
    assert m["evidence_basis"] == "observed"


def test_javascript_no_longer_missing_and_ceiling_lifts():
    vs = _build()
    cov = vs["coverage"]
    extractors = {e["extractor"]: e for e in cov["extractors"]}
    # the JS extractor is now reported, covered (the dashboard has JS)
    assert "js_import_crawler" in extractors
    assert extractors["js_import_crawler"]["status"] in C.COVERAGE_STATUSES
    assert extractors["js_import_crawler"]["status"] == "covered"
    # javascript is no longer counted as a missing extractor for DontPanic itself
    missing = cov.get("missing_extractors") or []
    assert "javascript" not in missing
    # with JS extracted, DontPanic's own map is no longer forced to the low ceiling
    assert cov["confidence_ceiling"] != "low"
