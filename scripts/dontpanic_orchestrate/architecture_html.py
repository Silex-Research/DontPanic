"""dontpanic architecture HTML renderer.

Plan 2026-05-19-004 F002. Pure transform from
``docs/architecture/architecture.json`` (produced by F001's crawler) to a
single-page, mobile-responsive ``architecture.html``. No second pass over
source — if the JSON is missing or invalid, this module raises
:class:`ArchitectureRenderError` with an actionable pointer to
``dontpanic architecture regen``.

Design constraints:
- No JS framework, no external CSS, no fonts. One self-contained HTML
  document so it survives ``file://`` opens on any device.
- Three SVG diagrams (module dependency graph, plan lifecycle, supervisor
  state machine) are inline + deterministic — same snapshot → same SVG.
- Mobile-first: single column under 800px, two-column on wider viewports.
- Output is gitignored (see ``.gitignore``); operators regen locally.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any, Iterable

DEFAULT_HTML_REL = Path("docs/architecture/architecture.html")

# These fields must be present on a valid snapshot — they back the four
# top-nav sections + the SVG diagrams. Kept narrower than the schema's
# `required` (which includes schema_version) so a missing version still
# renders, but anything missing here means we can't draw a section.
_REQUIRED_TOP_KEYS = ("modules", "schemas", "plans", "source_fingerprint")

# The 8 terminal/transition states the supervisor reports. Stable + ordered
# so the SVG layout is deterministic. Pulled from circuit_breakers and the
# F003 v3 taxonomy doc; if a new state lands it goes here.
_SUPERVISOR_STATES = (
    "signed_off",
    "needs_changes",
    "blocked",
    "stopped_no_progress",
    "stopped_environmental_blocker",
    "blocked_no_findings",
    "paused_on_gate",
    "paused_on_environmental",
)

# Plan lifecycle order (left → right in the SVG).
_PLAN_LIFECYCLE_STATES = ("draft", "active", "completed", "abandoned", "blocked")


class ArchitectureRenderError(RuntimeError):
    """Raised when the input JSON is missing, malformed, or fails the
    minimal-shape check. Message always includes the regen command so the
    operator can fix-forward without grepping docs."""


# ── File-level entry ───────────────────────────────────────────────────


def render(
    json_path: Path | str,
    html_path: Path | str | None = None,
) -> Path:
    """Read ``json_path``, render HTML, write to ``html_path``.

    When ``html_path`` is omitted, defaults to the same directory as the
    JSON with an ``.html`` extension. Returns the path written.
    """
    json_path = Path(json_path)
    snapshot = _load_snapshot(json_path)
    out = Path(html_path) if html_path is not None else json_path.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(snapshot), encoding="utf-8")
    return out


def _load_snapshot(json_path: Path) -> dict[str, Any]:
    if not json_path.is_file():
        raise ArchitectureRenderError(
            f"architecture.json not found at {json_path}. "
            f"Run `dontpanic architecture regen` to generate it."
        )
    try:
        raw = json_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArchitectureRenderError(
            f"unable to read {json_path}: {exc}. "
            f"Run `dontpanic architecture regen` to regenerate."
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ArchitectureRenderError(
            f"{json_path} is not valid JSON ({exc.msg} at line {exc.lineno}). "
            f"Run `dontpanic architecture regen` to regenerate."
        ) from exc
    _validate_snapshot_shape(data, source=json_path)
    return data


def _validate_snapshot_shape(data: Any, *, source: Path | str) -> None:
    if not isinstance(data, dict):
        raise ArchitectureRenderError(
            f"{source} top-level value is {type(data).__name__}, expected object. "
            f"Run `dontpanic architecture regen` to regenerate."
        )
    missing = [k for k in _REQUIRED_TOP_KEYS if k not in data]
    if missing:
        raise ArchitectureRenderError(
            f"{source} missing required fields: {missing}. "
            f"Run `dontpanic architecture regen` to regenerate."
        )
    for key in ("modules", "schemas", "plans"):
        if not isinstance(data[key], list):
            raise ArchitectureRenderError(
                f"{source} field {key!r} is {type(data[key]).__name__}, expected list. "
                f"Run `dontpanic architecture regen` to regenerate."
            )
        for idx, entry in enumerate(data[key]):
            if not isinstance(entry, dict):
                raise ArchitectureRenderError(
                    f"{source} field {key!r}[{idx}] is "
                    f"{type(entry).__name__}, expected object. "
                    f"Run `dontpanic architecture regen` to regenerate."
                )
    if not isinstance(data["source_fingerprint"], dict):
        raise ArchitectureRenderError(
            f"{source} field 'source_fingerprint' is "
            f"{type(data['source_fingerprint']).__name__}, expected object. "
            f"Run `dontpanic architecture regen` to regenerate."
        )
    # Plan 4 F002 i1 auditor finding (high/security): the renderer used to
    # fall through to raw interpolation when files_count wasn't an int,
    # which let `"<script>x</script>"` reach the page unescaped. Mirror the
    # architecture-snapshot.schema.json contract here for the two fields
    # the header consumes, and the renderer's defensive escape (below)
    # handles anything that slips past in the future.
    fp = data["source_fingerprint"]
    files_count = fp.get("files_count")
    if files_count is not None and not (isinstance(files_count, int) and not isinstance(files_count, bool)):
        raise ArchitectureRenderError(
            f"{source} field 'source_fingerprint.files_count' is "
            f"{type(files_count).__name__}, expected integer. "
            f"Run `dontpanic architecture regen` to regenerate."
        )
    if isinstance(files_count, int) and files_count < 0:
        raise ArchitectureRenderError(
            f"{source} field 'source_fingerprint.files_count' is "
            f"{files_count}, expected integer >= 0. "
            f"Run `dontpanic architecture regen` to regenerate."
        )
    root_val = fp.get("file_hashes_root")
    if root_val is not None and not isinstance(root_val, str):
        raise ArchitectureRenderError(
            f"{source} field 'source_fingerprint.file_hashes_root' is "
            f"{type(root_val).__name__}, expected string. "
            f"Run `dontpanic architecture regen` to regenerate."
        )


# ── Public transform ───────────────────────────────────────────────────


def render_html(snapshot: dict[str, Any]) -> str:
    """Pure transform — snapshot dict → single-page HTML string.

    Callers that already have a snapshot in memory should call this
    directly (no disk I/O). For a JSON-on-disk pipeline use :func:`render`.
    """
    _validate_snapshot_shape(snapshot, source="<snapshot>")
    modules = list(snapshot.get("modules", []))
    schemas = list(snapshot.get("schemas", []))
    plans = list(snapshot.get("plans", []))
    fp = snapshot.get("source_fingerprint", {}) or {}
    generated_at = snapshot.get("generated_at", "(unknown)")
    schema_version = snapshot.get("schema_version", "(unknown)")
    truncated = bool(snapshot.get("truncated", False))
    truncation_marker = snapshot.get("truncation_marker", "")

    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append(
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
    )
    parts.append("<title>DontPanic Architecture</title>")
    parts.append(_STYLE_BLOCK)
    parts.append("</head>")
    parts.append("<body>")
    parts.append(_render_header(generated_at, schema_version, fp, truncated, truncation_marker))
    parts.append(_render_nav())
    parts.append('<main class="container">')
    parts.append(_render_modules_section(modules))
    parts.append(_render_schemas_section(schemas))
    parts.append(_render_plans_section(plans))
    parts.append(_render_lifecycle_section())
    parts.append("</main>")
    parts.append(_render_footer(fp))
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


# ── HTML pieces ────────────────────────────────────────────────────────


_STYLE_BLOCK = """<style>
:root {
  --bg: #0f172a;
  --bg-panel: #1e293b;
  --fg: #e2e8f0;
  --fg-muted: #94a3b8;
  --accent: #38bdf8;
  --accent-2: #f472b6;
  --good: #22c55e;
  --warn: #facc15;
  --bad: #ef4444;
  --border: #334155;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  line-height: 1.5; }
header.top { padding: 1.25rem 1rem; border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); }
header.top h1 { margin: 0 0 0.25rem; font-size: 1.5rem; letter-spacing: -0.01em; }
header.top .meta { color: var(--fg-muted); font-size: 0.875rem; }
header.top .meta code { background: rgba(56,189,248,0.1); padding: 0.1rem 0.4rem;
  border-radius: 3px; color: var(--accent); font-size: 0.8rem; }
