"""Architecture C0 — language-agnostic weak architecture-graph baseline.

Plan 2026-06-09-001. Four cooperating surfaces, all pure apart from reading
the scan root (no network, no mutation, no cache/state writes):

F001 — project detector: a deterministic ProjectProfile over a CLOSED list of
detection classes, built from the pinned marker tables below. Bounded
traversal with a deterministic cap; reaching the cap stamps the SHARED
``scan_truncated`` signal (one signal across detector, graph, and coverage).

F002 — tier-aware extractor registry: pure resolution of available vs missing
extractors per detected language. The tier-2 parser set is pinned EXACTLY as
today's production extractors (Python import crawler + dashboard JS crawler);
tier 3 is reserved and never available in C0.

F003 — tier-0 inventory + tier-1 heuristic graph: directory containment tree
rooted at the repo root (never a disconnected node bag), typed nodes for
manifests/build/test/docs/ADR/infra/config surfaces, manifest-inferred
framework ANNOTATIONS (never fabricated standalone nodes), and heuristic
import edges for every tier-1 matrix language — suppressed for parser-served
languages (tier precedence).

F004 — tiered coverage block: per-language map (detected languages ONLY),
per-evidence-type map keyed by the unified source_kind taxonomy (+
``filesystem``), the pinned deterministic rollup lattice, operator-facing
low-confidence notes, and truncation demotion.

Every table the pre-impl audit attempted to enumerate is pinned HERE with an
equality test (C0 D017 recorded-override contract).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# ──────────────────────────────  F001: pinned tables  ──────────────────────────────

DETECTION_CLASSES: tuple[str, ...] = (
    "languages",
    "package_managers",
    "build_systems",
    "test_frameworks",
    "app_frameworks",
    "docs",
    "adr",
    "infra",
    "config",
)
"""Closed ProjectProfile detection-class list (F001). docs and adr are
SEPARATE classes — never bundled."""

LANGUAGE_MARKER_MATRIX: dict[str, tuple[str, ...]] = {
    "python": (".py",),
    "javascript": (".js", ".mjs", ".cjs"),
    "typescript": (".ts", ".tsx"),
    "jsx": (".jsx",),
    "swift": (".swift",),
    "kotlin": (".kt", ".kts"),
    "go": (".go",),
    "rust": (".rs",),
}
"""The closed C0 language marker matrix — extending it is Plan C+ scope."""

TIER2_LANGUAGES: frozenset[str] = frozenset({"python", "javascript"})
"""Languages with a parser-backed extractor TODAY. TypeScript/TSX and JSX are
NOT parser-covered (the dashboard JS crawler reads .js/.mjs/.cjs only)."""

TIER1_LANGUAGES: frozenset[str] = (
    frozenset(LANGUAGE_MARKER_MATRIX) - TIER2_LANGUAGES
)

TIER2_EXTRACTORS: dict[str, str] = {
    "python": "python_import_crawler",
    "javascript": "js_import_crawler",
}
"""The pinned tier-2 set — the F004 scope guard asserts this never grows in
C0 (new parser extractors are Plan C+)."""

PACKAGE_MANAGER_MARKERS: dict[str, str] = {
    "package.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "pyproject.toml": "pip",
    "requirements.txt": "pip",
    "Pipfile": "pipenv",
    "poetry.lock": "poetry",
    "Podfile": "cocoapods",
    "Cartfile": "carthage",
    "Package.swift": "swiftpm",
    "go.mod": "gomod",
    "Cargo.toml": "cargo",
    "Gemfile": "bundler",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "pom.xml": "maven",
}

BUILD_SYSTEM_MARKERS: dict[str, str] = {
    "Makefile": "make",
    "CMakeLists.txt": "cmake",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "settings.gradle": "gradle",
    "Package.swift": "swiftpm",
    "webpack.config.js": "webpack",
    "vite.config.js": "vite",
    "vite.config.ts": "vite",
    "tsconfig.json": "tsc",
    "setup.py": "setuptools",
}
BUILD_SYSTEM_DIR_SUFFIXES: dict[str, str] = {".xcodeproj": "xcode"}

TEST_FRAMEWORK_MARKERS: dict[str, str] = {
    "pytest.ini": "pytest",
    "conftest.py": "pytest",
    "jest.config.js": "jest",
    "jest.config.ts": "jest",
    "vitest.config.js": "vitest",
    "vitest.config.ts": "vitest",
    "karma.conf.js": "karma",
}
TEST_DIR_NAMES: frozenset[str] = frozenset({"tests", "test", "__tests__", "spec"})

APP_FRAMEWORK_DEPENDENCY_MARKERS: dict[str, str] = {
    "react": "react",
    "next": "nextjs",
    "vue": "vue",
    "@angular/core": "angular",
    "express": "express",
    "django": "django",
    "flask": "flask",
    "fastapi": "fastapi",
    "rails": "rails",
}
"""Manifest-inferred (dependency-name -> framework). Detected from manifest
CONTENT, so represented as annotations on the owning manifest node (F003)."""

_APP_FRAMEWORK_MANIFESTS: frozenset[str] = frozenset(
    {"package.json", "pyproject.toml", "requirements.txt", "Gemfile"}
)

INFRA_FILE_MARKERS: dict[str, str] = {
    "Dockerfile": "docker",
    "docker-compose.yml": "docker-compose",
    "docker-compose.yaml": "docker-compose",
    "Jenkinsfile": "jenkins",
    ".gitlab-ci.yml": "gitlab-ci",
}
INFRA_EXTENSION_MARKERS: dict[str, str] = {".tf": "terraform"}
INFRA_DIR_MARKERS: dict[str, str] = {".github/workflows": "github-actions"}

CONFIG_EXTENSIONS: frozenset[str] = frozenset({".toml", ".yaml", ".yml", ".ini", ".cfg"})

DOC_DIR_NAMES: frozenset[str] = frozenset({"docs", "doc"})
ADR_DIR_NAMES: frozenset[str] = frozenset({"adr", "adrs", "decisions"})
_ADR_FILE_RE = re.compile(r"^ADR-\d+.*\.md$", re.IGNORECASE)

SOURCE_LIKE_EXTRA_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".zig", ".rb", ".java", ".c", ".h", ".cpp", ".cc", ".cs", ".php",
        ".scala", ".ex", ".exs", ".hs", ".lua", ".m", ".mm", ".dart",
        ".r", ".jl", ".pl",
    }
)
"""Source-like extensions OUTSIDE the marker matrix — the closed set that
feeds ``unrecognized_extensions`` (the producer for the unknown-language
note)."""

DETECTION_CLASS_TO_EVIDENCE_TYPE: dict[str, str] = {
    "languages": "code",
    "package_managers": "manifest",
    "build_systems": "build",
    "test_frameworks": "test",
    "app_frameworks": "manifest",
    "docs": "doc",
    "adr": "adr",
    "infra": "infra",
    "config": "config",
}
"""ONE taxonomy: every detection class maps into exactly one source_kind-
aligned evidence type. ``filesystem`` deliberately has NO detection class —
it is satisfied structurally by the tier-0 inventory itself (F004)."""

EVIDENCE_TYPES: tuple[str, ...] = (
    "filesystem",
    "code",
    "manifest",
    "build",
    "test",
    "config",
    "infra",
    "doc",
    "adr",
    "runtime",
)

SCAN_ENTRY_CAP: int = 50000
"""Deterministic traversal cap shared by detector and graph builder. Hitting
it sets the ONE scan_truncated signal."""

_SKIP_DIRS = frozenset(
    {".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__",
     ".next", "coverage", ".turbo", "vendor"}
)

LOW_CONFIDENCE_NOTE_TEMPLATE = "Dependency confidence is low. No {lang} extractor installed."
UNKNOWN_LANGUAGE_NOTE = (
    "Language dependency extraction was not attempted for unrecognized file types."
)

_EXT_TO_LANGUAGE: dict[str, str] = {
    ext: lang for lang, exts in LANGUAGE_MARKER_MATRIX.items() for ext in exts
}

# Tier-1 heuristic import patterns (F003). Python/JavaScript are parser-served
# and deliberately absent — tier precedence.
_HEURISTIC_IMPORT_PATTERNS: dict[str, re.Pattern[str]] = {
    "swift": re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)", re.MULTILINE),
    "kotlin": re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)", re.MULTILINE),
    "typescript": re.compile(
        r"""(?:import\s+(?:[\w*{},\s]+\s+from\s+)?|require\()\s*['"]([^'"]+)['"]"""
    ),
    "jsx": re.compile(
        r"""(?:import\s+(?:[\w*{},\s]+\s+from\s+)?|require\()\s*['"]([^'"]+)['"]"""
    ),
    "go": re.compile(r'^\s*(?:import\s+)?"([\w./-]+)"', re.MULTILINE),
    "rust": re.compile(r"^\s*use\s+([A-Za-z_][\w:]*)", re.MULTILINE),
}


# ──────────────────────────────  F001: detector  ──────────────────────────────


def _walk_bounded(repo_root: Path, scan_cap: int):
    """Deterministic bounded walk. Yields (dirpath, dirnames, filenames) with
    sorted entries and skip/hidden dirs pruned; returns truncated flag via
    the generator's StopIteration value — callers use ``_collect``."""
    visited = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".") or d == ".github"
        )
        filenames.sort()
        yield Path(dirpath), dirnames, filenames
        visited += len(dirnames) + len(filenames)
        if visited >= scan_cap:
            truncated = True
            break
    if truncated:
        raise _Truncated()


