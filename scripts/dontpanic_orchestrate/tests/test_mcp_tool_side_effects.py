"""MCP tool annotations and read-only filesystem guarantees."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sys
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from dontpanic_orchestrate import (  # noqa: E402
    active_supervisors,
    gate_pause,
    mcp_server,
    projects_registry,
)


_EXPECTED_ANNOTATIONS = {
    "list_projects": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "validate_plan": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "status": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "read_evidence": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "state_snapshot": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "state_stream": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "capabilities.get_status": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "dispatch": {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "approve_gate": {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
}

_PLAN_ID = "2026-11-03-001-feat-mcp-read-side-effects"
_DEAD_PID = 2_147_483_647
_TOOL_ARGUMENTS = {
    "list_projects": {},
    "validate_plan": {"plan": _PLAN_ID},
    "status": {"plan": _PLAN_ID},
    "read_evidence": {"plan": _PLAN_ID, "file": "proof.md"},
    "state_snapshot": {"plan": _PLAN_ID},
    "state_stream": {"plan": _PLAN_ID},
    "capabilities.get_status": {},
}
_READ_ONLY_TOOL_NAMES = tuple(
    name
    for name, tool in mcp_server.TOOLS.items()
    if tool.annotations.get("readOnlyHint") is True
)


def _make_plan(plans_root: Path, plan_id: str) -> Path:
    plan_dir = plans_root / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        f"id: {plan_id}\n"
        "title: MCP side effect fixture\n"
        "type: feat\n"
        "tier: local\n"
        "status: active\n"
        'date: "2026-11-03"\n'
        "goal_type: infra\n"
        "surfaces:\n  - infra\n"
        "agents_required:\n  - claude\n"
        "human_gates:\n  - pre_impl\n  - pre_merge\n"
        "loop_caps:\n  max_iterations: 3\n  no_progress_threshold: 2\n  wall_clock_hours: 4\n  hard_stop: false\n"
        "privacy_tier: internal\n"
        "links:\n  features: ./features.json\n  decisions: ./decisions.jsonl\n  evidence_dir: ./evidence/\n"
        "description: |\n  MCP side effect fixture.\n"
        "motivation: |\n  MCP side effect fixture.\n"
        "---\n"
        f"# {plan_id}\n\n"
        "## Target\n\n"
        "```yaml\n"
        "target_env: dev\n"
        "target_project: none\n"
        "```\n\n"
        "## Acceptance Summary\n\n"
        "- Fixture.\n",
        encoding="utf-8",
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
                        "description": "A read-only MCP fixture.",
                        "steps": ["Read the fixture."],
                        "acceptance": "The fixture validates.",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (plan_dir / "evidence").mkdir()
    return plan_dir


def test_tool_annotations_are_truthful():
    assert set(mcp_server.TOOLS) == set(_EXPECTED_ANNOTATIONS)
    for name, expected in _EXPECTED_ANNOTATIONS.items():
        annotations = mcp_server.TOOLS[name].annotations
        assert annotations == expected
        assert all(isinstance(annotations[key], bool) for key in expected)

    response = mcp_server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    listed_tools = response["result"]["tools"]
    assert {tool["name"] for tool in listed_tools} == set(_EXPECTED_ANNOTATIONS)
    for tool in listed_tools:
        annotations = tool["annotations"]
        expected = _EXPECTED_ANNOTATIONS[tool["name"]]
        assert {
            key: annotations.get(key) for key in expected
        } == expected
        assert annotations["title"] == tool["title"]


def _snapshot_tree(root: Path) -> dict[str, tuple[int, str, int]]:
    snapshot: dict[str, tuple[int, str, int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            payload = os.readlink(path).encode("utf-8")
            stat = path.lstat()
        elif path.is_file():
            payload = path.read_bytes()
            stat = path.stat()
        else:
            continue
        snapshot[str(path.relative_to(root))] = (
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            stat.st_mtime_ns,
        )
    return snapshot


@pytest.mark.parametrize("tool_name", _READ_ONLY_TOOL_NAMES)
def test_read_only_tools_have_no_filesystem_side_effects(
    tool_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    read_only_names = {
        name
        for name, tool in mcp_server.TOOLS.items()
        if tool.annotations.get("readOnlyHint") is True
    }
    assert read_only_names <= set(_TOOL_ARGUMENTS), (
        f"add an argument scenario for {sorted(read_only_names - set(_TOOL_ARGUMENTS))}"
    )

    home = tmp_path / "home"
    dontpanic_home = tmp_path / "dontpanic-home"
    project = tmp_path / "project"
    plan_dir = _make_plan(project / "docs" / "plans", _PLAN_ID)
    (plan_dir / "evidence" / "proof.md").write_text("evidence\n", encoding="utf-8")
    home.mkdir()
    dontpanic_home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DONTPANIC_HOME", str(dontpanic_home))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jarvis-home"))
    registry_path = tmp_path / "jarvis-home" / "active_supervisors.jsonl"
    monkeypatch.setenv("JARVIS_ACTIVE_SUPERVISORS_PATH", str(registry_path))

    projects_registry.add_project("side-effect-project", str(project))
    gate_path = gate_pause.gate_state_path(plan_dir)
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text("{ invalid gate json", encoding="utf-8")
    active_supervisors.register(
        _PLAN_ID,
        "dev",
        None,
        None,
        pid=_DEAD_PID,
    )
    monkeypatch.setattr(
        active_supervisors,
        "_is_pid_alive",
        lambda pid: False if pid == _DEAD_PID else True,
    )

    real_git = shutil.which("git")
    assert real_git is not None
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    (stub_bin / "git").symlink_to(real_git)
    monkeypatch.setenv("PATH", str(stub_bin))

    network_calls = {"urlopen": 0, "socket": 0}

    def block_urlopen(*_args, **_kwargs):
        network_calls["urlopen"] += 1
        raise OSError("network disabled in test")

    def block_socket(*_args, **_kwargs):
        network_calls["socket"] += 1
        raise OSError("network disabled in test")

    monkeypatch.setattr(urllib.request, "urlopen", block_urlopen)
    monkeypatch.setattr(socket, "create_connection", block_socket)

    before = _snapshot_tree(tmp_path)
    response = mcp_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": _TOOL_ARGUMENTS[tool_name]},
        }
    )
    after = _snapshot_tree(tmp_path)

    assert "error" not in response
    assert response["result"]["isError"] is False
    assert before == after
    if tool_name == "capabilities.get_status":
        assert network_calls["urlopen"] > 0


def test_dead_supervisor_entries_are_still_pruned_on_write_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    registry_path = tmp_path / "active_supervisors.jsonl"
    monkeypatch.setenv("JARVIS_ACTIVE_SUPERVISORS_PATH", str(registry_path))
    monkeypatch.setattr(
        active_supervisors,
        "_is_pid_alive",
        lambda pid: False if pid == _DEAD_PID else True,
    )
    active_supervisors.register("dead-plan", "dev", None, None, pid=_DEAD_PID)
    original = registry_path.read_bytes()

    assert active_supervisors.list_active(prune=False) == []
    assert registry_path.read_bytes() == original
    assert active_supervisors.list_active() == []
    assert registry_path.read_bytes() == b""


def test_corrupt_gate_state_backup_moves_to_write_path(tmp_path: Path):
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    gate_path = gate_pause.gate_state_path(plan_dir)
    gate_path.parent.mkdir(parents=True)
    corrupt_bytes = b"{ invalid gate json"
    gate_path.write_bytes(corrupt_bytes)
    backup_path = gate_path.with_suffix(".corrupt.json")

    assert gate_pause._read_state(plan_dir) == {
        "plan_id": None,
        "cleared_gates": [],
        "history": [],
    }
    assert gate_pause.cleared_gates(plan_dir) == []
    assert gate_pause.is_gate_cleared(plan_dir, "pre_impl") is False
    evaluation = gate_pause.evaluate(plan_dir, ["pre_impl"])
    assert evaluation.unmet == ["pre_impl"]
    assert gate_path.read_bytes() == corrupt_bytes
    assert not backup_path.exists()

    assert gate_pause.approve_gate(plan_dir, "pre_impl", plan_id="gate-plan") is True
    assert backup_path.read_bytes() == corrupt_bytes
    assert isinstance(json.loads(gate_path.read_text(encoding="utf-8")), dict)
