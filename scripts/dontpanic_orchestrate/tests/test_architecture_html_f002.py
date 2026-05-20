"""Fixture tests for plan 2026-05-19-004 F002 — architecture HTML renderer.

Covers the acceptance criteria:
  (a) HTML renders without error from a valid snapshot
  (b) errors clearly when architecture.json is missing or invalid
  (c) generated HTML parses as valid HTML5 (well-formed, balanced tags,
      single <html>/<head>/<body>, doctype, viewport meta)
  (d) all three SVG diagrams (module graph, plan lifecycle, supervisor
      state machine) are present
  (e) CLI `regen` writes both JSON + HTML by default; `--json-only`
      skips the HTML companion

Tests use a hand-rolled synthetic snapshot — they don't shell out to the
real Crawler, so HTML rendering is exercised independently of F001.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from dontpanic_orchestrate import architecture as arch
from dontpanic_orchestrate import architecture_html as arch_html


def _build_snapshot() -> dict[str, Any]:
    """A minimal, schema-valid snapshot that exercises every rendering
    branch: multiple modules with intra-package imports, schemas with a
    version, plans in every lifecycle state we care about, a truncated
    flag exercised below in a separate test."""
    return {
        "schema_version": "1.0",
        "generated_at": "2026-05-20T03:00:00Z",
        "source_fingerprint": {
            "algo": "sha256",
            "files_count": 4,
            "file_hashes_root": "a" * 64,
            "file_hashes": {
                "scripts/dontpanic_orchestrate/supervisor.py": "b" * 64,
                "scripts/dontpanic_orchestrate/audit_writer.py": "c" * 64,
            },
            "computed_at": "2026-05-20T03:00:00Z",
        },
        "modules": [
            {
                "path": "scripts/dontpanic_orchestrate/__init__.py",
                "name": "dontpanic_orchestrate",
                "public_symbols": [],
                "imports": [],
                "summary": "DontPanic cross-agent orchestration runtime.",
            },
            {
                "path": "scripts/dontpanic_orchestrate/supervisor.py",
                "name": "dontpanic_orchestrate.supervisor",
                "public_symbols": ["Supervisor", "dispatch_volley", "QuotaExceeded"],
                # The first import resolves to another module in this snapshot —
                # it should show up as an edge in the dependency graph.
                "imports": ["dontpanic_orchestrate.audit_writer", "json", "pathlib"],
                "summary": "Supervisor orchestration entry point.",
            },
            {
                "path": "scripts/dontpanic_orchestrate/audit_writer.py",
                "name": "dontpanic_orchestrate.audit_writer",
                "public_symbols": ["write_audit"],
                "imports": ["os", "json"],
                "summary": "Audit writer.",
            },
        ],
        "schemas": [
            {
                "path": "claude/shared/schemas/v1.0/plan.schema.json",
                "name": "plan.schema",
                "version": "1.0.0",
                "validator_present": True,
            },
            {
                "path": "claude/shared/schemas/v1.0/features.schema.json",
                "name": "features.schema",
                "version": "1.0.0",
                "validator_present": False,
            },
        ],
        "plans": [
            {"id": "2026-05-19-100-feat-alpha", "title": "Alpha", "status": "active",     "features_count": 2},
            {"id": "2026-05-19-200-fix-beta",   "title": "Beta",  "status": "completed",  "features_count": 1},
            {"id": "2026-05-19-300-feat-gamma", "title": "Gamma", "status": "draft",      "features_count": 0},
            {"id": "2026-05-19-400-fix-delta",  "title": "Delta", "status": "blocked",    "features_count": 3},
        ],
    }


# ── HTML5 well-formedness checker ─────────────────────────────────────


class _StructuralCounter(HTMLParser):
    """A tiny HTML5 well-formedness probe.

    We don't pull html5lib (not in the dev env); we use the stdlib
    HTMLParser to count open vs close tags + verify a single document
    structure. Void elements are tracked separately so they don't unbalance.
    """

    VOID_TAGS = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input",
         "link", "meta", "param", "source", "track", "wbr"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.tag_open_count: dict[str, int] = {}
        self.tag_close_count: dict[str, int] = {}
        self.unbalanced: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tag_open_count[tag] = self.tag_open_count.get(tag, 0) + 1
        if tag not in self.VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing form (e.g. <br/>) — count as void.
        self.tag_open_count[tag] = self.tag_open_count.get(tag, 0) + 1

    def handle_endtag(self, tag: str) -> None:
        self.tag_close_count[tag] = self.tag_close_count.get(tag, 0) + 1
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            # Pop down to matching tag and record everything popped as out-of-order.
            while self.stack and self.stack[-1] != tag:
                self.unbalanced.append(self.stack.pop())
            if self.stack:
                self.stack.pop()
        else:
            self.unbalanced.append(f"closing {tag} without open")


def _assert_well_formed_html(html_doc: str) -> None:
    assert html_doc.lower().lstrip().startswith("<!doctype html>"), (
        "HTML5 documents must start with <!doctype html>"
    )
    parser = _StructuralCounter()
    parser.feed(html_doc)
    parser.close()
    assert not parser.stack, f"unclosed tags at end of doc: {parser.stack}"
    assert not parser.unbalanced, f"unbalanced tags encountered: {parser.unbalanced}"
    # Exactly one html / head / body — guards against accidental duplication.
    for tag in ("html", "head", "body"):
        assert parser.tag_open_count.get(tag, 0) == 1, (
            f"expected exactly one <{tag}>, saw {parser.tag_open_count.get(tag, 0)}"
        )
        assert parser.tag_close_count.get(tag, 0) == 1, (
            f"expected exactly one </{tag}>, saw {parser.tag_close_count.get(tag, 0)}"
        )


# ── (a) Happy path: HTML renders ───────────────────────────────────────


def test_a_render_html_returns_complete_document_from_valid_snapshot() -> None:
    snap = _build_snapshot()
    out = arch_html.render_html(snap)
    assert isinstance(out, str)
    assert "<!doctype html>" in out.lower()
    assert "<title>DontPanic Architecture</title>" in out
    # Header surfaces the schema version and generated_at.
    assert "schema v1.0" in out
    assert "2026-05-20T03:00:00Z" in out
    # Mobile-responsive viewport meta tag.
    assert 'name="viewport"' in out
    # At least one CSS media query for the wider-viewport layout.
    assert "@media (min-width:" in out
    # Each plan id appears in the plans table.
    for pid in ("2026-05-19-100-feat-alpha", "2026-05-19-400-fix-delta"):
        assert pid in out


def test_a2_render_writes_file_at_target_path(tmp_path: Path) -> None:
    snap = _build_snapshot()
    json_path = tmp_path / "architecture.json"
    json_path.write_text(json.dumps(snap), encoding="utf-8")
    html_path = tmp_path / "architecture.html"
    written = arch_html.render(json_path, html_path)
    assert written == html_path
    assert html_path.is_file()
    body = html_path.read_text(encoding="utf-8")
    assert "<title>DontPanic Architecture</title>" in body


def test_a3_render_defaults_html_path_alongside_json(tmp_path: Path) -> None:
    snap = _build_snapshot()
    json_path = tmp_path / "architecture.json"
    json_path.write_text(json.dumps(snap), encoding="utf-8")
    written = arch_html.render(json_path)
    assert written == tmp_path / "architecture.html"
    assert written.is_file()


# ── (b) Error surfaces ─────────────────────────────────────────────────


def test_b_missing_json_raises_render_error_with_regen_pointer(tmp_path: Path) -> None:
    missing = tmp_path / "architecture.json"
    with pytest.raises(arch_html.ArchitectureRenderError) as excinfo:
        arch_html.render(missing)
    msg = str(excinfo.value)
    assert "not found" in msg
    assert "dontpanic architecture regen" in msg


def test_b2_invalid_json_raises_render_error(tmp_path: Path) -> None:
    bad = tmp_path / "architecture.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(arch_html.ArchitectureRenderError) as excinfo:
        arch_html.render(bad)
    msg = str(excinfo.value)
    assert "not valid JSON" in msg
    assert "dontpanic architecture regen" in msg


def test_b3_snapshot_missing_required_keys_raises(tmp_path: Path) -> None:
    incomplete = {"schema_version": "1.0"}
    out = tmp_path / "architecture.json"
    out.write_text(json.dumps(incomplete), encoding="utf-8")
    with pytest.raises(arch_html.ArchitectureRenderError) as excinfo:
        arch_html.render(out)
    msg = str(excinfo.value)
    assert "missing required fields" in msg
    # Names every missing top-level key the renderer needs.
    for key in arch_html.iter_required_top_keys():
        assert key in msg


def test_b4_snapshot_with_wrong_types_raises() -> None:
    snap = _build_snapshot()
    snap["modules"] = "not a list"  # type: ignore[assignment]
    with pytest.raises(arch_html.ArchitectureRenderError) as excinfo:
        arch_html.render_html(snap)
    msg = str(excinfo.value)
    assert "modules" in msg
    assert "expected list" in msg


@pytest.mark.parametrize(
    "field,bad_entry",
    [
        ("modules", "bad-module-entry"),
        ("schemas", 42),
        ("plans", None),
    ],
)
def test_b5_snapshot_with_non_object_list_entries_raises(
    field: str, bad_entry: Any
) -> None:
    """Element-level shape check: a string/int/None inside modules/schemas/
    plans must surface as ArchitectureRenderError with the regen pointer,
    not bubble up as a raw AttributeError when downstream code calls
    ``entry.get(...)``. Regression for the codex-auditor F002 i0 finding."""
    snap = _build_snapshot()
    snap[field] = [bad_entry]  # type: ignore[assignment]
    with pytest.raises(arch_html.ArchitectureRenderError) as excinfo:
        arch_html.render_html(snap)
    msg = str(excinfo.value)
    assert field in msg
    assert "expected object" in msg
    assert "dontpanic architecture regen" in msg


# ── (b6) source_fingerprint typed validation ───────────────────────────


def test_b6_source_fingerprint_files_count_must_be_int() -> None:
    """Regression: codex-auditor F002 i1 (high/security). A non-int
    ``files_count`` (e.g., a string containing HTML) used to flow through
    the renderer's fallback branch unescaped, allowing raw HTML injection
    into the page. Validator now rejects non-int up-front so the bypass
    can't be reached."""
    snap = _build_snapshot()
    snap["source_fingerprint"]["files_count"] = "<script>x</script>"
    with pytest.raises(arch_html.ArchitectureRenderError) as excinfo:
        arch_html.render_html(snap)
    msg = str(excinfo.value)
    assert "source_fingerprint.files_count" in msg
    assert "expected integer" in msg
    assert "dontpanic architecture regen" in msg


