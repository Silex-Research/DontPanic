"""Plan 2026-06-09-001 F001/F002 — detector tables + registry.

Every table the pre-impl audit attempted to enumerate is pinned here with an
EQUALITY test (the C0 D017 recorded-override contract): languages, package
managers, build systems, test frameworks, app frameworks, docs/ADR, infra,
config, unknown extensions, and the detection-class -> evidence-type mapping.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import architecture_baseline as ab  # noqa: E402
from dontpanic_orchestrate import architecture_contract as ac  # noqa: E402

# ──────────────────────────────  table equality pins  ──────────────────────────────


def test_language_marker_matrix_pinned():
    assert ab.LANGUAGE_MARKER_MATRIX == {
        "python": (".py",),
        "javascript": (".js", ".mjs", ".cjs"),
        "typescript": (".ts", ".tsx"),
        "jsx": (".jsx",),
        "swift": (".swift",),
        "kotlin": (".kt", ".kts"),
        "go": (".go",),
        "rust": (".rs",),
    }


def test_tier_split_pinned():
    # Plan C2 promoted typescript/jsx to tier 2 (ts_import_crawler) — the C0
    # scope guard anticipated exactly this growth ("Plan C+ owns that").
    assert ab.TIER2_LANGUAGES == {"python", "javascript", "typescript", "jsx"}
    assert ab.TIER1_LANGUAGES == {"swift", "kotlin", "go", "rust"}
    assert ab.TIER2_EXTRACTORS == {
        "python": "python_import_crawler",
        "javascript": "js_import_crawler",
        "typescript": "ts_import_crawler",
        "jsx": "ts_import_crawler",
    }


def test_package_manager_markers_pinned():
    assert ab.PACKAGE_MANAGER_MARKERS == {
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


def test_build_system_markers_pinned():
    assert ab.BUILD_SYSTEM_MARKERS == {
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
    assert ab.BUILD_SYSTEM_DIR_SUFFIXES == {".xcodeproj": "xcode"}


def test_test_framework_markers_pinned():
    assert ab.TEST_FRAMEWORK_MARKERS == {
        "pytest.ini": "pytest",
        "conftest.py": "pytest",
        "jest.config.js": "jest",
        "jest.config.ts": "jest",
        "vitest.config.js": "vitest",
        "vitest.config.ts": "vitest",
        "karma.conf.js": "karma",
    }
    assert ab.TEST_DIR_NAMES == {"tests", "test", "__tests__", "spec"}


def test_app_framework_markers_pinned():
    assert ab.APP_FRAMEWORK_DEPENDENCY_MARKERS == {
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


def test_infra_and_config_markers_pinned():
    assert ab.INFRA_FILE_MARKERS == {
        "Dockerfile": "docker",
        "docker-compose.yml": "docker-compose",
        "docker-compose.yaml": "docker-compose",
        "Jenkinsfile": "jenkins",
        ".gitlab-ci.yml": "gitlab-ci",
    }
    assert ab.INFRA_EXTENSION_MARKERS == {".tf": "terraform"}
    assert ab.INFRA_DIR_MARKERS == {".github/workflows": "github-actions"}
    assert ab.CONFIG_EXTENSIONS == {".toml", ".yaml", ".yml", ".ini", ".cfg"}


def test_docs_adr_markers_pinned():
    assert ab.DOC_DIR_NAMES == {"docs", "doc"}
    assert ab.ADR_DIR_NAMES == {"adr", "adrs", "decisions"}


def test_unknown_extension_set_is_closed_and_disjoint_from_matrix():
    matrix_exts = {e for exts in ab.LANGUAGE_MARKER_MATRIX.values() for e in exts}
    assert not (ab.SOURCE_LIKE_EXTRA_EXTENSIONS & matrix_exts)
    assert ".zig" in ab.SOURCE_LIKE_EXTRA_EXTENSIONS


def test_detection_class_mapping_total_and_one_taxonomy():
    # Totality: every detection class maps to exactly one evidence type.
    assert set(ab.DETECTION_CLASS_TO_EVIDENCE_TYPE) == set(ab.DETECTION_CLASSES)
    # Every target is a real evidence type; filesystem deliberately has NO class.
    assert set(ab.DETECTION_CLASS_TO_EVIDENCE_TYPE.values()) <= set(ab.EVIDENCE_TYPES)
    assert "filesystem" not in ab.DETECTION_CLASS_TO_EVIDENCE_TYPE.values()
    # One taxonomy: evidence types align with the contract's source_kind enum
    # (filesystem included; external/unknown excluded from coverage keys).
    assert set(ab.EVIDENCE_TYPES) <= set(ac.SOURCE_KINDS)
    assert "filesystem" in ac.SOURCE_KINDS


# ──────────────────────────────  detector behavior  ──────────────────────────────


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_detector_deterministic_and_pure(tmp_path: Path):
    root = _make_repo(tmp_path, {"a.swift": "import Foundation\n", "package.json": "{}"})
    before = sorted(p.as_posix() for p in root.rglob("*"))
    p1 = ab.detect_project(root)
    p2 = ab.detect_project(root)
    assert p1 == p2, "same repo -> identical profile"
    after = sorted(p.as_posix() for p in root.rglob("*"))
    assert before == after, "no mutation, no cache/state writes inside the repo"


def test_detector_empty_repo_profile(tmp_path: Path):
    root = tmp_path / "empty"
    root.mkdir()
    profile = ab.detect_project(root)
    assert profile["languages"] == []
    assert profile["unrecognized_extensions"] == []
    assert profile["scan_truncated"] is False


def test_detector_tables_drive_detection(tmp_path: Path):
    root = _make_repo(
        tmp_path,
        {
            "src/main.swift": "import UIKit\n",
            "Podfile": "",
            "Makefile": "",
            "conftest.py": "",
            "package.json": '{"dependencies": {"react": "^18.0.0"}}',
            "Dockerfile": "",
            "infra/main.tf": "",
            "settings.yaml": "",
            "docs/guide.md": "# docs",
            "docs/adr/ADR-001-choice.md": "# adr",
        },
    )
    profile = ab.detect_project(root)
    assert "swift" in profile["languages"]
    assert "python" in profile["languages"]  # conftest.py is also .py
    assert "cocoapods" in profile["package_managers"]
    assert "npm" in profile["package_managers"]
    assert "make" in profile["build_systems"]
    assert "pytest" in profile["test_frameworks"]
    assert profile["app_frameworks"] == {"package.json": ["react"]}
    assert {"docker", "terraform"} <= set(profile["infra"])
    assert ".yaml" in profile["config"]
    assert any("docs" in d for d in profile["docs"])
    assert any("ADR-001" in a for a in profile["adr"])


def test_detector_unrecognized_extensions_producer(tmp_path: Path):
    root = _make_repo(tmp_path, {"main.zig": "const std = @import(\"std\");\n"})
    profile = ab.detect_project(root)
    assert profile["unrecognized_extensions"] == [".zig"]
    assert profile["languages"] == []


def test_detector_bounded_cap_stamps_truncation(tmp_path: Path):
    files = {f"d{i}/f{i}.swift": "import A\n" for i in range(40)}
    root = _make_repo(tmp_path, files)
    profile = ab.detect_project(root, scan_cap=10)
    assert profile["scan_truncated"] is True


# ──────────────────────────────  registry  ──────────────────────────────


def test_registry_pure_deterministic_and_tier_aware():
    profile = {"languages": ["python", "swift"]}
    r1 = ab.resolve_extractors(profile)
    r2 = ab.resolve_extractors(profile)
    assert r1 == r2, "same profile -> identical resolution"
    by_lang_tier = {(r["language"], r["tier"]): r for r in r1}
    assert by_lang_tier[("python", 2)]["available"] is True
    assert by_lang_tier[("swift", 1)]["available"] is True
    assert by_lang_tier[("swift", 2)]["available"] is False, (
        "detected language without a parser reports the missing higher tier"
    )


def test_registry_tier3_reserved_never_available():
    for profile in ({"languages": []}, {"languages": ["python", "go", "rust"]}):
        rows = ab.resolve_extractors(profile)
        tier3 = [r for r in rows if r["tier"] == 3]
        assert tier3 and all(not r["available"] for r in tier3), (
            "Tier-3 build/runtime collection is a stated non-goal — reserved"
        )


def test_registry_tier0_always_available():
    rows = ab.resolve_extractors({"languages": []})
    assert any(r["tier"] == 0 and r["available"] for r in rows)