header.top .warning { color: var(--warn); margin-top: 0.5rem; font-size: 0.875rem; }
nav.top { position: sticky; top: 0; background: var(--bg-panel); border-bottom: 1px solid var(--border);
  padding: 0.5rem 1rem; z-index: 10; display: flex; flex-wrap: wrap; gap: 0.5rem; }
nav.top a { color: var(--fg); text-decoration: none; padding: 0.4rem 0.75rem;
  border-radius: 4px; font-size: 0.9rem; }
nav.top a:hover { background: rgba(56,189,248,0.15); color: var(--accent); }
main.container { padding: 1rem; max-width: 1400px; margin: 0 auto; }
section { margin-bottom: 2.5rem; }
section h2 { font-size: 1.25rem; border-bottom: 1px solid var(--border);
  padding-bottom: 0.5rem; margin: 0 0 1rem; color: var(--accent); }
section .lede { color: var(--fg-muted); font-size: 0.9rem; margin: -0.5rem 0 1rem; }
.diagram { background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: 8px; padding: 1rem; overflow-x: auto; margin-bottom: 1rem; }
.diagram svg { width: 100%; height: auto; display: block; }
.cards { display: grid; grid-template-columns: 1fr; gap: 0.75rem; }
.card { background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.75rem 1rem; }
.card h3 { margin: 0 0 0.25rem; font-size: 1rem; font-family:
  ui-monospace, "SF Mono", Menlo, monospace; color: var(--accent); }
