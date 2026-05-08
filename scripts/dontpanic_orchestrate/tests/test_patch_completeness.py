"""F002 — patch_completeness analyzer.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_patch_completeness.py

Pure-function analyzer over a captured GitState + explicit touched_files.
No supervisor wiring (F003 owns that). No audit_writer mutation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import patch_completeness  # noqa: E402
from dontpanic_orchestrate.patch_completeness import (  # noqa: E402
    CompletenessReport,
    Finding,
)

# ──────────────────────────────  fixture helpers  ──────────────────────────────


def _state(
    *,
    staged: list[dict] | None = None,
    unstaged_modified: list[dict] | None = None,
    untracked: list[str] | None = None,
    deleted_staged: list[str] | None = None,
    deleted_unstaged: list[str] | None = None,
) -> dict:
    return {
        "staged": staged or [],
        "unstaged_modified": unstaged_modified or [],
        "untracked": untracked or [],
        "deleted_staged": deleted_staged or [],
        "deleted_unstaged": deleted_unstaged or [],
    }


def _write(repo: Path, path: str, content: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(content)


# ──────────────────────────────  envelope shape  ──────────────────────────────


def test_clean_patch_returns_pass(tmp_path: Path) -> None:
    """Acceptance (7c): clean patch → status='pass', findings==[]."""
    report = patch_completeness.check(_state(), tmp_path, set())
    assert report.status == "pass"
    assert report.findings == []
    assert report.files == []
    assert report.schema_version == "1.0"


def test_report_json_roundtrip(tmp_path: Path) -> None:
    """Acceptance (3): JSON round-trip pins the envelope shape."""
    _write(tmp_path, "needs.py", "x = 1\n")
    _write(
        tmp_path,
        "tests/test_uses.py",
        "from needs import x\n",
    )
    git = _state(untracked=["needs.py"])

    report = patch_completeness.check(git, tmp_path, {"tests/test_uses.py"})
    blob = json.dumps(report.to_dict(), indent=2)
    rt = CompletenessReport.from_dict(json.loads(blob))
    assert rt == report
    assert rt.schema_version == "1.0"


# ──────────────────────────────  Mode 1: test_imports_uncommitted  ──────────────────────────────


@pytest.mark.parametrize("variant", ["untracked", "unstaged_modified"])
def test_mode1_test_imports_uncommitted(tmp_path: Path, variant: str) -> None:
    """6a: test file imports a source that's untracked or unstaged_modified."""
    _write(tmp_path, "needs.py", "x = 1\n")
    _write(tmp_path, "tests/test_uses.py", "from needs import x\n")

    if variant == "untracked":
        git = _state(untracked=["needs.py"])
    else:
        git = _state(unstaged_modified=[{"path": "needs.py", "status": "M"}])

    report = patch_completeness.check(git, tmp_path, {"tests/test_uses.py"})
    modes = [f.mode for f in report.findings]
    assert "test_imports_uncommitted" in modes, modes
    finding = next(f for f in report.findings if f.mode == "test_imports_uncommitted")
    assert finding.severity == "block"
    assert "needs.py" in finding.files
    assert "git add" in finding.recommendation


# ──────────────────────────────  Mode 2: source_imports_uncommitted  ──────────────────────────────


@pytest.mark.parametrize("variant", ["untracked", "unstaged_modified"])
def test_mode2_source_imports_uncommitted(tmp_path: Path, variant: str) -> None:
    """6b: non-test source imports a module that's untracked or unstaged_modified."""
    _write(tmp_path, "lib/helper.py", "y = 2\n")
    _write(tmp_path, "lib/main.py", "from lib.helper import y\n")

    if variant == "untracked":
        git = _state(untracked=["lib/helper.py"])
    else:
        git = _state(unstaged_modified=[{"path": "lib/helper.py", "status": "M"}])

    report = patch_completeness.check(git, tmp_path, {"lib/main.py"})
    finding = next(f for f in report.findings if f.mode == "source_imports_uncommitted")
    assert finding.severity == "block"
    assert "lib/helper.py" in finding.files


# ──────────────────────────────  Mode 3: test_file_untracked  ──────────────────────────────


