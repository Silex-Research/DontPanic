"""JavaScript/TS import extractor (plan 2026-06-08-002, Plan C slice 1).

The dashboard ships ES modules with no import extractor, so DontPanic's own
as-built map was Python-only and the Plan A coverage ceiling stayed pinned low
by ``missing_extractor: javascript``. This module extracts the dashboard's
relative-import module graph as as-built nodes + edges so that kind becomes
covered.

Bounded (Plan C slice 1):
  * relative ES imports only (``./x.js`` / ``../y.js``; optional extension /
    ``index.js``). Bare specifiers (vendor) and unresolved relatives surface as
    low-confidence unresolved endpoints — never dropped, mirroring the Python
    crawler's render-truth treatment.
  * no TS type analysis, no bundler/tsconfig alias resolution, no other language.

Pure + deterministic: no network, no mutation of external state.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Where the dashboard's authored JS lives; vendored / generated / test trees skip.
_SCAN_ROOT = "dashboard"
_SKIP_PARTS = frozenset({"node_modules", "vendor", "tests", "playwright", "dist", "coverage"})
_JS_EXTS = (".js", ".mjs", ".cjs")

_IMPORT_FROM_RE = re.compile(r"""\bimport\b[^;'"]*?\bfrom\s*['"]([^'"]+)['"]""")
_IMPORT_BARE_RE = re.compile(r"""\bimport\s*['"]([^'"]+)['"]""")
_EXPORT_RE = re.compile(
    r"^\s*export\s+(?:async\s+)?(?:function|const|class|let|var)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)

LANE_ID = "lane:client-surfaces"


def js_module_id(rel_path: str) -> str:
    return f"js_module:{rel_path}"


def external_id(name: str) -> str:
    return f"external:{name}"


def _iter_js_files(repo_root: Path) -> list[Path]:
    root = repo_root / _SCAN_ROOT
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.suffix not in _JS_EXTS or not p.is_file():
            continue
        if any(part in _SKIP_PARTS for part in p.relative_to(repo_root).parts):
            continue
        out.append(p)
    return sorted(out)


def _resolve_relative(spec: str, from_file: Path, repo_root: Path, known: set[Path]) -> Path | None:
    """Resolve a relative import specifier to a known JS file, or None."""
    base = (from_file.parent / spec).resolve()
    candidates = [base]
    if base.suffix not in _JS_EXTS:
        candidates += [base.with_suffix(ext) for ext in _JS_EXTS]
        candidates += [base / f"index{ext}" for ext in _JS_EXTS]
    for c in candidates:
        if c in known:
            return c
    return None


def extract_js_modules(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(nodes, edges)`` for the dashboard ES module graph. Never raises."""
    files = _iter_js_files(repo_root)
    known = {f.resolve() for f in files}
    rel_of = {f.resolve(): str(f.relative_to(repo_root)) for f in files}

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    externals: dict[str, dict[str, Any]] = {}

    for f in files:
        rel = str(f.relative_to(repo_root))
        from_id = js_module_id(rel)
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            text = ""
        exports = sorted(set(_EXPORT_RE.findall(text)))
        nodes.append(
            {
                "id": from_id,
                "type": "js_module",
                "lane_id": LANE_ID,
                "title": f.name,
                "summary": "",
                "source_path": rel,
                "public_symbols": exports,
            }
        )
        specs = set(_IMPORT_FROM_RE.findall(text)) | set(_IMPORT_BARE_RE.findall(text))
        for spec in sorted(specs):
            if spec.startswith("."):
                target = _resolve_relative(spec, f, repo_root, known)
                if target is not None:
                    to_id = js_module_id(rel_of[target])
                    if to_id != from_id:
                        edges.append(
                            {
                                "id": f"edge:import:{from_id}->{to_id}",
                                "type": "import",
                                "from": from_id,
                                "to": to_id,
                            }
                        )
                    continue
                kind = "unknown"  # a relative import that did not resolve = missing evidence
            else:
                kind = "external"  # bare specifier = vendor/third-party
            ext_id = external_id(spec)
            node = externals.get(ext_id)
            if node is None:
                node = {
                    "id": ext_id,
                    "type": "external",
                    "lane_id": "lane:external-services",
                    "title": spec,
                    "summary": (
                        "unresolved JS import — relative path with no local module"
                        if kind == "unknown"
                        else "JS import — vendor/third-party module"
                    ),
                    "source_kind": kind,
                    "evidence_basis": "unresolved",
                    "unresolved": True,
                    "referenced_by": [],
                }
                externals[ext_id] = node
            node["referenced_by"].append(from_id)
            edges.append(
                {
                    "id": f"edge:import:{from_id}->{ext_id}",
                    "type": "import",
                    "from": from_id,
                    "to": ext_id,
                    "unresolved": True,
                }
            )

    for ext_id in sorted(externals):
        n = externals[ext_id]
        n["referenced_by"] = sorted(set(n["referenced_by"]))
        nodes.append(n)
    return nodes, edges
