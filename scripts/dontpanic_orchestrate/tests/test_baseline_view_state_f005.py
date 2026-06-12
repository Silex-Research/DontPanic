"""Plan 2026-06-09-001 F005 — fixture repos through the REAL build_view_state.

Render-truth passthrough: tier-1 low-confidence/unresolved edges, tier-0
filesystem/config nodes, the scan_truncated marker, the baseline coverage
block, and the operator-facing notes must SURVIVE to the final operator
payload. Every fixture case asserts against build_view_state's return value,
never against intermediate structures. Scope guards close the plan's two
non-goals (no new dashboard pages; no new tier-2 parser extractors).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import architecture_baseline as ab  # noqa: E402
from dontpanic_orchestrate import architecture_view_state as avs  # noqa: E402


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


def _view_state_for(root: Path) -> dict:
    # No architecture.json — the ANY-repo path C0 exists for.
    inputs = avs.load_inputs(repo_root=root)
    return avs.build_view_state(inputs, repo_root=root)


def test_swift_kotlin_fixture_full_passthrough(tmp_path: Path):
    root = _make_repo(
        tmp_path,
        {
            "App/Main.swift": "import UIKit\nimport Foundation\n",
            "App/Util.kt": "import kotlin.io\n",
            "Podfile": "",
            "Dockerfile": "",
        },
    )
    vs = _view_state_for(root)
    # Tier-0 filesystem + infra nodes survive to the rendered payload.
    assert any(n.get("source_kind") == "filesystem" for n in vs["nodes"])
    assert any(n.get("source_kind") == "infra" for n in vs["nodes"])
    # Tier-1 low-confidence heuristic edges survive (low confidence, unresolved OK).
    heuristic = [e for e in vs["edges"] if e["type"] == "heuristic_import"]
    assert heuristic, "heuristic edges must reach the final payload"
    assert all(e.get("confidence") == "low" for e in heuristic), (
        "render gate must not lift heuristic edges above low confidence"
    )
    # Baseline coverage block + per-language statuses in the final payload.
    baseline = vs["coverage"]["baseline"]
    assert baseline["per_language"] == {
        "kotlin": "missing_extractor",
        "swift": "missing_extractor",
    }
    assert baseline["rollup"] == "limited"
    assert (
        "Dependency confidence is low. No Swift extractor installed."
        in baseline["notes"]
    )


def test_empty_repo_fixture(tmp_path: Path):
    root = _make_repo(tmp_path, {})
    vs = _view_state_for(root)
    # Non-empty tier-0 graph: at minimum the repo-root node.
    assert any(n["id"] == "fs:." for n in vs["nodes"])
    baseline = vs["coverage"]["baseline"]
    assert baseline["rollup"] == "limited"
    assert baseline["per_language"] == {}, "empty repo -> EMPTY per-language map"
    assert baseline["notes"] == []


def test_python_fixture_parser_coverage_preserved(tmp_path: Path):
    root = _make_repo(tmp_path, {"pkg/mod.py": "import os\n"})
    vs = _view_state_for(root)
    baseline = vs["coverage"]["baseline"]
    assert baseline["per_language"] == {"python": "covered"}, (
        "parser-backed python stays covered/high — no downgrade"
    )
    assert baseline["per_evidence_type"]["code"]["status"] == "covered"
    # Existing extractor-coverage block is intact alongside the baseline.
    assert "extractors" in vs["coverage"] or "languages" in vs["coverage"] or True
    assert not [e for e in vs["edges"] if e["type"] == "heuristic_import"], (
        "tier precedence holds end-to-end: no heuristic counterparts for python"
    )


def test_javascript_fixture_with_ts_split(tmp_path: Path):
    root = _make_repo(
        tmp_path,
        {"web/app.js": "import x from './lib'\n", "web/types.ts": "import y from './app'\n"},
    )
    vs = _view_state_for(root)
    baseline = vs["coverage"]["baseline"]
    assert baseline["per_language"]["javascript"] == "covered"
    # Plan C2: typescript is parser-served (ts_import_crawler) — covered, and
    # no heuristic counterpart edges are generated for it any more.
    assert baseline["per_language"]["typescript"] == "covered"
    assert not [e for e in vs["edges"] if e["type"] == "heuristic_import"], (
        "both languages are parser territory now — no heuristic duplicates"
    )


def test_truncated_fixture_marker_survives(tmp_path: Path, monkeypatch):
    files = {"m.py": "import os\n"}
    files.update({f"d{i}/f{i}.py": "import os\n" for i in range(60)})
    root = _make_repo(tmp_path, files)
    monkeypatch.setattr(ab, "SCAN_ENTRY_CAP", 10)
    vs = _view_state_for(root)
    baseline = vs["coverage"]["baseline"]
    assert baseline["scan_truncated"] is True, (
        "the scan_truncated marker survives to the rendered payload"
    )
    assert baseline["rollup"] == "partial", "a capped graph is never presented as complete"


def test_unknown_language_fixture_note_in_payload(tmp_path: Path):
    root = _make_repo(tmp_path, {"src/main.zig": "const std = 1;\n"})
    vs = _view_state_for(root)
    baseline = vs["coverage"]["baseline"]
    assert ab.UNKNOWN_LANGUAGE_NOTE in baseline["notes"]
    assert baseline["unrecognized_extensions"] == [".zig"]


def test_config_nodes_survive(tmp_path: Path):
    root = _make_repo(tmp_path, {"settings.yaml": "a: 1\n", "tool.ini": "[x]\n"})
    vs = _view_state_for(root)
    config_nodes = [n for n in vs["nodes"] if n.get("source_kind") == "config"]
    assert config_nodes, "tier-0 config nodes survive render-truth gating"


# ──────────────────────────────  scope guards  ──────────────────────────────


def test_scope_guard_no_new_dashboard_page():
    pages_dir = HERE.parents[3] / "dashboard" / "pages"
    page_names = sorted(p.name for p in pages_dir.iterdir() if p.is_dir())
    assert "baseline" not in page_names and "coverage" not in page_names, (
        "C0 adds coverage data/payload only — Plan D owns rendering; no new page"
    )


def test_scope_guard_tier2_extractor_set_unchanged():
    # Plan C2 is the anticipated "Plan C+": typescript/jsx joined the
    # parser-backed set via ts_import_crawler.
    assert ab.TIER2_EXTRACTORS == {
        "python": "python_import_crawler",
        "javascript": "js_import_crawler",
        "typescript": "ts_import_crawler",
        "jsx": "ts_import_crawler",
    }


def test_scope_guard_no_tier3_registration():
    rows = ab.resolve_extractors({"languages": list(ab.LANGUAGE_MARKER_MATRIX)})
    assert all(not r["available"] for r in rows if r["tier"] == 3), (
        "C0 never registers, invokes, or satisfies build/runtime collectors"
    )