.card .path { color: var(--fg-muted); font-size: 0.8rem; font-family:
  ui-monospace, "SF Mono", Menlo, monospace; word-break: break-all; }
.card .summary { margin: 0.5rem 0 0; color: var(--fg); font-size: 0.9rem; }
.card .meta { font-size: 0.8rem; color: var(--fg-muted); margin-top: 0.5rem; }
.tag { display: inline-block; background: rgba(56,189,248,0.1); color: var(--accent);
  padding: 0.1rem 0.5rem; border-radius: 3px; margin: 0.15rem 0.25rem 0 0;
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.75rem; }
.tag.import { background: rgba(244,114,182,0.1); color: var(--accent-2); }
.tag.status-active { background: rgba(34,197,94,0.15); color: var(--good); }
.tag.status-completed { background: rgba(56,189,248,0.15); color: var(--accent); }
.tag.status-draft { background: rgba(148,163,184,0.15); color: var(--fg-muted); }
.tag.status-blocked, .tag.status-abandoned { background: rgba(239,68,68,0.15); color: var(--bad); }
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
table th, table td { text-align: left; padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border); }
table th { color: var(--fg-muted); font-weight: 600; }
footer.bottom { padding: 1rem; color: var(--fg-muted); font-size: 0.8rem;
  text-align: center; border-top: 1px solid var(--border); }
