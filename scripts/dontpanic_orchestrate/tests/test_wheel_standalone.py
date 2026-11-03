"""Verify the published wheel starts as a standalone MCP server."""

from __future__ import annotations

import json
import hashlib
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
from dontpanic_orchestrate import projects_registry  # noqa: E402


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


@pytest.fixture(scope="module")
def installed_wheel_venv(
    wheel_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path]:
    venv_dir = tmp_path_factory.mktemp("standalone-wheel-venv") / "venv"
    created = subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(venv_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert created.returncode == 0, f"uv venv failed: {created.stderr}"
    bin_dir = venv_dir / "bin"
    python = bin_dir / "python"
    installed = subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(wheel_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert installed.returncode == 0, (
        f"wheel install failed (exit {installed.returncode})\n"
        f"stdout:\n{installed.stdout[-2000:]}\n"
        f"stderr:\n{installed.stderr[-2000:]}"
    )
    return venv_dir, bin_dir


def _run_server(
    command: list[str],
    run_dir: Path,
    *,
    env_overrides: dict[str, str] | None = None,
    extra_requests: list[dict] | None = None,
    read_only_scenarios: dict[str, dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    run_dir.mkdir(parents=True)
    assert not run_dir.resolve().is_relative_to(REPO_ROOT.resolve())

    env = os.environ.copy()
    for key in list(env):
        if key in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"} or key.startswith(
            "UV_PROJECT"
        ):
            env.pop(key, None)
    if env_overrides:
        env.update(env_overrides)

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
    extra_responses: list[dict] = []
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
        requests_to_send = list(extra_requests or [])
        if read_only_scenarios is not None:
            listed_tools = tools_response.get("result", {}).get("tools", [])
            read_only_tools = [
                tool
                for tool in listed_tools
                if tool.get("annotations", {}).get("readOnlyHint") is True
            ]
            missing_scenarios = {
                tool["name"] for tool in read_only_tools
            } - set(read_only_scenarios)
            if missing_scenarios:
                raise RuntimeError(
                    f"add an argument scenario for {sorted(missing_scenarios)}"
                )
            for index, tool in enumerate(read_only_tools, start=100):
                requests_to_send.append(
                    {
                        "jsonrpc": "2.0",
                        "id": index,
                        "method": "tools/call",
                        "params": {
                            "name": tool["name"],
                            "arguments": read_only_scenarios[tool["name"]],
                        },
                    }
                )
        for request in requests_to_send:
            send(request)
            if "id" in request:
                extra_responses.append(read_response())
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
    return tools, extra_responses


def _hermetic_runtime_env(
    tmp_path: Path, bin_dir: Path
) -> tuple[dict[str, str], Path, Path, Path, Path]:
    home = tmp_path / "home"
    dontpanic_home = tmp_path / "dontpanic-home"
    jarvis_home = tmp_path / "jarvis-home"
    for path in (home, dontpanic_home, jarvis_home):
        path.mkdir(parents=True, exist_ok=True)

    real_git = shutil.which("git")
    assert real_git is not None
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir(exist_ok=True)
    (stub_bin / "git").symlink_to(real_git)

    env = os.environ.copy()
    for key in list(env):
        if key in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"} or key.startswith(
            "UV_PROJECT"
        ):
            env.pop(key, None)
    env.update(
        {
            "HOME": str(home),
            "DONTPANIC_HOME": str(dontpanic_home),
            "JARVIS_HOME": str(jarvis_home),
            "JARVIS_ACTIVE_SUPERVISORS_PATH": str(jarvis_home / "active_supervisors.jsonl"),
            "PATH": os.pathsep.join((str(bin_dir), str(stub_bin))),
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
            "all_proxy": "http://127.0.0.1:9",
            "NO_PROXY": "",
            "no_proxy": "",
        }
    )
    return env, home, dontpanic_home, jarvis_home, stub_bin


def _snapshot_paths(paths: list[Path]) -> dict[str, tuple[int, str, int]]:
    snapshot: dict[str, tuple[int, str, int]] = {}
    for root in paths:
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                payload = os.readlink(path).encode("utf-8")
                stat = path.lstat()
            elif path.is_file():
                payload = path.read_bytes()
                stat = path.stat()
            else:
                continue
            snapshot[str(path)] = (
                len(payload),
                hashlib.sha256(payload).hexdigest(),
                stat.st_mtime_ns,
            )
    return snapshot


def _write_standalone_plan(project: Path, plan_id: str) -> Path:
    plan_dir = project / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        f"id: {plan_id}\n"
        "title: Standalone MCP fixture\n"
        "type: feat\n"
        "tier: trivial\n"
        "status: active\n"
        'date: "2026-11-03"\n'
        "description: |\n  Standalone wheel test fixture.\n"
        "agents_required:\n  - claude\n  - codex\n"
        "human_gates:\n  - pre_impl\n  - pre_merge\n"
        "loop_caps:\n  max_iterations: 2\n  hard_stop: false\n"
        "privacy_tier: internal\n"
        "links:\n  features: ./features.json\n"
        "---\n"
        f"# {plan_id}\n\n"
        "## Target\n\n"
        "```yaml\n"
        "target_env: dev\n"
        "target_project: none\n"
        "```\n",
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
                        "category": "test",
                        "phase": 0,
                        "description": "Standalone MCP feature.",
                        "steps": ["Read the fixture."],
                        "acceptance": "The plan validates.",
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


def test_wheel_contains_capability_manifests(wheel_path: Path) -> None:
    expected = {
        f"dontpanic_orchestrate/capability_manifests/{path.name}"
        for path in (REPO_ROOT / "capabilities").glob("*.json")
    }
    expected.add(
        "dontpanic_orchestrate/agent_conventions/schemas/v1_0/capability.schema.json"
    )

    with zipfile.ZipFile(wheel_path) as wheel:
        entries = set(wheel.namelist())

    assert expected <= entries, f"wheel is missing entries: {sorted(expected - entries)}"


def test_wheel_read_only_tools_answer_outside_repository(
    installed_wheel_venv: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _venv_dir, bin_dir = installed_wheel_venv
    env, home, dontpanic_home, jarvis_home, _stub_bin = _hermetic_runtime_env(
        tmp_path, bin_dir
    )
    monkeypatch.setenv("DONTPANIC_HOME", str(dontpanic_home))
    monkeypatch.setenv("JARVIS_HOME", str(jarvis_home))
    monkeypatch.setenv(
        "JARVIS_ACTIVE_SUPERVISORS_PATH",
        str(jarvis_home / "active_supervisors.jsonl"),
    )

    project = tmp_path / "registered-project"
    project.mkdir()
    plan_id = "2026-11-03-002-feat-standalone-mcp-tools"
    plan_dir = _write_standalone_plan(project, plan_id)
    evidence = plan_dir / "evidence"
    (evidence / "proof.md").write_text("standalone evidence\n", encoding="utf-8")
    projects_registry.add_project("standalone-wheel", str(project))

    scenarios = {
        "list_projects": {},
        "validate_plan": {"plan": plan_id},
        "status": {"plan": plan_id},
        "read_evidence": {"plan": plan_id, "file": "proof.md"},
        "state_snapshot": {"plan": plan_id},
        "state_stream": {"plan": plan_id},
        "capabilities.get_status": {},
    }
    run_dir = tmp_path / "outside-repository" / "mcp"
    assert not run_dir.resolve().is_relative_to(REPO_ROOT.resolve())
    before = _snapshot_paths([home, dontpanic_home, jarvis_home, project])
    tools, responses = _run_server(
        [str(bin_dir / "dontpanic-orchestrate")],
        run_dir,
        env_overrides=env,
        read_only_scenarios=scenarios,
    )
    read_tools = [tool for tool in tools if tool["annotations"].get("readOnlyHint") is True]
    read_only_names = {tool["name"] for tool in read_tools}
    assert read_only_names <= set(scenarios), (
        f"add an argument scenario for {sorted(read_only_names - set(scenarios))}"
    )
    assert len(responses) == len(read_tools)
    payloads: dict[str, dict] = {}
    for tool, response in zip(read_tools, responses, strict=True):
        name = tool["name"]
        assert "error" not in response
        assert response["result"]["isError"] is False
        text_blocks = [
            block
            for block in response["result"]["content"]
            if block.get("type") == "text"
        ]
        assert text_blocks
        payloads[name] = json.loads(text_blocks[0]["text"])

    assert payloads["validate_plan"]["valid"] is True
    expected_capability_ids = {
        json.loads(path.read_text(encoding="utf-8"))["id"]
        for path in (REPO_ROOT / "capabilities").glob("*.json")
    }
    assert {
        item["capability_id"]
        for item in payloads["capabilities.get_status"]["capabilities"]
    } == expected_capability_ids
    after = _snapshot_paths([home, dontpanic_home, jarvis_home, project])
    assert before == after


def test_wheel_doctor_outside_checkout_fails_cleanly(
    installed_wheel_venv: tuple[Path, Path], tmp_path: Path
) -> None:
    _venv_dir, bin_dir = installed_wheel_venv
    env, _home, _dontpanic_home, _jarvis_home, _stub_bin = _hermetic_runtime_env(
        tmp_path, bin_dir
    )
    run_dir = tmp_path / "outside-repository" / "doctor"
    run_dir.mkdir(parents=True)
    assert not run_dir.resolve().is_relative_to(REPO_ROOT.resolve())

    result = subprocess.run(
        [str(bin_dir / "dontpanic"), "doctor", "--skip-auth"],
        cwd=run_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert result.returncode == 2
    assert "source checkout" in result.stderr.lower()
    assert "Traceback" not in result.stdout + result.stderr


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