def test_b7_source_fingerprint_files_count_must_be_non_negative() -> None:
    snap = _build_snapshot()
    snap["source_fingerprint"]["files_count"] = -1
    with pytest.raises(arch_html.ArchitectureRenderError) as excinfo:
        arch_html.render_html(snap)
    assert "expected integer >= 0" in str(excinfo.value)


def test_b8_source_fingerprint_file_hashes_root_must_be_string() -> None:
    snap = _build_snapshot()
    snap["source_fingerprint"]["file_hashes_root"] = 12345
    with pytest.raises(arch_html.ArchitectureRenderError) as excinfo:
        arch_html.render_html(snap)
    assert "source_fingerprint.file_hashes_root" in str(excinfo.value)


def test_b9_render_escapes_files_count_fallback_branch() -> None:
    """Defense in depth: even if a future refactor lets a non-int
    ``files_count`` reach _render_header (e.g., validator bypass for a
    streaming path), the rendered HTML must escape it. We test the
    private helper directly to exercise the fallback branch without
    going through the validator."""
    from dontpanic_orchestrate import architecture_html as ah
    rendered = ah._render_header(
        generated_at="2026-05-20T00:00:00Z",
        schema_version="1.0",
        fp={"file_hashes_root": "deadbeefcafe1234", "files_count": "<script>x</script>"},
        truncated=False,
        truncation_marker="",
    )
    assert "<script>x</script> files tracked" not in rendered
    assert "&lt;script&gt;x&lt;/script&gt; files tracked" in rendered


