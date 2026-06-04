"""Plan 2026-06-02-002 F003 — patch-completeness surfaces an untracked
IMPLEMENTATION module imported by a changed/added file (the F007 sizing_gate.py
miss), while NOT reporting unrelated untracked generated/runtime output.

Root cause of the F007 miss: ``_resolve_module`` builds repo-relative candidate
paths from the dotted module name (e.g. ``dontpanic_orchestrate/plan_review/
sizing_gate.py``), but the package lives under a source root (``scripts/``) on
PYTHONPATH, so the real git path is ``scripts/dontpanic_orchestrate/.../
sizing_gate.py``. The candidate never equals the dirty path → a source-root-
prefixed module imported by a changed file is silently un-surfaced.

Acceptance coverage map (features.json F003):
  (1)/(2) untracked module imported by a CHANGED file is surfaced; an untracked
          test + the untracked module it imports are BOTH surfaced
  (3)/(4) an unrelated untracked runtime file (outside touched/imported set) is
          NOT reported

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f003_patch_completeness_untracked_module.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import patch_completeness as pc  # noqa: E402


def _write(root: Path, rel: str, body: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _git_state(*, untracked=None, unstaged=None, staged=None) -> dict:
    return {
        "untracked": list(untracked or []),
        "unstaged_modified": [{"path": p} for p in (unstaged or [])],
        "staged": [{"path": p} for p in (staged or [])],
    }


def _module_findings(report) -> dict[str, set[str]]:
    """mode -> set(files) for the import-detection modes."""
    return {
        f.mode: set(f.files)
        for f in report.findings
        if f.mode in ("source_imports_uncommitted", "test_imports_uncommitted")
    }


# ──────────────  (1)/(2) source-root-prefixed module surfaced  ──────────────


def test_untracked_module_imported_by_changed_source_is_surfaced() -> None:
    """A CHANGED (modified) source file imports an untracked module that lives
    under a source root (scripts/). The module must be surfaced even though the
    dotted import omits the scripts/ prefix."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        module_rel = "scripts/dontpanic_orchestrate/plan_review/sizing_gate.py"
        consumer_rel = "scripts/dontpanic_orchestrate/plan_review/report.py"
        _write(root, module_rel, "def evaluate_feature():\n    return None\n")
        _write(
            root,
            consumer_rel,
            "from dontpanic_orchestrate.plan_review.sizing_gate import evaluate_feature\n",
        )
        git_state = _git_state(untracked=[module_rel], unstaged=[consumer_rel])
        report = pc.check(git_state, root, touched_files={consumer_rel})

        mods = _module_findings(report)
        assert module_rel in mods.get("source_imports_uncommitted", set()), (
            f"untracked source-root module must be surfaced; got {mods}"
        )
        assert report.status == "fail"