class _Truncated(Exception):
    """Internal control-flow signal for the bounded walk."""


def _collect(repo_root: Path, scan_cap: int) -> tuple[list[tuple[Path, list[str], list[str]]], bool]:
    entries: list[tuple[Path, list[str], list[str]]] = []
    truncated = False
    gen = _walk_bounded(repo_root, scan_cap)
    try:
        for item in gen:
            entries.append(item)
    except _Truncated:
        truncated = True
    return entries, truncated


def _detect_app_frameworks(path: Path) -> list[str]:
    """Manifest-inferred app frameworks — read the manifest CONTENT for
    dependency markers. Pure read; tolerant of unreadable files."""
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return []
    found = []
    for marker, framework in APP_FRAMEWORK_DEPENDENCY_MARKERS.items():
        if re.search(r'["\']?' + re.escape(marker) + r'["\']?\s*[:=<>~^]', text) or (
            f'"{marker}"' in text
        ):
            found.append(framework)
    return sorted(set(found))


def detect_project(repo_root: Path, *, scan_cap: int | None = None) -> dict[str, Any]:
    """F001 — deterministic, pure, bounded ProjectProfile."""
    scan_cap = SCAN_ENTRY_CAP if scan_cap is None else scan_cap
    repo_root = Path(repo_root).resolve()
    profile: dict[str, Any] = {cls: [] for cls in DETECTION_CLASSES}
    # docs/adr are presence classes carrying their marker paths.
    languages: set[str] = set()
    package_managers: set[str] = set()
    build_systems: set[str] = set()
    test_frameworks: set[str] = set()
    app_frameworks: dict[str, list[str]] = {}  # rel manifest path -> frameworks
    docs_markers: set[str] = set()
    adr_markers: set[str] = set()
    infra: set[str] = set()
    config: set[str] = set()
    unrecognized: set[str] = set()

    entries, truncated = _collect(repo_root, scan_cap)
    for dirpath, dirnames, filenames in entries:
        rel_dir = dirpath.relative_to(repo_root).as_posix()
        for d in dirnames:
            if d in TEST_DIR_NAMES:
                pass  # test DIRS are graph surface, not a framework claim
            if d in DOC_DIR_NAMES:
                docs_markers.add(f"{rel_dir}/{d}".lstrip("./"))
            if d.lower() in ADR_DIR_NAMES:
                adr_markers.add(f"{rel_dir}/{d}".lstrip("./"))
            for suffix, system in BUILD_SYSTEM_DIR_SUFFIXES.items():
                if d.endswith(suffix):
                    build_systems.add(system)
        rel_for_infra = rel_dir if rel_dir != "." else ""
        for marker_dir, kind in INFRA_DIR_MARKERS.items():
            candidate = (repo_root / marker_dir)
            if candidate.is_dir():
                infra.add(kind)
        for fn in filenames:
            ext = os.path.splitext(fn)[1]
            lang = _EXT_TO_LANGUAGE.get(ext)
            if lang:
                languages.add(lang)
            elif ext in SOURCE_LIKE_EXTRA_EXTENSIONS:
                unrecognized.add(ext)
            if fn in PACKAGE_MANAGER_MARKERS:
                package_managers.add(PACKAGE_MANAGER_MARKERS[fn])
            if fn in BUILD_SYSTEM_MARKERS:
                build_systems.add(BUILD_SYSTEM_MARKERS[fn])
            if fn in TEST_FRAMEWORK_MARKERS:
                test_frameworks.add(TEST_FRAMEWORK_MARKERS[fn])
            if fn in INFRA_FILE_MARKERS:
                infra.add(INFRA_FILE_MARKERS[fn])
            if ext in INFRA_EXTENSION_MARKERS:
                infra.add(INFRA_EXTENSION_MARKERS[ext])
            if ext in CONFIG_EXTENSIONS:
                config.add(ext)
            if ext == ".md":
                if _ADR_FILE_RE.match(fn):
                    adr_markers.add((Path(rel_for_infra) / fn).as_posix())
                docs_markers.add((Path(rel_for_infra) / fn).as_posix())
            if fn in _APP_FRAMEWORK_MANIFESTS:
                frameworks = _detect_app_frameworks(dirpath / fn)
                if frameworks:
                    rel = (Path(rel_for_infra) / fn).as_posix()
                    app_frameworks[rel] = frameworks

    profile["languages"] = sorted(languages)
    profile["package_managers"] = sorted(package_managers)
    profile["build_systems"] = sorted(build_systems)
    profile["test_frameworks"] = sorted(test_frameworks)
    profile["app_frameworks"] = {k: app_frameworks[k] for k in sorted(app_frameworks)}
    profile["docs"] = sorted(docs_markers)
    profile["adr"] = sorted(adr_markers)
    profile["infra"] = sorted(infra)
    profile["config"] = sorted(config)
    profile["unrecognized_extensions"] = sorted(unrecognized)
    profile["scan_truncated"] = truncated
    return profile


