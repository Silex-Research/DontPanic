"""Plan 2026-05-09-003 F005 — MCP tools `state_snapshot` + `state_stream` tests.

Pins:
  - state_snapshot tool registered, returns same envelope as F004 CLI
  - state_snapshot caps redact_level at `operator` regardless of caller
    (full is local-CLI-only)
  - state_snapshot honors select + compact params (parity with CLI)
  - state_stream returns inbox-event delta given `since` cursor
  - mutation tools (dispatch, approve_gate) carry approval metadata
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "claude" / "shared" / "schemas" / "v1.0" / "models"))

from dontpanic_orchestrate import mcp_server, projects_registry  # noqa: E402
from state_snapshot_model import StateSnapshot  # noqa: E402


def _make_plan(plans_root: Path, plan_id: str = "2026-05-10-001-feat-fixture") -> Path:
    plan_dir = plans_root / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        f"id: {plan_id}\n"
        "title: MCP fixture\n"
        "type: feat\n"
        "tier: local\n"
        "status: active\n"
        'date: "2026-05-10"\n'
        "goal_type: infra\n"
        "surfaces:\n  - infra\n"
        "agents_required:\n  - claude\n"
        "human_gates:\n  - pre_impl\n  - pre_merge\n"
        "loop_caps:\n  max_iterations: 3\n  no_progress_threshold: 2\n  wall_clock_hours: 4\n  hard_stop: false\n"
        "privacy_tier: internal\n"
        "links:\n  features: ./features.json\n  decisions: ./decisions.jsonl\n  evidence_dir: ./evidence/\n"
        "description: |\n  MCP fixture.\n"
        "motivation: |\n  MCP fixture.\n"
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
                        "description": "Fixture feature for MCP tests.",
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
    return plan_dir


@pytest.fixture
def registered_project(tmp_path: Path, monkeypatch):
    """Register a project so MCP's strict path resolver accepts the plan dir."""
    project_path = tmp_path / "proj"
    (project_path / "docs" / "plans").mkdir(parents=True)
    _make_plan(project_path / "docs" / "plans")

    # Redirect projects.json to a tmp location.
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path / "dontpanic_home"))
    reg = projects_registry.Registry(
        projects=[
            projects_registry.ProjectEntry(
                name="test-proj",
                path=str(project_path),
                created_at="2026-05-10T00:00:00Z",
            )
        ]
    )
    projects_registry.save_registry(reg)
    yield project_path


# ─────────────────── 1. state_snapshot tool ───────────────────


class TestStateSnapshotTool:
    def test_tool_registered(self) -> None:
        assert "state_snapshot" in mcp_server.list_tool_names()

    def test_returns_valid_envelope(self, registered_project: Path) -> None:
        result = mcp_server.dispatch_tool("state_snapshot", {})
        # Validates against F001 schema
        StateSnapshot.model_validate(result)
        # Default redact level is operator
        assert result["redact_level"] == "operator"

    def test_caps_redact_level_at_operator(self, registered_project: Path) -> None:
        # full is forbidden over MCP — silently capped to operator
        result = mcp_server.dispatch_tool(
            "state_snapshot", {"redact_level": "full"}
        )
        assert result["redact_level"] == "operator"

    def test_accepts_public_redact_level(self, registered_project: Path) -> None:
        result = mcp_server.dispatch_tool(
            "state_snapshot", {"redact_level": "public"}
        )
        assert result["redact_level"] == "public"

    def test_select_param(self, registered_project: Path) -> None:
        result = mcp_server.dispatch_tool(
            "state_snapshot",
            {"select": "$.streams.plans[*].plan_id"},
        )
        # When select is used, the result is the selection — wrapped under
        # a `select_result` key so the schema stays clean
        assert "select_result" in result
        assert result["select_result"] == ["2026-05-10-001-feat-fixture"]

    def test_include_filter(self, registered_project: Path) -> None:
        result = mcp_server.dispatch_tool(
            "state_snapshot", {"include": ["plans"]}
        )
        assert len(result["streams"]["plans"]) == 1
        assert result["streams"]["gates"] == []

    def test_plan_filter(self, registered_project: Path) -> None:
        result = mcp_server.dispatch_tool(
            "state_snapshot",
            {"plan": "2026-05-10-001-feat-fixture"},
        )
        ids = [p["plan_id"] for p in result["streams"]["plans"]]
        assert ids == ["2026-05-10-001-feat-fixture"]


# ─────────────────── 2. state_stream tool ───────────────────


class TestStateStreamTool:
    def test_tool_registered(self) -> None:
        assert "state_stream" in mcp_server.list_tool_names()

    def test_returns_events_envelope(self, registered_project: Path) -> None:
        result = mcp_server.dispatch_tool("state_stream", {})
        assert "events" in result
        assert "since" in result
        assert "captured_at" in result
        assert isinstance(result["events"], list)

    def test_since_cursor_filters_old_events(self, registered_project: Path) -> None:
        future = "2099-01-01T00:00:00Z"
        result = mcp_server.dispatch_tool("state_stream", {"since": future})
        assert result["events"] == []


# ─────────────────── 3. approval metadata on mutation tools ───────────────────


class TestApprovalMetadata:
    def test_dispatch_tool_describes_confirm_requirement(self) -> None:
        schema = mcp_server.tool_schema("dispatch")
        # `confirm` is a documented parameter
        assert "confirm" in schema["properties"]

    def test_approve_gate_tool_describes_confirm_requirement(self) -> None:
        schema = mcp_server.tool_schema("approve_gate")
        assert "confirm" in schema["properties"]


# ─────────────────── 4. surface count ───────────────────


class TestToolSurface:
    def test_state_tools_present(self) -> None:
        names = mcp_server.list_tool_names()
        # F005 adds two; original D002 surface was 6, now 8
        assert "state_snapshot" in names
        assert "state_stream" in names
        assert len(names) == 8
