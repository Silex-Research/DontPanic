"""Plan 2026-06-08-004 F005 — coverage.baseline parity across producer branches.

build_view_state must attach the build_baseline coverage block as
coverage["baseline"] on BOTH branches (architecture.json present and absent),
and the two blocks must be VALUE-IDENTICAL — deep equality of the full block,
not merely the same key set. Both branches run against the SAME repo tree:
the absent branch points architecture_path at a missing file so the baseline
scan inputs are byte-identical.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import architecture_view_state as avs  # noqa: E402

BASELINE_KEYS = {
    "rollup",
    "per_language",
    "per_evidence_type",
    "scan_truncated",
    "notes",
    "unrecognized_extensions",
}


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "App").mkdir()
    (root / "App" / "Main.swift").write_text("import UIKit\n")
    (root / "Dockerfile").write_text("")
    # a minimal-but-parseable architecture.json so the present branch is real
    arch = {
        "schema_version": "1.0",
        "generated_at": "2026-06-11T00:00:00Z",
        "source_fingerprint": {
            "algo": "sha256",
            "files_count": 1,
            "file_hashes_root": "a" * 64,
            "file_hashes": {},
            "computed_at": "2026-06-11T00:00:00Z",
        },
        "modules": [
            {
                "path": "App/main.py",
                "name": "app.main",
                "public_symbols": [],
                "imports": [],
                "summary": "entry",
            }
        ],
        "schemas": [],
        "plans": [],
    }
    target = root / "docs" / "architecture" / "architecture.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(arch, sort_keys=True, indent=2) + "\n")
    return root


def _both_branches(root: Path) -> tuple[dict, dict]:
    present = avs.build_view_state(avs.load_inputs(repo_root=root), repo_root=root)
    absent_inputs = avs.load_inputs(
        repo_root=root, architecture_path=root / "does-not-exist.json"
    )
    assert absent_inputs.architecture is None
    absent = avs.build_view_state(absent_inputs, repo_root=root)
    return present, absent


def test_present_branch_carries_coverage_baseline(tmp_path: Path):
    present, _ = _both_branches(_make_repo(tmp_path))
    assert "baseline" in present["coverage"], (
        "present-architecture branch must attach coverage['baseline']"
    )
    assert BASELINE_KEYS <= set(present["coverage"]["baseline"].keys())


def test_baseline_blocks_are_value_identical_across_branches(tmp_path: Path):
    present, absent = _both_branches(_make_repo(tmp_path))
    pb = present["coverage"]["baseline"]
    ab = absent["coverage"]["baseline"]
    # deep equality of the FULL block — divergent values on the same keys fail
    assert pb == ab, (
        "coverage.baseline must be value-identical across producer branches:\n"
        f"present={json.dumps(pb, sort_keys=True)[:400]}\n"
        f"absent={json.dumps(ab, sort_keys=True)[:400]}"
    )
    # and explicitly per contract field, so a failure names the divergent field
    for key in BASELINE_KEYS:
        assert pb[key] == ab[key], f"coverage.baseline.{key} diverges between branches"


def test_absent_branch_behavior_unchanged(tmp_path: Path):
    # regression guard for the 'no change to absent branch' clause
    _, absent = _both_branches(_make_repo(tmp_path))
    assert absent["freshness"]["state"] == "absent"
    assert "baseline" in absent["coverage"]
    assert any(
        w.get("code") == "architecture_missing"
        for w in absent.get("validation_warnings", [])
    )