# ──────────────────────────────  F002: registry  ──────────────────────────────


def resolve_extractors(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure, deterministic tier-aware registry resolution for a profile.

    Tier 0 (filesystem inventory) is always available. Tier 1 heuristic is
    available for every tier-1 matrix language. Tier 2 is EXACTLY the pinned
    parser set. Tier 3 (build/runtime) is reserved — never available in C0.
    A detected language without a tier-2 parser reports the missing
    higher-tier extractor while still served by tiers 0/1.
    """
    rows: list[dict[str, Any]] = [
        {
            "evidence_kind": "filesystem",
            "language": None,
            "tier": 0,
            "extractor": "tier0_inventory",
            "available": True,
        }
    ]
    for lang in profile.get("languages", []):
        if lang in TIER2_LANGUAGES:
            rows.append(
                {
                    "evidence_kind": "code",
                    "language": lang,
                    "tier": 2,
                    "extractor": TIER2_EXTRACTORS[lang],
                    "available": True,
                }
            )
        else:
            rows.append(
                {
                    "evidence_kind": "code",
                    "language": lang,
                    "tier": 1,
                    "extractor": "heuristic_import_scan",
                    "available": True,
                }
            )
            rows.append(
                {
                    "evidence_kind": "code",
                    "language": lang,
                    "tier": 2,
                    "extractor": None,
                    "available": False,  # missing higher-tier extractor
                }
            )
    rows.append(
        {
            "evidence_kind": "runtime",
            "language": None,
            "tier": 3,
            "extractor": None,
            "available": False,  # reserved — Tier-3 collection is a non-goal
        }
    )
    return rows


# ──────────────────────────────  F003: tier-0/1 graph  ──────────────────────────────


BASELINE_LANE_ID = "lane:orchestrator-runtime"


def _node(node_id: str, node_type: str, label: str, source_kind: str,
          evidence_basis: str, source_path: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": node_id,
        "type": node_type,
        "label": label,
        "title": label,
        "lane_id": BASELINE_LANE_ID,
        "source_kind": source_kind,
        "evidence_basis": evidence_basis,
        "extractor": "tier0_inventory",
    }
    if source_path is not None:
        item["source_path"] = source_path
    return item


def _file_source_kind(fn: str) -> str | None:
    """Classify a tier-0 file into its evidence home, or None for plain files."""
    ext = os.path.splitext(fn)[1]
    if fn in PACKAGE_MANAGER_MARKERS:
        return "manifest"
    if fn in BUILD_SYSTEM_MARKERS:
        return "build"
    if fn in TEST_FRAMEWORK_MARKERS:
        return "test"
    if fn in INFRA_FILE_MARKERS or ext in INFRA_EXTENSION_MARKERS:
        return "infra"
    if ext == ".md":
        return "adr" if _ADR_FILE_RE.match(fn) else "doc"
    if ext in CONFIG_EXTENSIONS:
        return "config"
    return None


def build_baseline_graph(
    repo_root: Path,
    profile: dict[str, Any] | None = None,
    *,
    scan_cap: int | None = None,
) -> dict[str, Any]:
    """F003 — tier-0 inventory + tier-1 heuristic edges. Deterministic,
    bounded, pure apart from reading the scan root. Non-empty for any repo
    (repo-root node always present). Containment edges connect every node
    into one tree rooted at the repo root."""
    scan_cap = SCAN_ENTRY_CAP if scan_cap is None else scan_cap
    repo_root = Path(repo_root).resolve()
    if profile is None:
        profile = detect_project(repo_root, scan_cap=scan_cap)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    root_id = "fs:."
    nodes.append(_node(root_id, "fs_dir", repo_root.name or ".", "filesystem", "declared", "."))

    entries, truncated = _collect(repo_root, scan_cap)
    truncated = truncated or bool(profile.get("scan_truncated"))
    tier1_detected = [l for l in profile.get("languages", []) if l in TIER1_LANGUAGES]
    heuristic_files: list[tuple[Path, str, str]] = []  # (abs path, rel, language)

    for dirpath, dirnames, filenames in entries:
        rel_dir = dirpath.relative_to(repo_root).as_posix()
        dir_id = "fs:." if rel_dir == "." else f"fs:{rel_dir}"
        for d in dirnames:
            child_rel = d if rel_dir == "." else f"{rel_dir}/{d}"
            child_id = f"fs:{child_rel}"
            node_type = "fs_test_dir" if d in TEST_DIR_NAMES else "fs_dir"
            kind = "test" if d in TEST_DIR_NAMES else "filesystem"
            nodes.append(_node(child_id, node_type, d, kind, "declared", child_rel))
            edges.append(
                {
                    "id": f"edge:contains:{dir_id}->{child_id}",
                    "type": "contains",
                    "from": dir_id,
                    "to": child_id,
                    "source_kind": "filesystem",
                    "evidence_basis": "declared",
                    "extractor": "tier0_inventory",
                }
            )
        for fn in filenames:
            rel_file = fn if rel_dir == "." else f"{rel_dir}/{fn}"
            kind = _file_source_kind(fn)
            ext = os.path.splitext(fn)[1]
            lang = _EXT_TO_LANGUAGE.get(ext)
            # Tier-0 keeps CLASSIFIED files (manifest/build/test/config/infra/
            # doc/adr) plus tier-1 source files (heuristic-edge sources).
            # Plain files and tier-2 sources are parser/dir territory — the
            # directory tree carries the rest of the inventory.
            if kind is None and lang not in tier1_detected:
                continue
            file_id = f"fs:{rel_file}"
            node_type = f"fs_{kind}" if kind else "fs_source"
            node_kind = kind or "code"
            file_node = _node(file_id, node_type, fn, node_kind, "declared", rel_file)
            # Manifest-inferred frameworks become ANNOTATIONS on the owning
            # manifest node — never fabricated standalone nodes (F003).
            if kind == "manifest":
                annotations: dict[str, Any] = {}
                frameworks = profile.get("app_frameworks", {}).get(rel_file)
                if frameworks:
                    annotations["app_frameworks"] = frameworks
                if fn in TEST_FRAMEWORK_MARKERS:
                    annotations.setdefault("test_frameworks", []).append(
                        TEST_FRAMEWORK_MARKERS[fn]
                    )
                if annotations:
                    file_node["annotations"] = annotations
            nodes.append(file_node)
            edges.append(
                {
                    "id": f"edge:contains:{dir_id}->{file_id}",
                    "type": "contains",
                    "from": dir_id,
                    "to": file_id,
                    "source_kind": "filesystem",
                    "evidence_basis": "declared",
                    "extractor": "tier0_inventory",
                }
            )
            if lang in tier1_detected:
                heuristic_files.append((dirpath / fn, rel_file, lang))

    # Tier-1 heuristic import edges — tier precedence: parser-served
    # languages (python/javascript) never get heuristic counterparts.
    file_ids = {n["source_path"] for n in nodes if "source_path" in n}
    for abs_path, rel_file, lang in heuristic_files:
        pattern = _HEURISTIC_IMPORT_PATTERNS.get(lang)
        if pattern is None:
            continue
        try:
            text = abs_path.read_text(errors="ignore")
        except OSError:
            continue
        for match in sorted(set(pattern.findall(text))):
            target_rel = None
            if match.startswith("."):
                base = (Path(rel_file).parent / match).as_posix()
                for candidate_ext in LANGUAGE_MARKER_MATRIX[lang]:
                    if f"{base}{candidate_ext}".lstrip("./") in file_ids:
                        target_rel = f"{base}{candidate_ext}".lstrip("./")
                        break
            resolved = target_rel is not None
            to_id = f"fs:{target_rel}" if resolved else f"heuristic:{lang}:{match}"
            if not resolved:
                nodes.append(
                    {
                        "id": to_id,
                        "type": "heuristic_target",
                        "label": match,
                        "title": match,
                        "lane_id": BASELINE_LANE_ID,
                        "source_kind": "unknown",
                        "evidence_basis": "unresolved",
                        "extractor": "heuristic_import_scan",
                    }
                )
            edges.append(
                {
                    "id": f"edge:himport:fs:{rel_file}->{to_id}",
                    "type": "heuristic_import",
                    "from": f"fs:{rel_file}",
                    "to": to_id,
                    "source_kind": "code",
                    "evidence_basis": "inferred" if resolved else "unresolved",
                    "extractor": "heuristic_import_scan",
                    "resolved": resolved,
                }
            )

    # Dedupe (heuristic targets can repeat across files).
    seen: set[str] = set()
    deduped_nodes = []
    for n in nodes:
        if n["id"] not in seen:
            seen.add(n["id"])
            deduped_nodes.append(n)

    return {
        "nodes": deduped_nodes,
        "edges": edges,
        "scan_truncated": truncated,
        "scan_cap": scan_cap,
    }


# ──────────────────────────────  F004: tiered coverage  ──────────────────────────────


def _evidence_type_detected(profile: dict[str, Any], evidence_type: str) -> bool:
    for cls, etype in DETECTION_CLASS_TO_EVIDENCE_TYPE.items():
        if etype != evidence_type:
            continue
        value = profile.get(cls)
        if value:
            return True
    return False


def build_baseline_coverage(
    profile: dict[str, Any], graph: dict[str, Any]
) -> dict[str, Any]:
    """F004 — the tiered coverage block, every rule pinned by the plan."""
    truncated = bool(graph.get("scan_truncated") or profile.get("scan_truncated"))
    languages = profile.get("languages", [])

    # Per-language map: EXACTLY the detected languages — never not_found.
    per_language: dict[str, str] = {}
    for lang in languages:
        per_language[lang] = "covered" if lang in TIER2_LANGUAGES else "missing_extractor"

    # Per-evidence-type map.
    per_type: dict[str, dict[str, Any]] = {}
    # filesystem: satisfied structurally by the tier-0 inventory.
    per_type["filesystem"] = {
        "status": "partial" if truncated else "covered",
        "tier": 0,
        "confidence_ceiling": "medium",
    }
    # code: deterministic aggregation across detected languages.
    if not languages:
        code_status = "not_found"
    elif all(lang in TIER2_LANGUAGES for lang in languages):
        code_status = "covered"
    else:
        code_status = "partial"
    per_type["code"] = {
        "status": code_status,
        "tier": 2 if code_status == "covered" else 1,
        "confidence_ceiling": "high" if code_status == "covered" else "low",
    }
    # The seven non-code classes: covered at tier 0 (declared/medium) when the
    # class was detected AND a corresponding tier-0 representation exists;
    # not_found when undetected; never missing_extractor in C0; truncation
    # demotes to partial exactly like filesystem.
    node_kinds = {n.get("source_kind") for n in graph.get("nodes", [])}
    annotated = any(n.get("annotations") for n in graph.get("nodes", []))
    for etype in ("manifest", "build", "test", "config", "infra", "doc", "adr"):
        detected = _evidence_type_detected(profile, etype)
        represented = etype in node_kinds or (
            etype == "manifest" and annotated
        )
        if not detected:
            status = "not_found"
        elif truncated:
            status = "partial"
        elif represented:
            status = "covered"
        else:
            status = "partial"  # detected but capped before its node landed
        per_type[etype] = {
            "status": status,
            "tier": 0,
            "confidence_ceiling": "medium",
        }
    # runtime: tier-3 reserved — always not_found in C0, never demotes.
    per_type["runtime"] = {"status": "not_found", "tier": 3, "reserved": True}

    # Pinned rollup lattice.
    any_tier2 = any(lang in TIER2_LANGUAGES for lang in languages)
    all_tier2 = bool(languages) and all(lang in TIER2_LANGUAGES for lang in languages)
    detected_classes_ok = all(
        per_type[etype]["status"] in ("covered", "not_found")
        for etype in EVIDENCE_TYPES
        if etype not in ("runtime",)
    )
    if not any_tier2:
        rollup = "limited"
    elif all_tier2 and detected_classes_ok and not truncated:
        rollup = "covered"
    else:
        rollup = "partial"

    # Operator-facing notes — rendered payload fields, not edge metadata.
    notes: list[str] = []
    for lang in languages:
        if lang not in TIER2_LANGUAGES:
            notes.append(LOW_CONFIDENCE_NOTE_TEMPLATE.format(lang=lang.capitalize()))
    if profile.get("unrecognized_extensions"):
        notes.append(UNKNOWN_LANGUAGE_NOTE)

    return {
        "rollup": rollup,
        "per_language": per_language,
        "per_evidence_type": per_type,
        "scan_truncated": truncated,
        "notes": notes,
        "unrecognized_extensions": profile.get("unrecognized_extensions", []),
    }


def build_baseline(repo_root: Path, *, scan_cap: int | None = None) -> dict[str, Any]:
    """Detection -> registry -> baseline graph -> coverage, run together —
    the unit build_view_state and project registration consume."""
    scan_cap = SCAN_ENTRY_CAP if scan_cap is None else scan_cap
    profile = detect_project(repo_root, scan_cap=scan_cap)
    registry = resolve_extractors(profile)
    graph = build_baseline_graph(repo_root, profile, scan_cap=scan_cap)
    coverage = build_baseline_coverage(profile, graph)
    return {
        "profile": profile,
        "registry": registry,
        "graph": graph,
        "coverage": coverage,
    }


__all__ = [
    "ADR_DIR_NAMES",
    "APP_FRAMEWORK_DEPENDENCY_MARKERS",
    "BUILD_SYSTEM_DIR_SUFFIXES",
    "BUILD_SYSTEM_MARKERS",
    "CONFIG_EXTENSIONS",
    "DETECTION_CLASSES",
    "DETECTION_CLASS_TO_EVIDENCE_TYPE",
    "DOC_DIR_NAMES",
    "EVIDENCE_TYPES",
    "INFRA_DIR_MARKERS",
    "INFRA_EXTENSION_MARKERS",
    "INFRA_FILE_MARKERS",
    "LANGUAGE_MARKER_MATRIX",
    "LOW_CONFIDENCE_NOTE_TEMPLATE",
    "PACKAGE_MANAGER_MARKERS",
    "SCAN_ENTRY_CAP",
    "SOURCE_LIKE_EXTRA_EXTENSIONS",
    "TEST_DIR_NAMES",
    "TEST_FRAMEWORK_MARKERS",
    "TIER1_LANGUAGES",
    "TIER2_EXTRACTORS",
    "TIER2_LANGUAGES",
    "UNKNOWN_LANGUAGE_NOTE",
    "build_baseline",
    "build_baseline_coverage",
    "build_baseline_graph",
    "detect_project",
    "resolve_extractors",
]
