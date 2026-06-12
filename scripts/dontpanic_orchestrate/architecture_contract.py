"""Evidence contract for the architecture view-state (plan 2026-06-07-001).

This module is the single source of the v0 evidence vocabulary and the pure
functions that stamp it onto every node/edge, classify unresolved references,
compute extractor coverage, and frame the as_built / intent / diff layer shell.

It is deliberately **contract-only**: no new extractors, no ADR ingestion, no
UI. It generalizes what the 007 crawler already emits into an honest,
provenance-carrying shape so the Architecture surface can say "this is what
DontPanic can prove from current evidence" instead of presenting a Python-shaped
guess as fact.

Two orthogonal axes (never conflated):
  * ``source_kind``  — WHERE the evidence lives (closed enum).
  * ``evidence_basis`` — HOW it is known.

``confidence`` is DERIVED from those + whether the endpoint resolved + whether a
``source_path`` is cited; it is never asserted without provenance.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# ─────────────────────────────── enums (v0) ────────────────────────────────

SOURCE_KINDS = (
    "code",
    "build",
    "manifest",
    "config",
    "infra",
    "test",
    "doc",
    "adr",
    "runtime",
    "external",
    "unknown",
    # Plan C0 — tier-0 filesystem inventory (directories, containment tree).
    "filesystem",
)
EVIDENCE_BASES = ("observed", "declared", "inferred", "unresolved")
CONFIDENCE_LEVELS = ("high", "medium", "low")

# F003 — extractor-coverage statuses. Distinct, never collapsed.
COVERAGE_STATUSES = (
    "covered",          # an extractor ran and produced evidence of this kind
    "not_found",        # extractor ran but the repo has no such artifact
    "missing_extractor",# the repo HAS this kind but DontPanic has no extractor
    "not_applicable",   # this kind cannot apply to this repo
    "error",            # extractor ran and failed
)

# F004 — as-built ↔ intent diff taxonomy (shell only in v0).
DIFF_TAXONOMY = (
    "aligned",
    "drift",
    "implemented_undocumented",
    "documented_unimplemented",
    "conflicting_dependency",
    "stale_adr",
    "unknown_confidence",
)

CONTRACT_VERSION = "v0"

# Per node ``type`` → (source_kind, evidence_basis, extractor method). The
# emission site may pre-set source_kind/evidence_basis (e.g. an unresolved
# external endpoint); those are respected and only the missing fields filled.
_NODE_EVIDENCE: dict[str, tuple[str, str, str]] = {
    "module": ("code", "observed", "python_import_crawler"),
    "schema": ("code", "observed", "json_schema_scan"),
    "plan": ("doc", "declared", "plan_index"),
    "command": ("code", "declared", "command_catalog"),
    "capability": ("manifest", "declared", "capability_manifest_scan"),
    "page": ("code", "observed", "dashboard_page_scan"),
    "js_module": ("code", "observed", "js_import_crawler"),
    "ts_module": ("code", "observed", "ts_import_crawler"),  # Plan C2
    "metadata": ("manifest", "observed", "architecture_fingerprint"),
    "external": ("external", "declared", "capability_manifest_scan"),
    "step": ("doc", "declared", "authored_flow"),
    "flow": ("doc", "declared", "authored_flow"),
}
_EDGE_EVIDENCE: dict[str, tuple[str, str, str]] = {
    "import": ("code", "observed", "python_import_crawler"),
    "runs": ("code", "declared", "command_catalog"),
    "reads": ("code", "declared", "architecture_view_state"),
    "writes": ("code", "declared", "architecture_view_state"),
    "calls": ("manifest", "declared", "capability_manifest_scan"),
    "step": ("doc", "declared", "authored_flow"),
}

# Extractor → the evidence kind it covers (F003).
EXTRACTORS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # (extractor_name, evidence_kind, node_types_it_produces)
    ("python_import_crawler", "code", ("module",)),
    ("json_schema_scan", "code", ("schema",)),
    ("plan_index", "doc", ("plan",)),
    ("capability_manifest_scan", "manifest", ("capability",)),
    ("dashboard_page_scan", "code", ("page",)),
    ("js_import_crawler", "code", ("js_module",)),  # Plan C slice 1
    ("ts_import_crawler", "code", ("ts_module",)),  # Plan C2
    ("architecture_fingerprint", "manifest", ("metadata",)),
)

# Evidence kinds DontPanic has NO extractor for, with the on-disk markers that
# prove the repo actually contains that kind (→ missing_extractor, not
# not_applicable). This is the load-bearing honesty case.
_UNEXTRACTED_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("swift", (".swift",)),
    ("xcode", (".xcodeproj", ".pbxproj")),
    ("kotlin", (".kt", ".kts")),
    ("gradle", ("build.gradle", "build.gradle.kts", "settings.gradle")),
    # Plan C's js_import_crawler extracts dashboard .js/.mjs/.cjs ONLY. TypeScript
    # and JSX have NO extractor, so their presence must still drop the ceiling
    # (audit 2026-06-08 B1#2: blanket-removing javascript let .ts/.tsx/.jsx pass
    # while the map read "high").
    ("typescript", (".ts", ".tsx")),
    ("jsx", (".jsx",)),
    ("go", (".go",)),
    ("rust", (".rs",)),
)
_SKIP_DIRS = frozenset(
    {".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__",
     ".next", "coverage", ".turbo", "vendor"}
)


# ───────────────────────────── F001: stamping ──────────────────────────────


def _derive_confidence(evidence_basis: str, *, resolved: bool, has_source: bool) -> str:
    """Confidence precedence (first match wins) — never asserted w/o provenance."""
    if evidence_basis == "unresolved":
        return "low"
    if evidence_basis == "inferred":
        return "low"
    if evidence_basis == "observed" and resolved:
        # "high" is only honest with a citation — never assert high w/o provenance
        # (audit 2026-06-08 B1#1: resolved import edges had no source_path).
        return "high" if has_source else "medium"
    if evidence_basis == "declared" and has_source:
        return "medium"
    return "low"


def _stamp(item: dict[str, Any], defaults: tuple[str, str, str], *, resolved: bool) -> None:
    src_default, basis_default, method_default = defaults
    # Emitters may attribute the real extractor (e.g. JS edges are NOT the
    # python_import_crawler) via an `extractor` hint (audit 2026-06-08 B1#1).
    method = item.get("extractor") or method_default
    source_kind = item.get("source_kind") or src_default
    # An unresolved endpoint is `unresolved` basis unless the emission site said
    # otherwise — never let a type default (e.g. import→observed) mask a drop.
    evidence_basis = item.get("evidence_basis") or (
        "unresolved" if not resolved else basis_default
    )
    source_path = item.get("source_path")
    has_source = isinstance(source_path, str) and bool(source_path)
    confidence = _derive_confidence(
        evidence_basis, resolved=resolved, has_source=has_source
    )
    item["source_kind"] = source_kind
    item["evidence_basis"] = evidence_basis
    item["confidence"] = confidence
    item["provenance"] = {
        "source_path": source_path if has_source else None,
        "resolved": resolved,
        "method": method,
    }


def apply_evidence_contract(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> None:
    """Stamp source_kind / evidence_basis / confidence / provenance on every
    node and edge IN PLACE (idempotent — re-stamping yields the same values).

    Emission sites that already set ``source_kind`` / ``evidence_basis`` (e.g.
    an unresolved external endpoint) are respected; the rest are derived from
    the node/edge ``type``.
    """
    for node in nodes:
        defaults = _NODE_EVIDENCE.get(
            str(node.get("type")), ("unknown", "inferred", "unknown")
        )
        resolved = bool(node.get("source_path")) and not node.get("unresolved")
        _stamp(node, defaults, resolved=resolved)
    for edge in edges:
        defaults = _EDGE_EVIDENCE.get(
            str(edge.get("type")), ("unknown", "inferred", "unknown")
        )
        resolved = not bool(edge.get("unresolved"))
        _stamp(edge, defaults, resolved=resolved)


# ──────────────────────── F002: unresolved classification ───────────────────


def classify_unresolved_endpoint(name: str, first_party_tops: set[str]) -> str:
    """Classify an import name the crawler could not resolve to an in-graph module.

    Returns a ``source_kind``:
      * ``unknown``  — its top segment is a FIRST-PARTY package that *should*
        have resolved (a genuine missing/typo/dynamic ref — "missing evidence").
      * ``external`` — stdlib or third-party (legitimately outside the graph).
    """
    top = name.split(".", 1)[0]
    if top in first_party_tops:
        return "unknown"
    return "external"


def is_stdlib(name: str) -> bool:
    top = name.split(".", 1)[0]
    return top in getattr(sys, "stdlib_module_names", frozenset())


# ───────────────────────────── F003: coverage ──────────────────────────────


# O(1)-per-entry marker lookup, built once. File extension → evidence kind,
# plus exact filenames and directory suffixes that don't read as extensions.
_EXT_TO_KIND: dict[str, str] = {
    ".swift": "swift",
    ".pbxproj": "xcode",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".gradle": "gradle",
    ".js": "javascript",   # extracted by js_import_crawler (dashboard scope)
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",   # NO extractor → drops the ceiling (audit B1#2)
    ".tsx": "typescript",
    ".jsx": "jsx",
    ".go": "go",
    ".rs": "rust",
}
_DIR_SUFFIX_TO_KIND: tuple[tuple[str, str], ...] = ((".xcodeproj", "xcode"),)
# Generous backstop so a pathological repo can't hang the <2s drift probe;
# O(1)/entry keeps a normal repo far under it. A marker past the cap is a v0
# limitation (recorded in the plan), never a silent confident claim.
_SCAN_ENTRY_CAP = 60000


def _repo_evidence_kinds(repo_root: Path) -> set[str]:
    """Bounded walk: which unextracted evidence kinds actually exist on disk."""
    found: set[str] = set()
    wanted = len(_UNEXTRACTED_KINDS)
    visited = 0
    try:
        for _dirpath, dirnames, filenames in os.walk(repo_root):
            # Prune skip-dirs AND hidden dirs (.git, .venv, .turbo, …).
            dirnames[:] = [
                d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
            ]
            for d in dirnames:
                for suffix, kind in _DIR_SUFFIX_TO_KIND:
                    if d.endswith(suffix):
                        found.add(kind)
            for fn in filenames:
                kind = _EXT_TO_KIND.get(os.path.splitext(fn)[1])
                if kind is not None:
                    found.add(kind)
            visited += len(dirnames) + len(filenames)
            if len(found) == wanted or visited >= _SCAN_ENTRY_CAP:
                break
    except OSError:
        pass
    return found


def compute_coverage(
    repo_root: Path, nodes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build the F003 extractor-coverage block.

    Every known extractor reports covered/not_found; evidence kinds the repo
    HAS but DontPanic cannot extract report missing_extractor; the confidence
    ceiling is driven DOWN by any missing_extractor so a repo whose primary
    language has no extractor never renders a confident map.
    """
    counts: dict[str, int] = {}
    for n in nodes:
        counts[str(n.get("type"))] = counts.get(str(n.get("type")), 0) + 1

    extractors: list[dict[str, Any]] = []
    for name, kind, node_types in EXTRACTORS:
        produced = sum(counts.get(t, 0) for t in node_types)
        extractors.append(
            {
                "extractor": name,
                "evidence_kind": kind,
                "status": "covered" if produced > 0 else "not_found",
                "node_count": produced,
            }
        )

    present = _repo_evidence_kinds(repo_root)
    missing: list[dict[str, Any]] = [
        {"evidence_kind": kind, "status": "missing_extractor"}
        for kind, _ in _UNEXTRACTED_KINDS
        if kind in present
    ]

    covered_any = any(e["status"] == "covered" for e in extractors)
    if missing:
        ceiling = "low"
    elif covered_any and all(
        e["status"] == "covered" for e in extractors
    ):
        ceiling = "high"
    elif covered_any:
        ceiling = "medium"
    else:
        ceiling = "low"

    return {
        "contract_version": CONTRACT_VERSION,
        "extractors": extractors,
        "missing_extractors": missing,
        "confidence_ceiling": ceiling,
        "note": (
            "Extractor coverage is the ceiling on the as-built model. "
            "missing_extractor means the repo contains this evidence kind but "
            "DontPanic has no extractor for it — the map is INCOMPLETE, not wrong."
        ),
    }


# ──────────────────────── F004: as_built / intent / diff ─────────────────────


def build_layer_shell(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, Any]:
    """Frame the as_built / intent / diff split (shell only — no reconciler).

    ``as_built`` describes today's extracted graph (the top-level nodes/edges
    ARE the as-built layer). ``intent`` is the reserved, empty claim shape a
    later ADR/doc extractor (Plan B) will populate. ``diff`` is empty and keyed
    by the defined taxonomy; nothing reconciles yet.
    """
    return {
        "contract_version": CONTRACT_VERSION,
        "as_built": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "is_current": True,
        },
        "intent": {
            "claims": [],
            "populated": False,
            "note": "Reserved for ADR/doc intent extraction (Plan B). Empty in v0.",
        },
        "diff": [],
        "diff_taxonomy": list(DIFF_TAXONOMY),
    }
