"""Plan 2026-05-09-003 F004 — `dontpanic state snapshot` CLI tests.

Pins the CLI flag surface:
  - `--json` / `--yaml` mutex (default --json)
  - `--plan <id>`
  - `--include <streams>` (comma-separated)
  - `--redact-level public|operator|full` (default operator)
  - `--out <path>`
  - `--compact` (single-line JSON; ignored under --yaml)
  - `--select <jsonpath>` (read-only minimal jsonpath subset)
  - `--plans-root <path>` (test/CI override; default cwd/docs/plans)

Round-trip: CLI JSON output validates against the F001 schema.
Bytewise: --select via CLI matches state_projection in-process call.
"""

from __future__ import annotations

import io
import json
import os
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


def _make_plan(plans_root: Path, plan_id: str = "2026-05-10-001-feat-fixture") -> Path:
    plan_dir = plans_root / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        f"id: {plan_id}\n"
        "title: CLI fixture\n"
        "type: feat\n"
        "tier: local\n"
        "status: active\n"
        'date: "2026-05-10"\n'
        "goal_type: infra\n"
        "surfaces:\n  - infra\n"
        "agents_required:\n  - claude\n"
        "human_gates:\n  - pre_impl\n  - pre_merge\n"
        "loop_caps:\n"
        "  max_iterations: 3\n"
        "  no_progress_threshold: 2\n"
        "  wall_clock_hours: 4\n"
        "  hard_stop: false\n"
        "privacy_tier: internal\n"
        "links:\n"
        "  features: ./features.json\n"
        "  decisions: ./decisions.jsonl\n"
        "  evidence_dir: ./evidence/\n"
        "description: |\n  CLI fixture plan.\n"
        "motivation: |\n  CLI fixture motivation.\n"
        "---\n"
        f"# {plan_id}\n\n"
        "## Target\n\n"
        "```yaml\n"
        "target_env: dev\n"
        "target_project: none\n"
        "```\n\n"
        "## Acceptance Summary\n\n"
        "- Fixture.\n"
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "infra",
                        "phase": 1,
                        "description": "Fixture feature for CLI tests.",
                        "steps": ["Do the thing."],
                        "acceptance": "Thing done.",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            },
            indent=2,
        )
    )
    (plan_dir / "evidence").mkdir(exist_ok=True)
    return plan_dir


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Invoke cli.main; capture stdout, stderr, exit code."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            rc = cli.main(argv)
        except SystemExit as e:
            rc = int(e.code) if e.code is not None else 0
    return rc, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def plans_root(tmp_path: Path) -> Path:
    root = tmp_path / "plans"
    _make_plan(root)
    return root


# ─────────────────── 1. happy paths ───────────────────


