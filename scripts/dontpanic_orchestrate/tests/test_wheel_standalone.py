"""Verify the published wheel starts as a standalone MCP server."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from dontpanic_orchestrate import mcp_server  # noqa: E402


pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None or shutil.which("uvx") is None,
    reason="uv/uvx not available",
)


@pytest.fixture(scope="module")
def wheel_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build_root = tmp_path_factory.mktemp("standalone-wheel")
    dist_dir = build_root / "dist"
    dist_dir.mkdir()
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir), str(REPO_ROOT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, (
        f"wheel build failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout[-2000:]}\n"
        f"stderr:\n{result.stderr[-2000:]}"
    )
    wheels = sorted(dist_dir.glob("dontpanic_orchestrate-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found {wheels}"
    return wheels[0]


def _run_server(command: list[str], run_dir: Path) -> None:
    run_dir.mkdir()
    assert not run_dir.resolve().is_relative_to(REPO_ROOT.resolve())

    env = os.environ.copy()
    for key in list(env):
        if key in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"} or key.startswith(
            "UV_PROJECT"
        ):
            env.pop(key, None)

    process = subprocess.Popen(
        command,
        cwd=run_dir,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_lines: queue.Queue[str | None] = queue.Queue()
    stderr_tail = {"text": ""}
    stderr_lock = threading.Lock()

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            stdout_lines.put(line)
        stdout_lines.put(None)

    def read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            with stderr_lock:
                stderr_tail["text"] = (stderr_tail["text"] + line)[-2000:]

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    deadline = time.monotonic() + 300
    failure: str | None = None
    initialize_response: dict | None = None
    tools_response: dict | None = None
    exit_code: int | None = None

    def send(message: dict) -> None:
        if process.stdin is None:
            raise RuntimeError("stdin is unavailable")
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def read_response() -> dict:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("timed out waiting for MCP response after 300 seconds")
        try:
            line = stdout_lines.get(timeout=remaining)
        except queue.Empty as exc:
            raise RuntimeError("timed out waiting for MCP response after 300 seconds") from exc
        if line is None:
            raise RuntimeError("server closed stdout before returning an MCP response")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"server returned a non-JSON line: {line[:500]!r}") from exc

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "standalone-wheel-test", "version": "1"},
                },
            }
        )
        initialize_response = read_response()
        send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_response = read_response()
    except (BrokenPipeError, OSError, RuntimeError, ValueError) as exc:
        failure = str(exc)
    finally:
        if process.stdin is not None and not process.stdin.closed:
            try:
                process.stdin.close()
            except OSError as exc:
                failure = failure or f"could not close server stdin: {exc}"
        try:
            exit_code = process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            failure = failure or "server did not exit within 60 seconds after stdin closed"
            process.terminate()
            try:
                exit_code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                exit_code = process.wait(timeout=10)
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

    with stderr_lock:
        stderr = stderr_tail["text"][-2000:]

    def fail(message: str) -> None:
        raise AssertionError(f"{message}\n--- stderr (last 2000 chars) ---\n{stderr}")

    try:
        if failure:
            raise RuntimeError(f"MCP server command failed: {failure}")
        if initialize_response is None:
            raise RuntimeError("server returned no initialize response")
        if tools_response is None:
            raise RuntimeError("server returned no tools/list response")
        initialize_result = initialize_response.get("result")
        if not isinstance(initialize_result, dict):
            raise RuntimeError(f"unexpected initialize response: {initialize_response!r}")
        if initialize_result.get("protocolVersion") != "2025-03-26":
            raise RuntimeError(f"unexpected initialize response: {initialize_response!r}")

        tools_result = tools_response.get("result")
        if not isinstance(tools_result, dict):
            raise RuntimeError(f"unexpected tools/list response: {tools_response!r}")
        tools = tools_result.get("tools")
        if not isinstance(tools, list):
            raise RuntimeError(f"unexpected tools/list response: {tools_response!r}")
        if len(tools) != 9:
            raise RuntimeError(f"expected exactly 9 tools, received {len(tools)}")
        for tool in tools:
            if not isinstance(tool, dict):
                raise RuntimeError(f"tool entry is not an object: {tool!r}")
            if not isinstance(tool.get("title"), str) or not tool["title"].strip():
                raise RuntimeError(f"tool has no non-empty title: {tool!r}")
            annotations = tool.get("annotations")
            if not isinstance(annotations, dict) or not {
                "readOnlyHint",
                "destructiveHint",
            }.issubset(annotations):
                raise RuntimeError(
                    f"tool annotations lack readOnlyHint or destructiveHint: {tool!r}"
                )
            if not isinstance(tool.get("name"), str):
                raise RuntimeError(f"tool has no string name: {tool!r}")
        expected_names = set(mcp_server.list_tool_names())
        actual_names = {tool["name"] for tool in tools}
        if actual_names != expected_names:
            raise RuntimeError(
                f"tool names differ: expected {sorted(expected_names)}, got {sorted(actual_names)}"
            )
        if exit_code != 0:
            raise RuntimeError(f"server exited with code {exit_code}")
    except Exception as exc:
        fail(f"standalone server assertion failed: {exc}")


@pytest.mark.parametrize(
    "launch_args",
    [
        ["--from", "WHEEL", "dontpanic", "mcp", "serve"],
        ["--from", "WHEEL", "dontpanic-orchestrate"],
    ],
    ids=["dontpanic-mcp-serve", "distribution-entrypoint"],
)
def test_built_wheel_serves_mcp_over_stdio(
    wheel_path: Path,
    tmp_path: Path,
    launch_args: list[str],
) -> None:
    command = ["uvx", *(str(wheel_path) if arg == "WHEEL" else arg for arg in launch_args)]
    _run_server(command, tmp_path / "outside-repository")


def test_wheel_contains_agent_conventions_and_prompt_data(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as wheel:
        entries = set(wheel.namelist())

    required = {
        "dontpanic_orchestrate/agent_conventions/VERSION",
        "dontpanic_orchestrate/agent_conventions/schemas/v1_0/plan.schema.json",
        "dontpanic_orchestrate/agent_conventions/schemas/v1_0/models/plan_model.py",
        "dontpanic_orchestrate/agent_conventions/schemas/v1_0/models/experience_readiness.py",
    }
    assert required <= entries, f"wheel is missing entries: {sorted(required - entries)}"
    expected_prompts = {
        f"dontpanic_orchestrate/prompts/{path.name}"
        for path in (REPO_ROOT / "scripts/dontpanic_orchestrate/prompts").glob("*.md")
        if path.is_file()
    }
    assert expected_prompts <= entries, (
        f"wheel is missing prompt files: {sorted(expected_prompts - entries)}"
    )
    assert not any(entry.startswith("models/") for entry in entries)
    assert "experience_readiness.py" not in entries