# ── (c) HTML5 validity ─────────────────────────────────────────────────


def test_c_generated_html_is_well_formed_html5() -> None:
    html_doc = arch_html.render_html(_build_snapshot())
    _assert_well_formed_html(html_doc)


def test_c2_well_formed_even_with_empty_collections() -> None:
    """The empty-snapshot path renders placeholder SVGs/table rows but
    must still produce a well-formed document. Regression guard for
    'empty list' branches in each section renderer."""
    snap = _build_snapshot()
    snap["modules"] = []
    snap["schemas"] = []
    snap["plans"] = []
    html_doc = arch_html.render_html(snap)
    _assert_well_formed_html(html_doc)
    assert "No modules" in html_doc
    assert "No schemas" in html_doc
    assert "No plans" in html_doc


# ── (d) SVG diagrams ───────────────────────────────────────────────────


def test_d_html_contains_all_three_svg_diagrams() -> None:
    html_doc = arch_html.render_html(_build_snapshot())
    # Each diagram has a stable, unique id.
    assert 'id="module-graph"' in html_doc
    assert 'id="plan-lifecycle"' in html_doc
    assert 'id="supervisor-state"' in html_doc
    # Each is a real <svg> element.
    assert html_doc.count("<svg") >= 3
    assert html_doc.count("</svg>") >= 3
    # Every <svg> closes.
    assert html_doc.count("<svg") == html_doc.count("</svg>")