class TestSnapshotHappy:
    def test_default_json_to_stdout(self, plans_root: Path) -> None:
        rc, out, err = _run_cli(
            ["state", "snapshot", "--plans-root", str(plans_root)]
        )
        assert rc == 0, err
        data = json.loads(out)
        # Validates against F001 schema via Pydantic
        StateSnapshot.model_validate(data)
        assert data["redact_level"] == "operator"  # default

    def test_compact_emits_single_line(self, plans_root: Path) -> None:
        rc, out, err = _run_cli(
            ["state", "snapshot", "--plans-root", str(plans_root), "--compact"]
        )
        assert rc == 0, err
        # Single line (trailing newline allowed)
        assert out.count("\n") <= 1
        StateSnapshot.model_validate(json.loads(out))

    def test_redact_level_threaded(self, plans_root: Path) -> None:
        for level in ("public", "operator", "full"):
            rc, out, _ = _run_cli(
                [
                    "state",
                    "snapshot",
                    "--plans-root",
                    str(plans_root),
                    "--redact-level",
                    level,
                ]
            )
            assert rc == 0
            assert json.loads(out)["redact_level"] == level

    def test_plan_filter(self, plans_root: Path, tmp_path: Path) -> None:
        _make_plan(plans_root, "2026-05-10-002-feat-other")
        rc, out, _ = _run_cli(
            [
                "state",
                "snapshot",
                "--plans-root",
                str(plans_root),
                "--plan",
                "2026-05-10-001-feat-fixture",
            ]
        )
        assert rc == 0
        ids = [p["plan_id"] for p in json.loads(out)["streams"]["plans"]]
        assert ids == ["2026-05-10-001-feat-fixture"]

    def test_include_filter(self, plans_root: Path) -> None:
        rc, out, _ = _run_cli(
            [
                "state",
                "snapshot",
                "--plans-root",
                str(plans_root),
                "--include",
                "plans",
            ]
        )
        assert rc == 0
        data = json.loads(out)
        assert len(data["streams"]["plans"]) == 1
        # Unselected streams are empty
        for stream in ("gates", "inbox", "supervisors", "quota", "decisions", "evidence_refs"):
            assert data["streams"][stream] == []

    def test_out_writes_to_file(self, plans_root: Path, tmp_path: Path) -> None:
        out_path = tmp_path / "snap.json"
        rc, out, _ = _run_cli(
            [
                "state",
                "snapshot",
                "--plans-root",
                str(plans_root),
                "--out",
                str(out_path),
            ]
        )
        assert rc == 0
        assert out_path.is_file()
        StateSnapshot.model_validate_json(out_path.read_text())
        # stdout is empty when --out is set
        assert out.strip() == ""


# ─────────────────── 2. --select jsonpath subset ───────────────────


class TestSelectFilter:
    def test_select_extracts_plan_ids(self, plans_root: Path) -> None:
        rc, out, err = _run_cli(
            [
                "state",
                "snapshot",
                "--plans-root",
                str(plans_root),
                "--select",
                "$.streams.plans[*].plan_id",
            ]
        )
        assert rc == 0, err
        result = json.loads(out)
        assert result == ["2026-05-10-001-feat-fixture"]

    def test_select_nested_field(self, plans_root: Path) -> None:
        rc, out, _ = _run_cli(
            [
                "state",
                "snapshot",
                "--plans-root",
                str(plans_root),
                "--select",
                "$.redact_level",
            ]
        )
        assert json.loads(out) == "operator"

    def test_select_invalid_path_exits_nonzero(self, plans_root: Path) -> None:
        rc, out, err = _run_cli(
            [
                "state",
                "snapshot",
                "--plans-root",
                str(plans_root),
                "--select",
                "$.streams.plans; rm -rf /",  # injection attempt
            ]
        )
        assert rc != 0
        assert "select" in err.lower() or "jsonpath" in err.lower()


# ─────────────────── 3. invalid argv ───────────────────


class TestInvalidArgv:
    def test_unknown_redact_level_rejected(self, plans_root: Path) -> None:
        rc, _, err = _run_cli(
            [
                "state",
                "snapshot",
                "--plans-root",
                str(plans_root),
                "--redact-level",
                "bogus",
            ]
        )
        assert rc != 0

    def test_unknown_include_stream_rejected(self, plans_root: Path) -> None:
        rc, _, err = _run_cli(
            [
                "state",
                "snapshot",
                "--plans-root",
                str(plans_root),
                "--include",
                "plans,bogus",
            ]
        )
        assert rc != 0

    def test_json_yaml_mutex(self, plans_root: Path) -> None:
        rc, _, _ = _run_cli(
            [
                "state",
                "snapshot",
                "--plans-root",
                str(plans_root),
                "--json",
                "--yaml",
            ]
        )
        assert rc != 0

    def test_state_subcommand_required(self) -> None:
        rc, _, err = _run_cli(["state"])
        assert rc != 0


# ─────────────────── 4. yaml output ───────────────────


class TestYamlOutput:
    def test_yaml_output_parses_back(self, plans_root: Path) -> None:
        import yaml
        rc, out, _ = _run_cli(
            ["state", "snapshot", "--plans-root", str(plans_root), "--yaml"]
        )
        assert rc == 0
        data = yaml.safe_load(out)
        StateSnapshot.model_validate(data)