@pytest.mark.parametrize("variant", ["untracked", "unstaged_modified"])
def test_mode3_test_file_untracked_or_modified(tmp_path: Path, variant: str) -> None:
    """6c/6d: test file itself missing from commit — pytest discovery skips it on fresh clone."""
    _write(tmp_path, "tests/test_new.py", "def test_x(): assert True\n")

    if variant == "untracked":
        git = _state(untracked=["tests/test_new.py"])
    else:
        git = _state(unstaged_modified=[{"path": "tests/test_new.py", "status": "M"}])

    report = patch_completeness.check(git, tmp_path, set())
    finding = next(f for f in report.findings if f.mode == "test_file_untracked")
    assert finding.severity == "block"
    assert "tests/test_new.py" in finding.files


def test_mode3_recognises_underscore_test_suffix(tmp_path: Path) -> None:
    """`*_test.py` naming convention also classifies as a test file."""
    _write(tmp_path, "tests/things_test.py", "def test_y(): assert True\n")
    git = _state(untracked=["tests/things_test.py"])
    report = patch_completeness.check(git, tmp_path, set())
    assert any(f.mode == "test_file_untracked" for f in report.findings)


def test_mode3_top_level_test_file_outside_test_dir_does_not_fire(tmp_path: Path) -> None:
    """`test_*.py` outside any test/ or tests/ directory is NOT classified as a test file."""
    _write(tmp_path, "test_misnamed.py", "def hello(): pass\n")
    git = _state(untracked=["test_misnamed.py"])
    report = patch_completeness.check(git, tmp_path, set())
    assert not any(f.mode == "test_file_untracked" for f in report.findings)


# ──────────────────────────────  Mode 4: generated_artifact_staged  ──────────────────────────────


@pytest.mark.parametrize(
    "staged_path",
    [
        "scripts/foo/__pycache__/bar.cpython-310.pyc",
        "scripts/foo.pyc",
        "scripts/foo.pyo",
        ".coverage",
        "scripts/.DS_Store",
        ".pytest_cache/v/cache/lastfailed",
        "node_modules/some-pkg/index.js",
        ".tox/py310/lib/python3.10/site-packages/x.py",
        ".mypy_cache/3.10/foo.json",
        ".ruff_cache/0.1.0/foo.json",
    ],
    ids=[
        "__pycache__",
        "pyc",
        "pyo",
        "coverage",
        "DS_Store",
        "pytest_cache",
        "node_modules",
        "tox",
        "mypy_cache",
        "ruff_cache",
    ],
)
def test_mode4_each_denylist_pattern_fires(tmp_path: Path, staged_path: str) -> None:
    """6e: every deny-list pattern fires Mode 4 when staged."""
    git = _state(staged=[{"path": staged_path, "status": "A"}])
    report = patch_completeness.check(git, tmp_path, set())
    finding = next(f for f in report.findings if f.mode == "generated_artifact_staged")
    assert finding.severity == "block"
    assert staged_path in finding.files
    assert "git restore --staged" in finding.recommendation


def test_mode4_does_not_fire_when_artifact_is_untracked(tmp_path: Path) -> None:
    """7a: generated artifact in untracked (not staged) → NO Mode 4 finding."""
    git = _state(untracked=["scripts/foo/__pycache__/bar.pyc"])
    report = patch_completeness.check(git, tmp_path, set())
    assert not any(f.mode == "generated_artifact_staged" for f in report.findings)


# ──────────────────────────────  Mode 5: unstaged_dirty_state  ──────────────────────────────


def test_mode5_fires_info_severity_regardless_of_touched_set(tmp_path: Path) -> None:
    """6f: unstaged_modified always emits a Mode 5 INFO finding."""
    _write(tmp_path, "lib/edited.py", "x = 1\n")
    git = _state(unstaged_modified=[{"path": "lib/edited.py", "status": "M"}])

    report_in = patch_completeness.check(git, tmp_path, {"lib/edited.py"})
    report_out = patch_completeness.check(git, tmp_path, set())

    for report in (report_in, report_out):
        finding = next(f for f in report.findings if f.mode == "unstaged_dirty_state")
        assert finding.severity == "info"
        assert "lib/edited.py" in finding.files


def test_mode5_status_is_pass_when_only_info_findings(tmp_path: Path) -> None:
    """Info-only findings keep status at 'pass' — F002 never blocks on Mode 5 alone."""
    _write(tmp_path, "lib/edited.py", "x = 1\n")
    git = _state(unstaged_modified=[{"path": "lib/edited.py", "status": "M"}])
    report = patch_completeness.check(git, tmp_path, set())
    assert report.status == "pass"