@media (min-width: 800px) {
  .cards { grid-template-columns: 1fr 1fr; }
  header.top { padding: 2rem; }
  header.top h1 { font-size: 2rem; }
  main.container { padding: 2rem; }
}
@media (min-width: 1200px) {
  .cards.modules-cards { grid-template-columns: 1fr 1fr 1fr; }
}
</style>"""


def _render_header(
    generated_at: str,
    schema_version: str,
    fp: dict[str, Any],
    truncated: bool,
    truncation_marker: str,
) -> str:
    root = fp.get("file_hashes_root", "")
    short = root[:12] if isinstance(root, str) else ""
    files_count = fp.get("files_count", 0)
    # Validator now rejects non-int files_count, so this branch should
    # always render the int form. Defense in depth: html.escape the
    # fallback so a future bypass of the validator still can't inject HTML.
    files_count_str = (
        str(int(files_count))
        if isinstance(files_count, int) and not isinstance(files_count, bool)
        else html.escape(str(files_count))
    )
    lines = [
        '<header class="top">',
        "<h1>DontPanic Architecture</h1>",
        '<div class="meta">',
        f"schema v{html.escape(str(schema_version))} · "
        f"generated {html.escape(str(generated_at))} · "
        f"fingerprint <code>{html.escape(short)}</code> · "
        f"{files_count_str} files tracked",
        "</div>",
    ]
    if truncated:
        lines.append(
            f'<div class="warning">⚠ snapshot truncated: '
            f"{html.escape(str(truncation_marker))}</div>"
        )
    lines.append("</header>")
    return "\n".join(lines)


def _render_nav() -> str:
    return (
        '<nav class="top">'
        '<a href="#modules">Modules</a>'
        '<a href="#schemas">Schemas</a>'
        '<a href="#plans">Plans</a>'
        '<a href="#lifecycle">Lifecycle</a>'
        "</nav>"
    )


def _render_modules_section(modules: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for m in modules:
        name = html.escape(str(m.get("name", "")))
        path = html.escape(str(m.get("path", "")))
        summary = html.escape(str(m.get("summary", "")) or "(no docstring)")
        syms = m.get("public_symbols", []) or []
        imps = m.get("imports", []) or []
        sym_tags = "".join(
            f'<span class="tag">{html.escape(str(s))}</span>'
            for s in syms[:12]
        )
        if len(syms) > 12:
            sym_tags += f'<span class="tag">+{len(syms) - 12}</span>'
        imp_tags = "".join(
            f'<span class="tag import">{html.escape(str(i))}</span>'
            for i in imps[:8]
        )
        if len(imps) > 8:
            imp_tags += f'<span class="tag import">+{len(imps) - 8}</span>'
        cards.append(
            "<article class=\"card\">"
            f"<h3>{name}</h3>"
            f'<div class="path">{path}</div>'
            f'<p class="summary">{summary}</p>'
            f'<div class="meta">Public symbols: {sym_tags or "<em>none</em>"}</div>'
            f'<div class="meta">Imports: {imp_tags or "<em>none</em>"}</div>'
            "</article>"
        )
    body = "".join(cards) or "<p>No modules.</p>"
    return (
        '<section id="modules">'
        f"<h2>Modules ({len(modules)})</h2>"
        '<p class="lede">Python modules discovered under '
        "<code>scripts/dontpanic_orchestrate/</code>. Edges in the graph are "
        "intra-package imports.</p>"
        f'<div class="diagram">{_render_module_graph_svg(modules)}</div>'
        f'<div class="cards modules-cards">{body}</div>'
        "</section>"
    )


def _render_schemas_section(schemas: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for s in schemas:
        name = html.escape(str(s.get("name", "")))
        path = html.escape(str(s.get("path", "")))
        version = html.escape(str(s.get("version") or "—"))
        validator = "✓" if s.get("validator_present") else "—"
        rows.append(
            f"<tr><td><code>{name}</code></td>"
            f"<td><code>{path}</code></td>"
            f"<td>{version}</td><td>{validator}</td></tr>"
        )
    body = "".join(rows) or '<tr><td colspan="4">No schemas.</td></tr>'
    return (
        '<section id="schemas">'
        f"<h2>Schemas ({len(schemas)})</h2>"
        '<p class="lede">JSON schemas mirrored from '
        "<code>claude/shared/schemas/</code>. <em>validator_present</em> "
        "indicates a matching Pydantic mirror under "
        "<code>validate.py</code>.</p>"
        "<table><thead><tr><th>Name</th><th>Path</th>"
        "<th>Version</th><th>Validator</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
        "</section>"
    )


def _render_plans_section(plans: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for p in plans:
        pid = html.escape(str(p.get("id", "")))
        title = html.escape(str(p.get("title", "")))
        status = str(p.get("status", "unknown"))
        status_cls = "status-" + "".join(
            c if c.isalnum() else "-" for c in status.lower()
        )
        feats = p.get("features_count", 0)
        rows.append(
            f"<tr><td><code>{pid}</code></td>"
            f"<td>{title}</td>"
            f'<td><span class="tag {status_cls}">{html.escape(status)}</span></td>'
            f"<td>{int(feats) if isinstance(feats, int) else 0}</td></tr>"
        )
    body = "".join(rows) or '<tr><td colspan="4">No plans.</td></tr>'
    return (
        '<section id="plans">'
        f"<h2>Plans ({len(plans)})</h2>"
        '<p class="lede">Plan inventory derived from '
        "<code>docs/plans/*/plan.md</code> frontmatter + features.json. "
        "Counts show the plan lifecycle distribution.</p>"
        f'<div class="diagram">{_render_plan_lifecycle_svg(plans)}</div>'
        "<table><thead><tr><th>ID</th><th>Title</th>"
        "<th>Status</th><th>Features</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
        "</section>"
    )


def _render_lifecycle_section() -> str:
    return (
        '<section id="lifecycle">'
        "<h2>Supervisor state machine</h2>"
        '<p class="lede">Terminal + transition states reported by '
        "<code>dispatch_volley</code>. Sourced from the F003 v3 taxonomy "
        "and circuit_breakers module; gated states (paused_*) require "
        "operator clearance via <code>dontpanic approve</code>.</p>"
        f'<div class="diagram">{_render_supervisor_state_svg()}</div>'
        "</section>"
    )


def _render_footer(fp: dict[str, Any]) -> str:
    root = fp.get("file_hashes_root", "")
    short = root[:12] if isinstance(root, str) else ""
    return (
        '<footer class="bottom">'
        f"Generated by <code>dontpanic architecture regen</code>. "
        f"Fingerprint <code>{html.escape(short)}</code>. "
        "This file is gitignored — regen locally on demand."
        "</footer>"
    )


# ── SVG diagrams ───────────────────────────────────────────────────────


def _render_module_graph_svg(modules: list[dict[str, Any]]) -> str:
    """Circular layout: each module on a circle, edges = intra-package imports.

    Deterministic positions (sort by name then angle = 2π·i/n), so two
    runs over the same snapshot produce byte-identical SVG.
    """
    if not modules:
        return _empty_svg("module-graph", "No modules to graph.")
    # Stable ordering. We use `name` since that's what edges reference.
    ordered = sorted(modules, key=lambda m: str(m.get("name", "")))
    names = [str(m.get("name", "")) for m in ordered]
    name_to_index = {n: i for i, n in enumerate(names) if n}

    width = 800
    height = 600
    cx, cy = width / 2, height / 2
    radius = min(width, height) / 2 - 70
    n = len(ordered)

    # Position each node.
    positions: list[tuple[float, float]] = []
    for i in range(n):
        # Start at top, rotate clockwise. -π/2 offset so module 0 is at 12 o'clock.
        theta = -math.pi / 2 + 2 * math.pi * i / n
        positions.append((cx + radius * math.cos(theta), cy + radius * math.sin(theta)))

    # Collect edges (intra-package only).
    edges: list[tuple[int, int]] = []
    for i, m in enumerate(ordered):
        imports = m.get("imports", []) or []
        for imp in imports:
            j = name_to_index.get(str(imp))
            if j is not None and j != i:
                edges.append((i, j))
    # Dedupe edges (treat as undirected for visual purposes).
    edge_set: set[tuple[int, int]] = set()
    for i, j in edges:
        edge_set.add((min(i, j), max(i, j)))

    parts: list[str] = []
    parts.append(
        f'<svg id="module-graph" role="img" aria-label="Module dependency graph" '
        f'viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
    )
    parts.append('<title>Module dependency graph</title>')
    # Background rect for visual contrast (transparent inside SVG = panel bg).
    # Edges first so nodes render on top.
    for i, j in sorted(edge_set):
        x1, y1 = positions[i]
        x2, y2 = positions[j]
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#475569" stroke-width="0.6" opacity="0.55" />'
        )
    # Nodes + labels.
    for i, (x, y) in enumerate(positions):
        short = _short_module_name(names[i])
        # Larger nodes for modules with more imports (visual prominence).
        deg = sum(1 for a, b in edge_set if a == i or b == i)
        r = 4 + min(deg, 10) * 0.6
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="#38bdf8" '
            f'stroke="#0f172a" stroke-width="1.5" />'
        )
        # Label radially outward from center.
        theta = math.atan2(y - cy, x - cx)
        lx = cx + (radius + 18) * math.cos(theta)
        ly = cy + (radius + 18) * math.sin(theta)
        anchor = "start" if math.cos(theta) >= 0 else "end"
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" fill="#e2e8f0" font-size="10" '
            f'text-anchor="{anchor}" dominant-baseline="middle" '
            f'font-family="ui-monospace,monospace">{html.escape(short)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _short_module_name(name: str) -> str:
    """Trim `dontpanic_orchestrate.` prefix for SVG labels — keeps the
    diagram legible on mobile."""
    prefix = "dontpanic_orchestrate."
    if name.startswith(prefix):
        return name[len(prefix):] or name
    return name


def _render_plan_lifecycle_svg(plans: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {s: 0 for s in _PLAN_LIFECYCLE_STATES}
    other = 0
    for p in plans:
        st = str(p.get("status", "")).lower()
        if st in counts:
            counts[st] += 1
        else:
            other += 1

    width = 800
    height = 220
    # Lay states out in a row, evenly spaced.
    n = len(_PLAN_LIFECYCLE_STATES)
    margin = 80
    step = (width - 2 * margin) / max(n - 1, 1)
    y = height / 2

    parts: list[str] = []
    parts.append(
        f'<svg id="plan-lifecycle" role="img" aria-label="Plan lifecycle" '
        f'viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
    )
    parts.append('<title>Plan lifecycle</title>')
    # Define the transitions.
    transitions = [
        ("draft", "active"),
        ("active", "completed"),
        ("active", "abandoned"),
        ("active", "blocked"),
    ]
    positions: dict[str, tuple[float, float]] = {
        s: (margin + i * step, y) for i, s in enumerate(_PLAN_LIFECYCLE_STATES)
    }
    parts.append(
        '<defs><marker id="arrow-plan" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8"/></marker></defs>'
    )
    # Edges with arrowheads.
    for src, dst in transitions:
        x1, y1 = positions[src]
        x2, y2 = positions[dst]
        # Trim endpoints so the arrowhead doesn't overlap the node.
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        offset = 32
        sx, sy = x1 + ux * offset, y1 + uy * offset
        ex, ey = x2 - ux * offset, y2 - uy * offset
        parts.append(
            f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            'stroke="#94a3b8" stroke-width="1.5" marker-end="url(#arrow-plan)"/>'
        )
    # Nodes.
    for s in _PLAN_LIFECYCLE_STATES:
        nx, ny = positions[s]
        count = counts[s]
        fill = _status_fill(s)
        parts.append(
            f'<circle cx="{nx:.1f}" cy="{ny:.1f}" r="28" fill="{fill}" '
            'stroke="#0f172a" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{nx:.1f}" y="{ny - 2:.1f}" text-anchor="middle" '
            'fill="#0f172a" font-size="11" font-weight="700" '
            f'font-family="ui-monospace,monospace">{html.escape(s)}</text>'
        )
        parts.append(
            f'<text x="{nx:.1f}" y="{ny + 12:.1f}" text-anchor="middle" '
            f'fill="#0f172a" font-size="13" font-weight="700">{count}</text>'
        )
    if other:
        parts.append(
            f'<text x="{width / 2:.1f}" y="{height - 10:.1f}" text-anchor="middle" '
            f'fill="#94a3b8" font-size="11">+ {other} plan(s) with non-canonical status</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _status_fill(status: str) -> str:
    return {
        "draft": "#cbd5e1",
        "active": "#86efac",
        "completed": "#7dd3fc",
        "abandoned": "#fca5a5",
        "blocked": "#fca5a5",
    }.get(status, "#cbd5e1")


def _render_supervisor_state_svg() -> str:
    width = 800
    height = 380
    cols = 4
    rows = (len(_SUPERVISOR_STATES) + cols - 1) // cols
    cell_w = width / cols
    cell_h = height / rows
    positions: dict[str, tuple[float, float]] = {}
    for i, state in enumerate(_SUPERVISOR_STATES):
        col = i % cols
        row = i // cols
        positions[state] = (cell_w * (col + 0.5), cell_h * (row + 0.5))

    parts: list[str] = []
    parts.append(
        f'<svg id="supervisor-state" role="img" '
        f'aria-label="Supervisor state machine" '
        f'viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
    )
    parts.append('<title>Supervisor state machine</title>')
    # Transitions (illustrative — keyed on real supervisor branches).
    transitions = [
        ("needs_changes", "signed_off"),
        ("needs_changes", "stopped_no_progress"),
        ("needs_changes", "blocked"),
        ("blocked", "paused_on_gate"),
        ("blocked", "stopped_environmental_blocker"),
        ("blocked_no_findings", "paused_on_environmental"),
        ("paused_on_gate", "signed_off"),
        ("paused_on_environmental", "signed_off"),
    ]
    parts.append(
        '<defs><marker id="arrow-sv" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b"/></marker></defs>'
    )
    for src, dst in transitions:
        if src not in positions or dst not in positions:
            continue
        x1, y1 = positions[src]
        x2, y2 = positions[dst]
        # Curve the edge slightly so parallel edges are distinguishable.
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 18
        parts.append(
            f'<path d="M {x1:.1f} {y1:.1f} Q {mx:.1f} {my:.1f} {x2:.1f} {y2:.1f}" '
            'fill="none" stroke="#64748b" stroke-width="1.2" opacity="0.7" '
            'marker-end="url(#arrow-sv)"/>'
        )
    for state, (x, y) in positions.items():
        fill = _supervisor_state_fill(state)
        parts.append(
            f'<rect x="{x - 75:.1f}" y="{y - 22:.1f}" width="150" height="44" '
            f'rx="8" fill="{fill}" stroke="#0f172a" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle" '
            'fill="#0f172a" font-size="11" font-weight="700" '
            f'font-family="ui-monospace,monospace">{html.escape(state)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _supervisor_state_fill(state: str) -> str:
    if state == "signed_off":
        return "#86efac"
    if state.startswith("paused"):
        return "#fde68a"
    if state.startswith("stopped"):
        return "#fca5a5"
    if state == "blocked" or state == "blocked_no_findings":
        return "#fdba74"
    return "#cbd5e1"


def _empty_svg(svg_id: str, message: str) -> str:
    return (
        f'<svg id="{svg_id}" role="img" aria-label="{html.escape(message)}" '
        'viewBox="0 0 400 80" xmlns="http://www.w3.org/2000/svg">'
        f'<title>{html.escape(message)}</title>'
        f'<text x="200" y="44" fill="#94a3b8" font-size="14" '
        f'text-anchor="middle">{html.escape(message)}</text></svg>'
    )


# ── Iteration helper (only used by tests; kept tiny to avoid leakage) ──


def iter_required_top_keys() -> Iterable[str]:
    """Test/diagnostic helper — surfaces the keys that must be present
    on a snapshot for HTML rendering to succeed."""
    return _REQUIRED_TOP_KEYS