def test_untracked_test_and_imported_untracked_module_both_surfaced() -> None:
    """The F007 shape: a dispatch adds an untracked test AND the untracked
    implementation module it imports. BOTH must be surfaced — the test via
    test_file_untracked, the module via test_imports_uncommitted."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        module_rel = "scripts/dontpanic_orchestrate/plan_review/sizing_gate.py"
        test_rel = "scripts/dontpanic_orchestrate/plan_review/tests/test_sizing_gate.py"
        _write(root, module_rel, "VALUE = 1\n")
        _write(
            root,
            test_rel,
            "from dontpanic_orchestrate.plan_review.sizing_gate import VALUE\n\n"
            "def test_value():\n    assert VALUE == 1\n",
        )
        # The dispatch added the test (in touched set); the module is untracked
        # and NOT in the touched set — it must still be surfaced via the import.
        git_state = _git_state(untracked=[module_rel, test_rel])
        report = pc.check(git_state, root, touched_files={test_rel})

        files_by_mode = {f.mode: set(f.files) for f in report.findings}
        assert test_rel in files_by_mode.get("test_file_untracked", set()), (
            f"untracked test file must be surfaced; got {files_by_mode}"
        )
        assert module_rel in files_by_mode.get("test_imports_uncommitted", set()), (
            f"untracked module imported by the added test must be surfaced; "
            f"got {files_by_mode}"
        )


# ──────────────  (3)/(4) unrelated untracked runtime file NOT flagged  ──────────────


def test_unrelated_untracked_runtime_file_not_flagged() -> None:
    """An unrelated untracked runtime artifact (not imported by any surface
    file, not a test, not staged) must NOT be reported as a completeness
    blocker — the gate stays scoped to the touched/imported set, not a blanket
    untracked scan (the standing onboarding-v0 noise)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        consumer_rel = "scripts/dontpanic_orchestrate/plan_review/report.py"
        # consumer imports nothing dirty.
        _write(root, consumer_rel, "import json\n")
        runtime_json = "docs/plans/2026-05-30-001/evidence/git-state-0-implementer.json"
        runtime_py = "scripts/dontpanic_orchestrate/_unrelated_runtime_dump.py"
        _write(root, runtime_json, "{}\n")
        _write(root, runtime_py, "X = 1\n")
        git_state = _git_state(
            untracked=[runtime_json, runtime_py], unstaged=[consumer_rel]
        )
        report = pc.check(git_state, root, touched_files={consumer_rel})

        flagged = {f for fnd in report.findings for f in fnd.files}
        assert runtime_json not in flagged, f"unrelated runtime json flagged: {flagged}"
        assert runtime_py not in flagged, f"unrelated runtime py flagged: {flagged}"
        assert report.status == "pass", report.to_dict()


def test_suffix_match_does_not_overreach_on_single_name_import() -> None:
    """Guard: a bare ``import json``-style single-segment name must not
    suffix-match an unrelated untracked ``json.py`` deep in the tree (avoids
    false positives from the source-root suffix match)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        consumer_rel = "scripts/dontpanic_orchestrate/plan_review/report.py"
        _write(root, consumer_rel, "import sizing_gate\n")  # single-segment
        # An unrelated untracked file whose tail is sizing_gate.py but lives in
        # a different package — must NOT be matched on a single-name import.
        unrelated = "scripts/some_other_pkg/sizing_gate.py"
        _write(root, unrelated, "Y = 2\n")
        git_state = _git_state(untracked=[unrelated], unstaged=[consumer_rel])
        report = pc.check(git_state, root, touched_files={consumer_rel})

        flagged = {f for fnd in report.findings for f in fnd.files}
        assert unrelated not in flagged, (
            f"single-segment import must not suffix-match unrelated file: {flagged}"
        )


def test_nonimportable_mirror_prefix_does_not_match() -> None:
    """Codex batched-audit i0 finding (D006): a bare endswith suffix test would
    match an unrelated untracked MIRROR whose prefix is NOT an importable source
    root — e.g. docs/generated/dontpanic_orchestrate/plan_review/sizing_gate.py
    shares the imported candidate's tail. The prefix must be an ANCESTOR of the
    importer (scripts/...) to match; docs/generated is not, so the mirror is NOT
    flagged (acceptance #3/#4: no flagging of unrelated untracked output)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        consumer_rel = "scripts/dontpanic_orchestrate/plan_review/report.py"
        real_module = "scripts/dontpanic_orchestrate/plan_review/sizing_gate.py"
        mirror = "docs/generated/dontpanic_orchestrate/plan_review/sizing_gate.py"
        _write(root, consumer_rel,
               "from dontpanic_orchestrate.plan_review.sizing_gate import evaluate_feature\n")
        _write(root, real_module, "def evaluate_feature():\n    return None\n")
        _write(root, mirror, "def evaluate_feature():\n    return None\n")
        # Only the non-importable mirror is dirty; the real module is committed.
        git_state = _git_state(untracked=[mirror], unstaged=[consumer_rel])
        report = pc.check(git_state, root, touched_files={consumer_rel})

        flagged = {f for fnd in report.findings for f in fnd.files}
        assert mirror not in flagged, (
            f"non-importable mirror prefix must NOT match the import: {flagged}"
        )
        assert report.status == "pass", report.to_dict()
