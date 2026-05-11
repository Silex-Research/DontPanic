"""Plan 2026-05-09-003 F007 — `dontpanic state export-dashboard` tests.

Pins:
  - Subcommand exists and accepts --out / --plans-root / --redact-level
  - Writes one JSON file per F001 stream (7 files) + state-snapshot.json + manifest.json
  - Each per-stream file is a JSON array
  - state-snapshot.json validates against the F001 schema
  - manifest.json enumerates streams with file paths + counts
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "claude" / "shared" / "schemas" / "v1.0" / "models"))

from dontpanic_orchestrate import cli  # noqa: E402
from state_snapshot_model import StateSnapshot  # noqa: E402


def _run(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            rc = cli.main(argv)
        except SystemExit as e:
            rc = int(e.code) if e.code is not None else 0
    return rc, stdout.getvalue(), stderr.getvalue()


def _make_plan(plans_root: Path) -> None:
    plan_dir = plans_root / "2026-05-10-001-feat-export-fixture"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        "id: 2026-05-10-001-feat-export-fixture\n"
        "title: Export fixture\n"
        "type: feat\ntier: local\nstatus: active\n"
        'date: "2026-05-10"\n'
        "goal_type: infra\n"
        "surfaces:\n  - infra\n"
        "agents_required:\n  - claude\n"
        "human_gates:\n  - pre_impl\n"
        "loop_caps:\n  max_iterations: 3\n  no_progress_threshold: 2\n  wall_clock_hours: 4\n  hard_stop: false\n"
        "privacy_tier: internal\n"
        "links:\n  features: ./features.json\n  decisions: ./decisions.jsonl\n  evidence_dir: ./evidence/\n"
        "description: |\n  Export fixture.\n"
        "motivation: |\n  Export fixture.\n"
        "---\n"
        "# fixture\n\n## Target\n\n```yaml\ntarget_env: dev\ntarget_project: none\n```\n\n## Acceptance Summary\n\n- x\n"
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": "2026-05-10-001-feat-export-fixture",
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "infra",
                        "phase": 1,
                        "description": "Fixture feature for F007.",
                        "steps": ["Do."],
                        "acceptance": "Done.",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            },
            indent=2,
        )
    )
    (plan_dir / "evidence").mkdir(exist_ok=True)


@pytest.fixture
def plans_root(tmp_path: Path) -> Path:
    root = tmp_path / "plans"
    _make_plan(root)
    return root


# ─────────────────── 1. happy path ───────────────────


class TestExportHappy:
    def test_writes_all_files(self, plans_root: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "export"
        rc, _, err = _run(
            [
                "state",
                "export-dashboard",
                "--out",
                str(out_dir),
                "--plans-root",
                str(plans_root),
            ]
        )
        assert rc == 0, err
        # state-snapshot.json + manifest.json + 7 per-stream
        assert (out_dir / "state-snapshot.json").is_file()
        assert (out_dir / "manifest.json").is_file()
        for s in (
            "plans",
            "gates",
            "inbox",
            "supervisors",
            "quota",
            "decisions",
            "evidence_refs",
        ):
            assert (out_dir / f"{s}.json").is_file(), f"missing {s}.json"

    def test_snapshot_validates(self, plans_root: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "export"
        _run(
            [
                "state",
                "export-dashboard",
                "--out",
                str(out_dir),
                "--plans-root",
                str(plans_root),
            ]
        )
        text = (out_dir / "state-snapshot.json").read_text()
        StateSnapshot.model_validate_json(text)

    def test_per_stream_files_are_arrays(self, plans_root: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "export"
        _run(
            [
                "state",
                "export-dashboard",
                "--out",
                str(out_dir),
                "--plans-root",
                str(plans_root),
            ]
        )
        for s in (
            "plans",
            "gates",
            "inbox",
            "supervisors",
            "quota",
            "decisions",
            "evidence_refs",
        ):
            data = json.loads((out_dir / f"{s}.json").read_text())
            assert isinstance(data, list), f"{s}.json should be a JSON array"

    def test_manifest_enumerates_streams(self, plans_root: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "export"
        _run(
            [
                "state",
                "export-dashboard",
                "--out",
                str(out_dir),
                "--plans-root",
                str(plans_root),
            ]
        )
        manifest = json.loads((out_dir / "manifest.json").read_text())
        names = {s["name"] for s in manifest["streams"]}
        assert names == {
            "plans",
            "gates",
            "inbox",
            "supervisors",
            "quota",
            "decisions",
            "evidence_refs",
        }
        # plans count = 1 (the fixture)
        plans_entry = next(s for s in manifest["streams"] if s["name"] == "plans")
        assert plans_entry["count"] == 1
        assert plans_entry["file"] == "plans.json"

    def test_plans_json_has_fixture_plan(self, plans_root: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "export"
        _run(
            [
                "state",
                "export-dashboard",
                "--out",
                str(out_dir),
                "--plans-root",
                str(plans_root),
            ]
        )
        plans = json.loads((out_dir / "plans.json").read_text())
        assert len(plans) == 1
        assert plans[0]["plan_id"] == "2026-05-10-001-feat-export-fixture"


# ─────────────────── 2. argv validation ───────────────────


class TestExportArgv:
    def test_missing_out_flag_fails(self, plans_root: Path) -> None:
        rc, _, _ = _run(
            ["state", "export-dashboard", "--plans-root", str(plans_root)]
        )
        assert rc != 0

    def test_bad_redact_level_fails(self, plans_root: Path, tmp_path: Path) -> None:
        rc, _, _ = _run(
            [
                "state",
                "export-dashboard",
                "--out",
                str(tmp_path / "x"),
                "--plans-root",
                str(plans_root),
                "--redact-level",
                "bogus",
            ]
        )
        assert rc != 0


# ─────────────────── 3. local-first invariant ───────────────────


class TestLocalFirstInvariant:
    def test_existing_dashboard_core_js_unchanged(self) -> None:
        """The existing static dashboard's core.js MUST still document
        'Local-first: reads state from JSON files, no Firebase dependency.'
        F007 does not alter the dashboard runtime."""
        core_js = ROOT / "dashboard" / "core.js"
        if not core_js.is_file():
            pytest.skip(f"{core_js} not present; static dashboard not bundled")
        text = core_js.read_text()
        assert "Local-first" in text or "no Firebase dependency" in text


# ─────────────────── 4. dashboard README ───────────────────


class TestDashboardReadme:
    README = ROOT / "dashboard" / "README.md"

    def test_readme_exists(self) -> None:
        assert self.README.is_file()

    def test_readme_documents_three_deployment_shapes(self) -> None:
        text = self.README.read_text()
        # python http.server, Firebase Hosting, any static host
        assert "python -m http.server" in text or "python3 -m http.server" in text
        assert "Firebase Hosting" in text
        # Plus a third option (file://, GitHub Pages, nginx, Vercel, S3)
        assert any(
            opt in text
            for opt in ("file://", "GitHub Pages", "nginx", "Vercel", "S3", "static host")
        )

    def test_readme_marks_firebase_optional(self) -> None:
        text = self.README.read_text()
        text_lower = text.lower()
        assert "optional" in text_lower
        assert "firebase" in text_lower