def test_unrelated_dirty_state_surfaces_for_f003_to_decide(tmp_path: Path) -> None:
    """User-requested: dirty file outside touched_files surfaces in the report so F003 can promote.

    F002 still emits severity='info' per locked spec — promotion to block (when no
    --unrelated-dirty-state-note is supplied) is F003's responsibility. This test pins
    the contract: F002 makes the data visible; F003 enforces.
    """
    _write(tmp_path, "lib/parallel_wip.py", "wip = True\n")
    _write(tmp_path, "lib/intended.py", "intended = True\n")
    git = _state(
        unstaged_modified=[
            {"path": "lib/parallel_wip.py", "status": "M"},
            {"path": "lib/intended.py", "status": "M"},
        ]
    )
    touched = {"lib/intended.py"}  # parallel_wip.py is "unrelated"

    report = patch_completeness.check(git, tmp_path, touched)
    finding = next(f for f in report.findings if f.mode == "unstaged_dirty_state")
    assert finding.severity == "info"
    assert {"lib/parallel_wip.py", "lib/intended.py"} <= set(finding.files)
    # F002 lists ALL unstaged_modified files (touched-set agnostic). F003 reads
    # touched_files separately to compute which subset to escalate to block.


# ──────────────────────────────  clean / allowed matrix  ──────────────────────────────


def test_third_party_and_stdlib_imports_silently_skipped(tmp_path: Path) -> None:
    """7d: imports that don't resolve to in-repo files are silently skipped."""
    _write(
        tmp_path,
        "tests/test_third_party.py",
        "import json\nimport pytest\nfrom collections import abc\n",
    )
    git = _state()  # nothing dirty
    report = patch_completeness.check(git, tmp_path, {"tests/test_third_party.py"})
    assert report.status == "pass"
    assert report.findings == []


def test_imports_from_non_touched_non_staged_file_not_analyzed(tmp_path: Path) -> None:
    """7e: touched-set narrowing — files outside the read surface are not parsed."""
    # File outside touched_files / staged / unstaged_modified — even with broken
    # imports (which would resolve to in-repo paths), F002 must NOT analyze it.
    _write(tmp_path, "scripts/needs.py", "y = 2\n")
    _write(
        tmp_path,
        "scripts/outside.py",  # syntactically valid but imports something untracked
        "from scripts.needs import y\n",
    )
    git = _state(untracked=["scripts/needs.py"])
    # touched_files does NOT include outside.py, and it's not staged or unstaged.
    report = patch_completeness.check(git, tmp_path, set())
    assert not any(
        f.mode in ("test_imports_uncommitted", "source_imports_uncommitted")
        for f in report.findings
    )


def test_intentionally_untracked_evidence_no_imports_no_finding(tmp_path: Path) -> None:
    """7b: untracked evidence/docs file that nothing imports → no finding."""
    _write(tmp_path, "evidence/scratch-notes.md", "# notes\n")
    git = _state(untracked=["evidence/scratch-notes.md"])
    report = patch_completeness.check(git, tmp_path, set())
    assert report.findings == []
    assert report.status == "pass"


def test_malformed_python_in_touched_set_does_not_raise(tmp_path: Path) -> None:
    """A SyntaxError in the read surface should be silently skipped (defensive)."""
    _write(tmp_path, "scripts/bad.py", "this is not valid python ::: $$$\n")
    git = _state(unstaged_modified=[{"path": "scripts/bad.py", "status": "M"}])
    report = patch_completeness.check(git, tmp_path, {"scripts/bad.py"})
    # Mode 5 still fires (file is in unstaged_modified). Modes 1/2 should not raise.
    assert any(f.mode == "unstaged_dirty_state" for f in report.findings)


# ──────────────────────────────  mixed: all 5 modes simultaneously  ──────────────────────────────