def test_d2_module_graph_has_node_per_module_and_at_least_one_edge() -> None:
    html_doc = arch_html.render_html(_build_snapshot())
    # 3 modules → ≥3 <circle>s in the module-graph SVG. (Plan lifecycle
    # also uses <circle>, so we slice down to the module graph block.)
    start = html_doc.index('id="module-graph"')
    end = html_doc.index("</svg>", start)
    module_svg = html_doc[start:end]
    assert module_svg.count("<circle ") >= 3
    # supervisor.py imports audit_writer → one <line> at minimum.
    assert module_svg.count("<line ") >= 1


def test_d3_plan_lifecycle_renders_node_counts_from_snapshot() -> None:
    html_doc = arch_html.render_html(_build_snapshot())
    start = html_doc.index('id="plan-lifecycle"')
    end = html_doc.index("</svg>", start)
    lifecycle_svg = html_doc[start:end]
    # Each of the canonical lifecycle states is labeled.
    for state in ("draft", "active", "completed", "abandoned", "blocked"):
        assert state in lifecycle_svg
    # The fixture has 1 active, 1 completed, 1 draft, 1 blocked → numeric
    # labels must show up in the SVG.
    assert ">1<" in lifecycle_svg
    assert ">0<" in lifecycle_svg  # abandoned has zero in the fixture


def test_d4_supervisor_state_diagram_lists_every_known_state() -> None:
    html_doc = arch_html.render_html(_build_snapshot())
    start = html_doc.index('id="supervisor-state"')
    end = html_doc.index("</svg>", start)
    sv_svg = html_doc[start:end]
    for state in (
        "signed_off",
        "needs_changes",
        "blocked",
        "stopped_no_progress",
        "stopped_environmental_blocker",
        "blocked_no_findings",
        "paused_on_gate",
        "paused_on_environmental",
    ):
        assert state in sv_svg, f"supervisor SVG missing state {state!r}"


