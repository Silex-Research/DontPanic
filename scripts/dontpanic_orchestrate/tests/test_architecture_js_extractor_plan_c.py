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
    # audit 2026-06-08 B1#7: `missing_extractors` is a list of dicts, so
    # `"javascript" not in missing` was a tautology that ALWAYS passed. Assert
    # against the real evidence_kind set.
    missing_kinds = {m["evidence_kind"] for m in (cov.get("missing_extractors") or [])}
    # javascript IS extracted now (js_import_crawler) → never a missing kind.
    assert "javascript" not in missing_kinds
    # HONESTY (audit B1#2): DontPanic itself ships unextracted .tsx/.jsx
    # (docs/design mockups, remotion skill), so the ceiling is correctly capped —
    # the Plan C slice-1 "ceiling lifts to high" claim was itself an over-claim.
    assert "typescript" in missing_kinds or "jsx" in missing_kinds
    assert cov["confidence_ceiling"] in {"low", "medium"}


# ── audit 2026-06-08 remediation: honest JS parsing ─────────────────────


def test_imports_inside_comments_and_strings_are_ignored(tmp_path):
    d = tmp_path / "dashboard"
    d.mkdir(parents=True)
    (d / "a.js").write_text(
        "// import x from './commented.js'\n"
        "/* import y from './block.js' */\n"
        "const s = \"import z from './string.js'\";\n"
        "import { real } from './real.js';\n"
    )
    nodes, edges = JS.extract_js_modules(tmp_path)
    titles = {n["title"] for n in nodes if n.get("unresolved")}
    assert "./commented.js" not in titles  # comment text is not an import (B1#3)
    assert "./block.js" not in titles
    assert "./string.js" not in titles
    # the one REAL relative import is still seen (as unresolved — target absent)
    assert any(n.get("title") == "./real.js" for n in nodes)


def test_export_from_and_dynamic_import_are_not_dropped(tmp_path):
    d = tmp_path / "dashboard"
    d.mkdir(parents=True)
    (d / "a.js").write_text(
        "export { thing } from 'reexported-vendor';\n"
        "export * from './star.js';\n"
        "const m = await import('dynlib');\n"
        "const t = await import(`./tpl/${name}.js`);\n"
    )
    nodes, _ = JS.extract_js_modules(tmp_path)
    titles = {n["title"] for n in nodes if n["type"] == "external"}
    assert "reexported-vendor" in titles      # export ... from (B1#4)
    assert "dynlib" in titles                 # dynamic import literal (B1#4)
    assert any("dynamic" in t or "${" in t for t in titles)  # interpolated dynamic surfaced


def test_dynamic_import_inside_template_interpolation_is_surfaced(tmp_path):
    # re-audit edge: import() nested in a template-literal ${...} (the mask blanks
    # template bodies) must still be surfaced, never silently dropped.
    d = tmp_path / "dashboard"
    d.mkdir(parents=True)
    (d / "a.js").write_text("const html = `<x>${import('./real.js')}</x>`;\n")
    nodes, _ = JS.extract_js_modules(tmp_path)
    assert any(n["type"] == "external" and n.get("unresolved")
               and "dynamic-import" in n["id"] for n in nodes)


def test_walk_prunes_node_modules(tmp_path):
    d = tmp_path / "dashboard"
    (d / "node_modules" / "pkg").mkdir(parents=True)
    (d / "node_modules" / "pkg" / "junk.js").write_text("import './deep.js';\n")
    (d / "real.js").write_text("export const x = 1;\n")
    nodes, _ = JS.extract_js_modules(tmp_path)
    paths = {n["source_path"] for n in nodes if n["type"] == "js_module"}
    assert "dashboard/real.js" in paths
    assert not any("node_modules" in p for p in paths)  # pruned, never walked (B1#6)


def test_present_typescript_drops_ceiling(tmp_path):
    # A repo with UNEXTRACTED TypeScript must not read "high" (B1#2).
    from dontpanic_orchestrate import architecture_contract as C
    (tmp_path / "app.tsx").write_text("export const X = 1;\n")
    nodes = [{"id": "m", "type": "module"}, {"id": "j", "type": "js_module"}]
    cov = C.compute_coverage(tmp_path, nodes)
    kinds = {m["evidence_kind"] for m in cov["missing_extractors"]}
    assert "typescript" in kinds
    assert cov["confidence_ceiling"] == "low"
