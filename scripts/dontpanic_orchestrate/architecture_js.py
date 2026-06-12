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

import os
import re
from pathlib import Path
from typing import Any

# Where the dashboard's authored JS lives; vendored / generated / test trees skip.
_SCAN_ROOT = "dashboard"
_SKIP_PARTS = frozenset({"node_modules", "vendor", "tests", "playwright", "dist", "coverage"})
_JS_EXTS = (".js", ".mjs", ".cjs")
_SCAN_ENTRY_CAP = 20000  # bounded traversal (audit 2026-06-08 B1#6)

# Specifier-bearing module forms (run over COMMENT/STRING-STRIPPED source only —
# audit 2026-06-08 B1#3/B1#4).
_IMPORT_FROM_RE = re.compile(r"""\bimport\b[^;'"]*?\bfrom\s*['"]([^'"]+)['"]""")
_IMPORT_BARE_RE = re.compile(r"""\bimport\s*['"]([^'"]+)['"]""")
_EXPORT_FROM_RE = re.compile(r"""\bexport\b[^;'"]*?\bfrom\s*['"]([^'"]+)['"]""")
_DYNAMIC_IMPORT_RE = re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)""")
# A dynamic import whose argument is NOT a plain string literal (e.g. a template
# with interpolation) — surfaced as visible unresolved evidence, never dropped.
_DYNAMIC_NONLITERAL_RE = re.compile(r"""\bimport\s*\(\s*(?!['"])""")
# A dynamic import() living INSIDE a template-literal ${...} interpolation: the
# mask blanks template bodies, so detect it on RAW source and surface it as an
# unresolved sentinel rather than drop it (audit 2026-06-08 re-audit B1#3/B1#4).
_TEMPLATE_IMPORT_RE = re.compile(r"`[^`]*\bimport\s*\([^`]*`", re.DOTALL)
_EXPORT_RE = re.compile(
    r"^\s*export\s+(?:async\s+)?(?:function|const|class|let|var)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
_PH_RE = re.compile(r"\x00(\d+)\x00")  # placeholder for a masked string literal

LANE_ID = "lane:client-surfaces"


def _mask(text: str) -> tuple[str, list[str]]:
    """Single-pass scanner (audit 2026-06-08 B1#3): strip line/block comments and
    replace each string/template-literal BODY with a numbered placeholder, while
    preserving the surrounding quotes. Import-looking text inside a comment or
    string therefore cannot match the specifier regexes (the keywords vanish),
    yet real specifiers — which ARE the quoted strings — survive as placeholders
    that map back to their literal value. Returns (masked_text, literals)."""
    out: list[str] = []
    literals: list[str] = []
    i, n = 0, len(text)
    while i < n:
        two = text[i : i + 2]
        if two == "//":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if two == "/*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        c = text[i]
        if c in "'\"`":
            j = i + 1
            buf: list[str] = []
            while j < n:
                if text[j] == "\\":
                    buf.append(text[j : j + 2])
                    j += 2
                    continue
                if text[j] == c:
                    break
                buf.append(text[j])
                j += 1
            literals.append("".join(buf))
            out.append(f"{c}\x00{len(literals) - 1}\x00{c}")
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out), literals


def _spec(placeholder: str, literals: list[str]) -> str | None:
    """Resolve a regex-captured specifier placeholder back to its literal value;
    returns None if the captured group was not a clean masked literal."""
    m = _PH_RE.fullmatch(placeholder)
    if not m:
        return None
    idx = int(m.group(1))
    return literals[idx] if 0 <= idx < len(literals) else None


def js_module_id(rel_path: str) -> str:
    return f"js_module:{rel_path}"


def ts_module_id(rel_path: str) -> str:
    return f"ts_module:{rel_path}"


def external_id(name: str) -> str:
    return f"external:{name}"


# Plan C2 — TypeScript/TSX/JSX extraction. First-party TS can live anywhere
# in a repo, so the TS scan is repo-rooted; the NON-PRODUCT trees below are
# excluded from BOTH this scan and the baseline language presence scan:
# documentation mockups (docs/design/* ships .jsx design canvases) and skill
# assets (claude/skills/*/ carries .tsx templates) are reference material,
# not product code, and must not pin a repo's coverage ceiling low.
_TS_EXTS = (".ts", ".tsx", ".jsx")
NON_PRODUCT_TREE_PREFIXES: tuple[str, ...] = ("docs/", "claude/skills/")
TS_EXTRACTOR = "ts_import_crawler"


def in_non_product_tree(rel_posix: str) -> bool:
    """True when a repo-root-relative POSIX path sits inside a documentation-
    mockup or skill-asset tree (single source of truth for C2 F002)."""
    probe = rel_posix if rel_posix.endswith("/") else rel_posix + "/"
    return any(probe.startswith(p) for p in NON_PRODUCT_TREE_PREFIXES)


def _iter_js_files(repo_root: Path) -> list[Path]:
    """Bounded traversal (audit 2026-06-08 B1#6): os.walk with skip-dirs PRUNED
    from descent (so node_modules is never walked) and a hard entry cap, instead
    of rglob('*') which enumerated every dependency file before filtering."""
    root = repo_root / _SCAN_ROOT
    if not root.is_dir():
        return []
    out: list[Path] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # Sort in place so traversal order — and thus any cap truncation — is
        # deterministic (audit 2026-06-08 re-audit LOW), not filesystem-dependent.
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_PARTS)
        for name in sorted(filenames):
            seen += 1
            if seen > _SCAN_ENTRY_CAP:
                return sorted(out)
            if name.endswith(_JS_EXTS):
                out.append(Path(dirpath) / name)
    return sorted(out)


def _resolve_relative(
    spec: str,
    from_file: Path,
    repo_root: Path,
    known: set[Path],
    exts: tuple[str, ...] = _JS_EXTS,
) -> Path | None:
    """Resolve a relative import specifier to a known module file, or None."""
    base = (from_file.parent / spec).resolve()
    candidates = [base]
    if base.suffix not in exts:
        candidates += [base.with_suffix(ext) for ext in exts]
        candidates += [base / f"index{ext}" for ext in exts]
    for c in candidates:
        if c in known:
            return c
    return None


def _iter_ts_files(repo_root: Path) -> list[Path]:
    """Plan C2 — repo-rooted bounded traversal for first-party .ts/.tsx/.jsx,
    pruning the C1 skip-dirs, dot-dirs, and the non-product trees."""
    root = Path(repo_root)
    if not root.is_dir():
        return []
    out: list[Path] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_prefix = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in _SKIP_PARTS
            and not d.startswith(".")
            and not in_non_product_tree(rel_prefix + d)
        )
        for name in sorted(filenames):
            seen += 1
            if seen > _SCAN_ENTRY_CAP:
                return sorted(out)
            if name.endswith(_TS_EXTS):
                out.append(Path(dirpath) / name)
    return sorted(out)


def extract_ts_modules(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Plan C2 F001 — first-party TypeScript/TSX/JSX module graph: ts_module
    nodes (source_path-bearing) + relative-import edges; import-type and
    export-from forms parse through the SAME masked-specifier pipeline as C1;
    an import that resolves to nothing surfaces as a low-confidence unresolved
    endpoint, never dropped. Never raises."""
    repo_root = Path(repo_root)
    files = _iter_ts_files(repo_root)
    return _extract_module_graph(
        files,
        repo_root,
        mod_id=ts_module_id,
        node_type="ts_module",
        extractor=TS_EXTRACTOR,
        resolve_exts=_TS_EXTS + _JS_EXTS,
    )


def extract_js_modules(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(nodes, edges)`` for the dashboard ES module graph. Never raises."""
    files = _iter_js_files(repo_root)
    return _extract_module_graph(
        files,
        Path(repo_root),
        mod_id=js_module_id,
        node_type="js_module",
        extractor="js_import_crawler",
        resolve_exts=_JS_EXTS,
    )


def _extract_module_graph(
    files: list[Path],
    repo_root: Path,
    *,
    mod_id,
    node_type: str,
    extractor: str,
    resolve_exts: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Shared C1/C2 module-graph extraction over a pre-scanned file set."""
    known = {f.resolve() for f in files}
    rel_of = {f.resolve(): str(f.relative_to(repo_root)) for f in files}

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    externals: dict[str, dict[str, Any]] = {}

    for f in files:
        rel = str(f.relative_to(repo_root))
        from_id = mod_id(rel)
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            text = ""
        masked, literals = _mask(text)
        exports = sorted(set(_EXPORT_RE.findall(masked)))
        nodes.append(
            {
                "id": from_id,
                "type": node_type,
                "lane_id": LANE_ID,
                "title": f.name,
                "summary": "",
                "source_path": rel,
                "public_symbols": exports,
            }
        )

        def _add_external(spec: str, kind: str, *, detail: str) -> None:
            ext_id = external_id(spec)
            node = externals.get(ext_id)
            if node is None:
                node = {
                    "id": ext_id,
                    "type": "external",
                    "lane_id": "lane:external-services",
                    "title": spec,
                    "summary": detail,
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
                    "source_path": rel,  # the importer cites this edge (B1#1)
                    "extractor": extractor,
                    "unresolved": True,
                }
            )

        # All specifier-bearing forms, resolved back through the string mask so
        # comment/string text cannot masquerade as an import (B1#3/B1#4).
        raw_specs: set[str] = set()
        for rgx in (_IMPORT_FROM_RE, _IMPORT_BARE_RE, _EXPORT_FROM_RE, _DYNAMIC_IMPORT_RE):
            for ph in rgx.findall(masked):
                val = _spec(ph, literals)
                if val:
                    raw_specs.add(val)
        # Dynamic import() whose argument is NOT a plain literal — never dropped.
        # Also catch import() nested inside a template-literal ${...} (which the
        # mask blanks) by scanning the RAW source.
        if _DYNAMIC_NONLITERAL_RE.search(masked) or _TEMPLATE_IMPORT_RE.search(text):
            _add_external(
                f"dynamic-import:{rel}", "unknown",
                detail="dynamic import() with a computed (non-literal) specifier",
            )

        for spec in sorted(raw_specs):
            if "${" in spec:  # interpolated template literal → not statically resolvable
                _add_external(spec, "unknown", detail="dynamic import — interpolated specifier")
                continue
            if spec.startswith("."):
                target = _resolve_relative(spec, f, repo_root, known, resolve_exts)
                if target is not None:
                    to_id = mod_id(rel_of[target])
                    if to_id != from_id:
                        edges.append(
                            {
                                "id": f"edge:import:{from_id}->{to_id}",
                                "type": "import",
                                "from": from_id,
                                "to": to_id,
                                "source_path": rel,  # importer cites this edge (B1#1)
                                "extractor": extractor,
                            }
                        )
                    continue
                _add_external(spec, "unknown",
                              detail="unresolved JS import — relative path with no local module")
            else:
                _add_external(spec, "external", detail="JS import — vendor/third-party module")

    for ext_id in sorted(externals):
        n = externals[ext_id]
        n["referenced_by"] = sorted(set(n["referenced_by"]))
        nodes.append(n)
    return nodes, edges