# ── (e) CLI: regen produces both files by default, --json-only skips HTML ──


def _build_minimal_repo(root: Path) -> None:
    """Tiny DontPanic-shaped tree so the F001 crawler has something to
    snapshot. We keep this independent of the F001 test file's builder so
    these CLI tests don't cross-couple with that module's import path."""
    modules = root / "scripts" / "dontpanic_orchestrate"
    modules.mkdir(parents=True)
    (modules / "__init__.py").write_text(
        '"""Synthetic package for F002 CLI tests."""\n', encoding="utf-8"
    )
    (modules / "supervisor.py").write_text(
        '"""Supervisor entry."""\nimport json\n', encoding="utf-8"
    )
    schemas = root / "claude" / "shared" / "schemas" / "v1.0"
    schemas.mkdir(parents=True)
    (root / "claude" / "shared" / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (schemas / "plan.schema.json").write_text(
        json.dumps({"$id": "plan", "type": "object"}, sort_keys=True),
        encoding="utf-8",
    )
    (schemas / "validate.py").write_text("# stub\n", encoding="utf-8")
    plan_dir = root / "docs" / "plans" / "2026-05-19-100-feat-alpha"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\nid: 2026-05-19-100-feat-alpha\ntitle: Alpha\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (plan_dir / "features.json").write_text(
        json.dumps({"task_id": "2026-05-19-100-feat-alpha", "features": [{"id": "F001"}]}),
        encoding="utf-8",
    )


@pytest.fixture()
def synthetic_repo(tmp_path: Path) -> Path:
    _build_minimal_repo(tmp_path)
    return tmp_path


def test_e_regen_default_writes_both_json_and_html(
    synthetic_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = arch.cli_main(["regen", "--repo-root", str(synthetic_repo)])
    assert rc == 0
    json_out = synthetic_repo / arch.DEFAULT_OUTPUT_REL
    html_out = json_out.with_suffix(".html")
    assert json_out.is_file()
    assert html_out.is_file()
    body = html_out.read_text(encoding="utf-8")
    assert "<title>DontPanic Architecture</title>" in body
    # The CLI announces both file writes.
    stdout = capsys.readouterr().out
    assert str(json_out) in stdout
    assert str(html_out) in stdout


def test_e2_regen_json_only_skips_html(
    synthetic_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = arch.cli_main(
        ["regen", "--repo-root", str(synthetic_repo), "--json-only"]
    )
    assert rc == 0
    json_out = synthetic_repo / arch.DEFAULT_OUTPUT_REL
    html_out = json_out.with_suffix(".html")
    assert json_out.is_file()
    assert not html_out.exists(), "--json-only must NOT produce the HTML companion"
    stdout = capsys.readouterr().out
    assert str(json_out) in stdout
    assert str(html_out) not in stdout


def test_e3_regen_with_html_overlapping_flag_is_default(
    synthetic_repo: Path,
) -> None:
    """Explicit --with-html matches default behavior."""
    rc = arch.cli_main(
        ["regen", "--repo-root", str(synthetic_repo), "--with-html"]
    )
    assert rc == 0
    html_out = synthetic_repo / arch.DEFAULT_OUTPUT_REL.with_suffix(".html")
    assert html_out.is_file()


def test_e4_regen_html_output_override(synthetic_repo: Path) -> None:
    custom_html = synthetic_repo / "docs" / "architecture" / "custom.html"
    rc = arch.cli_main(
        [
            "regen",
            "--repo-root",
            str(synthetic_repo),
            "--html-output",
            str(custom_html),
        ]
    )
    assert rc == 0
    assert custom_html.is_file()
    # Default HTML path should NOT exist when an override is supplied.
    default_html = synthetic_repo / arch.DEFAULT_OUTPUT_REL.with_suffix(".html")
    assert not default_html.exists()
