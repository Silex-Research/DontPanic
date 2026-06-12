"""Plan 2026-06-08-005 (Plan C2) — TypeScript/TSX/JSX extractor + coverage
exclusions.

F001 — first-party .ts/.tsx/.jsx scan into ts_module nodes (source_path-
bearing) plus relative-import edges; import-type and export-from forms
parsed; unresolved imports surface as low-confidence unresolved endpoints
(never dropped); build_view_state includes them with source_kind code.

F002 — documentation-mockup and skill-asset trees are excluded from both
the extractor scan and the coverage presence scan; typescript/jsx are no
longer missing_extractor when first-party TS/JSX is extracted or absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import architecture_baseline as BASE  # noqa: E402
from dontpanic_orchestrate import architecture_js as JS  # noqa: E402


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


class TestF001Extractor:
    def test_ts_modules_and_relative_edges(self, tmp_path):
        _write(tmp_path, "src/app.ts", "import { x } from './lib/util';\n")
        _write(tmp_path, "src/lib/util.ts", "export const x = 1;\n")
        nodes, edges = JS.extract_ts_modules(tmp_path)
        mods = {n["id"]: n for n in nodes if n["type"] == "ts_module"}
        a = JS.ts_module_id("src/app.ts")
        b = JS.ts_module_id("src/lib/util.ts")
        assert a in mods and b in mods
        assert mods[a]["source_path"] == "src/app.ts"  # source_path-bearing
        assert any(e["from"] == a and e["to"] == b for e in edges)
        assert all(e["extractor"] == "ts_import_crawler" for e in edges)

    def test_tsx_and_jsx_files_are_scanned(self, tmp_path):
        _write(tmp_path, "src/App.tsx", "import { B } from './Button';\n")
        _write(tmp_path, "src/Button.jsx", "export function B() {}\n")
        nodes, edges = JS.extract_ts_modules(tmp_path)
        ids = {n["id"] for n in nodes}
        assert JS.ts_module_id("src/App.tsx") in ids
        assert JS.ts_module_id("src/Button.jsx") in ids
        assert any(
            e["from"] == JS.ts_module_id("src/App.tsx")
            and e["to"] == JS.ts_module_id("src/Button.jsx")
            for e in edges
        )

    def test_import_type_form_is_parsed(self, tmp_path):
        _write(tmp_path, "src/a.ts", "import type { T } from './types';\n")
        _write(tmp_path, "src/types.ts", "export type T = string;\n")
        _, edges = JS.extract_ts_modules(tmp_path)
        assert any(
            e["from"] == JS.ts_module_id("src/a.ts")
            and e["to"] == JS.ts_module_id("src/types.ts")
            for e in edges
        )

    def test_export_from_form_is_parsed(self, tmp_path):
        _write(tmp_path, "src/index.ts", "export { x } from './impl';\n")
        _write(tmp_path, "src/impl.ts", "export const x = 1;\n")
        _, edges = JS.extract_ts_modules(tmp_path)
        assert any(
            e["from"] == JS.ts_module_id("src/index.ts")
            and e["to"] == JS.ts_module_id("src/impl.ts")
            for e in edges
        )

    def test_unresolved_import_is_low_confidence_endpoint_never_dropped(self, tmp_path):
        _write(tmp_path, "src/a.ts", "import { gone } from './missing';\n")
        nodes, edges = JS.extract_ts_modules(tmp_path)
        unresolved = [n for n in nodes if n.get("unresolved")]
        assert unresolved, "unresolved relative import must surface, never be dropped"
        assert unresolved[0]["evidence_basis"] == "unresolved"
        assert any(e.get("unresolved") for e in edges)

    def test_build_view_state_includes_ts_modules_with_source_kind_code(self, tmp_path):
        """Mirrors C1: extracted module graphs ride the architecture-present
        branch of build_view_state."""
        import json as _json

        from dontpanic_orchestrate import architecture_view_state as avs

        _write(tmp_path, "src/app.ts", "import { x } from './lib/util';\n")
        _write(tmp_path, "src/lib/util.ts", "export const x = 1;\n")
        arch = {
            "schema_version": "1.0",
            "generated_at": "2026-06-12T00:00:00Z",
            "source_fingerprint": {
                "algo": "sha256",
                "files_count": 1,
                "file_hashes_root": "a" * 64,
                "file_hashes": {},
                "computed_at": "2026-06-12T00:00:00Z",
            },
            "modules": [
                {
                    "path": "src/app.py",
                    "name": "app",
                    "public_symbols": [],
                    "imports": [],
                    "summary": "entry",
                }
            ],
            "schemas": [],
            "plans": [],
        }
        target = tmp_path / "docs" / "architecture" / "architecture.json"
        target.parent.mkdir(parents=True)
        target.write_text(_json.dumps(arch) + "\n")
        state = avs.build_view_state(
            avs.load_inputs(repo_root=tmp_path), repo_root=tmp_path
        )
        ts_nodes = [n for n in state["nodes"] if n.get("type") == "ts_module"]
        assert ts_nodes, "view state must include extracted ts_module nodes"
        assert all(n["source_kind"] == "code" for n in ts_nodes)
        assert all(n.get("source_path") for n in ts_nodes)


class TestF002Exclusions:
    def test_non_product_trees_excluded_from_extractor(self, tmp_path):
        _write(tmp_path, "docs/design/mockup/page.jsx", "import './x';\n")
        _write(
            tmp_path,
            "claude/skills/video/assets/chart.tsx",
            "import { a } from './b';\n",
        )
        nodes, edges = JS.extract_ts_modules(tmp_path)
        assert nodes == [] and edges == []

    def test_non_product_trees_excluded_from_language_presence_scan(self, tmp_path):
        _write(tmp_path, "docs/design/mockup/page.jsx", "// jsx\n")
        _write(tmp_path, "claude/skills/video/assets/chart.tsx", "// tsx\n")
        _write(tmp_path, "scripts/main.py", "x = 1\n")
        profile = BASE.detect_project(tmp_path)
        assert "typescript" not in profile["languages"]
        assert "jsx" not in profile["languages"]
        assert "python" in profile["languages"]

    def test_product_ts_is_detected_and_covered_not_missing_extractor(self, tmp_path):
        _write(tmp_path, "src/main.ts", "export const x = 1;\n")
        _write(tmp_path, "src/App.jsx", "export function A() {}\n")
        profile = BASE.detect_project(tmp_path)
        assert "typescript" in profile["languages"]
        assert "jsx" in profile["languages"]
        coverage = BASE.build_baseline_coverage(
            profile, {"nodes": [], "edges": [], "scan_truncated": False}
        )
        assert coverage["per_language"]["typescript"] == "covered"
        assert coverage["per_language"]["jsx"] == "covered"
        assert coverage["per_language"]["typescript"] != "missing_extractor"

    def test_dontpanic_shape_only_non_product_ts_keeps_ceiling_unforced(self, tmp_path):
        """A repo shaped like DontPanic (python + javascript product code,
        TS/JSX ONLY under docs mockups + skill assets) must not have its
        code-coverage ceiling forced low by typescript/jsx."""
        _write(tmp_path, "scripts/main.py", "x = 1\n")
        _write(tmp_path, "dashboard/app.js", "export const a = 1;\n")
        _write(tmp_path, "docs/design/mockup/page.jsx", "// mockup\n")
        _write(tmp_path, "claude/skills/video/assets/chart.tsx", "// asset\n")
        profile = BASE.detect_project(tmp_path)
        coverage = BASE.build_baseline_coverage(
            profile, {"nodes": [], "edges": [], "scan_truncated": False}
        )
        assert coverage["per_evidence_type"]["code"]["status"] == "covered"
        assert coverage["per_evidence_type"]["code"]["confidence_ceiling"] == "high"

    def test_docs_markers_still_detected_despite_language_exclusion(self, tmp_path):
        """The exclusion is scoped to the LANGUAGE presence scan — doc/adr
        marker detection still sees the docs tree."""
        _write(tmp_path, "docs/adr/ADR-001-choice.md", "# ADR-001: choice\n")
        profile = BASE.detect_project(tmp_path)
        assert profile["adr"], "ADR markers under docs/ must still be detected"