def test_mixed_all_five_modes_simultaneously(tmp_path: Path) -> None:
    """Acceptance (8): mixed fixture with all 5 modes firing.

    - Mode 1: test imports an untracked module
    - Mode 2: source imports an unstaged_modified module
    - Mode 3: a test file is itself untracked
    - Mode 4: a generated artifact is staged
    - Mode 5: any unstaged_modified file present (covered by Mode 2's setup)
    """
    _write(tmp_path, "lib/needed_by_test.py", "a = 1\n")
    _write(tmp_path, "tests/test_imports_a.py", "from lib.needed_by_test import a\n")

    _write(tmp_path, "lib/dirty_helper.py", "b = 2\n")
    _write(tmp_path, "lib/main.py", "from lib.dirty_helper import b\n")

    _write(tmp_path, "tests/test_brand_new.py", "def test_z(): assert True\n")

    git = _state(
        staged=[{"path": "scripts/.DS_Store", "status": "A"}],
        unstaged_modified=[{"path": "lib/dirty_helper.py", "status": "M"}],
        untracked=["lib/needed_by_test.py", "tests/test_brand_new.py"],
    )
    touched = {"tests/test_imports_a.py", "lib/main.py"}

    report = patch_completeness.check(git, tmp_path, touched)
    modes = sorted(f.mode for f in report.findings)
    assert modes == sorted(
        [
            "test_imports_uncommitted",
            "source_imports_uncommitted",
            "test_file_untracked",
            "generated_artifact_staged",
            "unstaged_dirty_state",
        ]
    )
    assert report.status == "fail"  # at least one block-severity finding

    # Files union is deduplicated across findings.
    assert len(report.files) == len(set(report.files))


# ──────────────────────────────  purity contract  ──────────────────────────────


def test_module_does_not_invoke_subprocess_or_logging() -> None:
    """Acceptance (2): pure function — no subprocess, no logging, no print."""
    src = Path(patch_completeness.__file__).read_text()
    forbidden = ["subprocess.run", "subprocess.Popen", "logging.getLogger", "print("]
    for needle in forbidden:
        assert needle not in src, f"patch_completeness.py must not contain {needle!r}"


def test_mode_and_severity_are_literal_typed() -> None:
    """Acceptance (5): mode + severity are Literal types in source."""
    src = Path(patch_completeness.__file__).read_text()
    assert "Literal[" in src
    assert "test_imports_uncommitted" in src
    assert "source_imports_uncommitted" in src
    assert "test_file_untracked" in src
    assert "generated_artifact_staged" in src
    assert "unstaged_dirty_state" in src
    assert "'info'" in src or '"info"' in src
    assert "'warn'" in src or '"warn"' in src
    assert "'block'" in src or '"block"' in src


def test_denylist_patterns_each_have_source_comment() -> None:
    """Acceptance (4): _GENERATED_ARTIFACT_PATTERNS each carry a `# source:` comment."""
    src = Path(patch_completeness.__file__).read_text()
    # Each pattern in the deny-list block should be preceded by a `# source:` comment.
    # We check by counting: the frozenset has N patterns, there should be >= N source comments.
    assert "_GENERATED_ARTIFACT_PATTERNS" in src
    assert "frozenset" in src
    source_comment_count = src.count("# source:")
    assert source_comment_count >= 10, (
        f"expected at least one '# source:' comment per deny-list pattern; found {source_comment_count}"
    )


# ──────────────────────────────  status mapping edge cases  ──────────────────────────────


def test_status_mapping_warn_present_no_block(tmp_path: Path) -> None:
    """If the analyzer surface includes warn-tier findings without block, status='warn'.

    Future modes may emit warn severity. We don't have a Mode that natively emits
    warn yet, but the mapping must be correct in the abstract — verified by
    constructing a report directly.
    """
    report = CompletenessReport(
        schema_version="1.0",
        status="pass",  # placeholder — recomputed below
        findings=[
            Finding(
                mode="unstaged_dirty_state",
                files=["x.py"],
                reason="placeholder",
                severity="warn",
                recommendation="placeholder",
            )
        ],
        files=["x.py"],
    )
    assert patch_completeness.compute_status(report.findings) == "warn"


def test_status_mapping_block_takes_precedence() -> None:
    findings = [
        Finding(
            mode="unstaged_dirty_state",
            files=["a.py"],
            reason="r",
            severity="info",
            recommendation="r",
        ),
        Finding(
            mode="generated_artifact_staged",
            files=["b.pyc"],
            reason="r",
            severity="block",
            recommendation="r",
        ),
    ]
    assert patch_completeness.compute_status(findings) == "fail"


def test_finding_class_serializes_via_asdict() -> None:
    """Stdlib dataclass — asdict should produce a JSON-serializable dict."""
    f = Finding(
        mode="test_file_untracked",
        files=["tests/test_x.py"],
        reason="r",
        severity="block",
        recommendation="Run: git add tests/test_x.py",
    )
    blob = json.dumps(f.to_dict())
    rt = Finding.from_dict(json.loads(blob))
    assert rt == f
