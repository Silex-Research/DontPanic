"""MCP Registry and plugin listing contracts."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from dontpanic_orchestrate import mcp_server  # noqa: E402
from dontpanic_orchestrate import __version__  # noqa: E402


LAUNCH_COMMAND = "uvx"
LAUNCH = [f"dontpanic-orchestrate=={__version__}"]


def _read_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("protocol_version", "expected_version"),
    [
        ("2025-03-26", "2025-03-26"),
        ("2024-11-05", "2024-11-05"),
        ("1999-01-01", "2025-03-26"),
    ],
)
def test_initialize_negotiates_supported_protocol_versions(protocol_version, expected_version):
    response = mcp_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
    )

    assert response["result"]["protocolVersion"] == expected_version


def test_initialize_defaults_protocol_version_when_params_are_missing():
    response = mcp_server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    )

    assert response["result"]["protocolVersion"] == "2025-03-26"


def test_supported_protocol_versions_are_explicit():
    assert mcp_server.SUPPORTED_PROTOCOL_VERSIONS == ("2025-03-26", "2024-11-05")
    assert mcp_server.DEFAULT_PROTOCOL_VERSION == "2025-03-26"


def test_tools_list_includes_titles_and_read_only_annotations():
    expected_annotations = {
        "list_projects": {"readOnlyHint": True, "destructiveHint": False},
        "validate_plan": {"readOnlyHint": True, "destructiveHint": False},
        "dispatch": {"readOnlyHint": False, "destructiveHint": True},
        "status": {"readOnlyHint": True, "destructiveHint": False},
        "approve_gate": {"readOnlyHint": False, "destructiveHint": True},
        "read_evidence": {"readOnlyHint": True, "destructiveHint": False},
        "state_snapshot": {"readOnlyHint": True, "destructiveHint": False},
        "state_stream": {"readOnlyHint": True, "destructiveHint": False},
        "capabilities.get_status": {"readOnlyHint": True, "destructiveHint": False},
    }
    response = mcp_server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    tools = response["result"]["tools"]

    assert {tool["name"] for tool in tools} == set(expected_annotations)
    for tool in tools:
        assert isinstance(tool.get("title"), str) and tool["title"].strip()
        annotations = tool.get("annotations")
        assert isinstance(annotations, dict)
        assert {
            "readOnlyHint": annotations.get("readOnlyHint"),
            "destructiveHint": annotations.get("destructiveHint"),
        } == expected_annotations[tool["name"]]


def test_server_json_matches_mcp_registry_listing():
    server = json.loads(_read_text("server.json"))

    assert server["$schema"] == "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    assert server["name"] == "io.github.Silex-Research/dontpanic"
    assert server["version"] == __version__
    packages = server["packages"]
    assert isinstance(packages, list)
    assert len(packages) == 1
    package = packages[0]
    assert package["registryType"] == "pypi"
    assert package["registryBaseUrl"] == "https://pypi.org"
    assert package["identifier"] == "dontpanic-orchestrate"
    assert package["version"] == __version__
    assert package["runtimeHint"] == "uvx"
    assert package["transport"] == {"type": "stdio"}
    assert not package.get("packageArguments")
    assert len(server["description"]) <= 100


def test_pyproject_exposes_distribution_named_console_script():
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python before 3.11
        import tomli as tomllib

    project = tomllib.loads(_read_text("pyproject.toml"))

    assert project["project"]["scripts"]["dontpanic-orchestrate"] != (
        "dontpanic_orchestrate.cli:main"
    )


def test_distribution_entrypoint_is_a_distinct_mcp_server_callable():
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python before 3.11
        import tomli as tomllib

    project = tomllib.loads(_read_text("pyproject.toml"))
    entrypoint = project["project"]["scripts"]["dontpanic-orchestrate"]
    module_name, separator, attribute_name = entrypoint.partition(":")

    assert separator
    assert module_name == "dontpanic_orchestrate.mcp_server"
    callable_entrypoint = getattr(mcp_server, attribute_name)
    assert callable(callable_entrypoint)

    from dontpanic_orchestrate import cli

    assert callable_entrypoint is not cli.main


@pytest.mark.parametrize("help_arg", ["-h", "--help"])
def test_distribution_entrypoint_help_is_stderr_only(monkeypatch, capsys, help_arg):
    monkeypatch.setattr(sys, "argv", ["dontpanic-orchestrate", help_arg])

    with pytest.raises(SystemExit) as exc_info:
        mcp_server.console_main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert captured.out == ""
    assert "dontpanic-orchestrate starts the local stdio MCP server" in captured.err
    assert "dontpanic mcp serve" in captured.err
    assert "full CLI is `dontpanic`" in captured.err


def test_distribution_entrypoint_delegates_arguments_and_exit_code(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dontpanic-orchestrate"])
    received: list[list[str]] = []

    def fake_serve_main(argv: list[str]) -> int:
        received.append(argv)
        return 7

    monkeypatch.setattr(mcp_server, "serve_main", fake_serve_main)

    with pytest.raises(SystemExit) as exc_info:
        mcp_server.console_main()

    assert received == [[]]
    assert exc_info.value.code == 7


def test_cursor_plugin_manifest_and_mcp_launch_config():
    plugin = json.loads(_read_text(".cursor-plugin/plugin.json"))
    server_config = json.loads(_read_text(".cursor-plugin/mcp.json"))

    assert plugin["name"] == "dontpanic"
    assert plugin["version"] == __version__
    assert plugin["mcpServers"] == ".cursor-plugin/mcp.json"
    assert server_config["mcpServers"]["dontpanic"]["command"] == LAUNCH_COMMAND
    assert server_config["mcpServers"]["dontpanic"]["args"] == LAUNCH


def test_claude_plugin_manifest_has_versioned_mcp_launch_config():
    plugin = json.loads(_read_text(".claude-plugin/plugin.json"))

    assert plugin["name"] == "dontpanic"
    assert plugin["version"] == __version__
    assert plugin["mcpServers"]["dontpanic"]["command"] == LAUNCH_COMMAND
    assert plugin["mcpServers"]["dontpanic"]["args"] == LAUNCH


def test_readme_has_registry_name_and_privacy_heading():
    readme = _read_text("README.md")

    assert "<!-- mcp-name: io.github.Silex-Research/dontpanic -->" in readme.splitlines()
    assert re.search(r"^## Privacy", readme, re.MULTILINE)


def test_registry_namespace_is_pinned_before_pypi_upload():
    """The README marker becomes permanent once a version is on PyPI, so this must pass before any upload."""
    server = json.loads(_read_text("server.json"))
    name = server["name"]

    assert name == "io.github.Silex-Research/dontpanic"
    namespace_owner = name.split("/")[0].removeprefix("io.github.")
    repository_owner = server["repository"]["url"].split("github.com/", 1)[1].split("/", 1)[0]
    assert namespace_owner == repository_owner

    readme_lines = _read_text("README.md").splitlines()
    marker = "<!-- mcp-name: io.github.Silex-Research/dontpanic -->"
    assert marker in readme_lines
    actual_marker = next(line for line in readme_lines if line.startswith("<!-- mcp-name: "))
    marker_name = actual_marker.removeprefix("<!-- mcp-name: ").removesuffix(" -->")
    assert marker_name == name

    checked_paths = [
        "README.md",
        "CHANGELOG.md",
        "server.json",
        "docs/PUBLISHING.md",
        "docs/DISCOVERABILITY.md",
        ".cursor-plugin/plugin.json",
        ".cursor-plugin/mcp.json",
        ".claude-plugin/plugin.json",
    ]
    for relative_path in checked_paths:
        assert "io.github.silex-research" not in _read_text(relative_path), relative_path


def test_version_pins_do_not_drift_across_listing_surfaces():
    relative_paths = [
        "README.md",
        "docs/DISCOVERABILITY.md",
        "docs/USE_CASES.md",
        "docs/PUBLISHING.md",
        "docs/roadmap-2026-05-19-install-ux-architecture-v0.md",
        "server.json",
        ".cursor-plugin/plugin.json",
        ".cursor-plugin/mcp.json",
        ".claude-plugin/plugin.json",
    ]
    pin_pattern = re.compile(r"dontpanic-orchestrate==([0-9][^\s\"'`,)]*)")
    pins_by_path = {
        relative_path: pin_pattern.findall(_read_text(relative_path))
        for relative_path in relative_paths
    }

    for relative_path, pins in pins_by_path.items():
        assert all(version == __version__ for version in pins), (
            f"Version pin drift in {relative_path}: {pins}"
        )
    assert pins_by_path["README.md"]
    assert pins_by_path["docs/PUBLISHING.md"]


def test_docs_do_not_recommend_installing_the_unrelated_bare_distribution():
    doc_paths = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").rglob("*.md"))]
    wrong_install = re.compile(r"pipx\s+install\s+dontpanic(?![-\w])")

    for path in doc_paths:
        assert not wrong_install.search(path.read_text(encoding="utf-8")), str(path)


def test_discoverability_tool_count_matches_registered_tools():
    response = mcp_server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    registered_names = {tool["name"] for tool in response["result"]["tools"]}
    discoverability = _read_text("docs/DISCOVERABILITY.md")

    count_match = re.search(
        r"tool\s+list\s+is\s+exactly\s+(\d+)\s+tools", discoverability
    )
    assert count_match is not None
    assert int(count_match.group(1)) == len(registered_names)
    assert all(f"`{name}`" in discoverability for name in registered_names)
    assert all(
        int(count) == len(registered_names)
        for count in re.findall(r"exactly\s+(\d+)\s+(?:MCP\s+)?tools", discoverability)
    )


def test_publishing_doc_release_conventions():
    publishing = _read_text("docs/PUBLISHING.md")

    assert "dontpanic-v" in publishing
    assert "TestPyPI" in publishing
    assert "https://test.pypi.org/simple/" in publishing
    assert re.search(r"maintainer approval", publishing, re.IGNORECASE)


def test_docs_use_the_single_uvx_launch_form():
    relative_paths = ["README.md", "docs/DISCOVERABILITY.md", "docs/PUBLISHING.md"]
    for relative_path in relative_paths:
        document = _read_text(relative_path)
        assert f"uvx dontpanic-orchestrate=={__version__}" in document, relative_path
    for relative_path in relative_paths[:2]:
        document = _read_text(relative_path)
        assert ("uvx" + " --from" + " dontpanic-orchestrate") not in document, relative_path


def test_testpypi_runbook_and_pipx_contents_are_accurate():
    publishing = _read_text("docs/PUBLISHING.md")
    code_blocks = re.findall(r"```[^\n]*\n(.*?)```", publishing, re.DOTALL)
    commands = [
        line.strip()
        for block in code_blocks
        for line in re.sub(r"\\\s*\n\s*", " ", block).splitlines()
        if line.strip()
    ]
    rc_fetch_commands = [
        command
        for command in commands
        if "dontpanic-orchestrate==<version>rc1" in command
        and "https://test.pypi.org/simple/" in command
    ]
    assert rc_fetch_commands
    assert any("--no-deps" in command for command in rc_fetch_commands)

    local_wheel_launch = [
        command
        for command in commands
        if "uvx --from " in command and ".whl" in command
    ]
    assert local_wheel_launch
    assert all("test.pypi.org" not in line for line in local_wheel_launch)

    assert "--index https://test.pypi.org" not in publishing
    assert "--extra-index-url https://test.pypi.org" not in publishing
    assert (
        "UV_PUBLISH_TOKEN=<TestPyPI API token> uv publish --publish-url "
        "https://test.pypi.org/legacy/ dist/*"
    ) in publishing
    assert "TestPyPI trusted publisher" not in publishing

    roadmap = _read_text(
        "docs/roadmap-2026-05-19-install-ux-architecture-v0.md"
    )
    assert (
        "`pipx install dontpanic-orchestrate` includes the CLI, supervisor/dispatch, "
        "doctor/init/new, vendored schemas, validators, MCP server, state projection, "
        "and static dashboard/export. It does not include the repository-root "
        "`docs/`, `examples/`, or `research/` directories; use a source install for those."
    ) in roadmap


def test_mcp_registry_runbook_uses_org_oidc_login():
    publishing = _read_text("docs/PUBLISHING.md")
    headings = list(re.finditer(r"(?m)^## .+$", publishing))
    registry_heading = next(match for match in headings if match.group() == "## MCP Registry")
    next_heading = next(
        (match for match in headings if match.start() > registry_heading.start()),
        None,
    )
    section = publishing[
        registry_heading.start() : next_heading.start() if next_heading else len(publishing)
    ]

    for expected in (
        "mcp-publisher login github-oidc",
        "id-token: write",
        "--token",
        "read:org",
        "1468",
    ):
        assert expected in section
    assert all(line.strip() != "mcp-publisher login github" for line in publishing.splitlines())


def test_pypi_trusted_publishing_is_documented_as_future_work():
    publishing = _read_text("docs/PUBLISHING.md")
    headings = list(re.finditer(r"(?m)^## .+$", publishing))
    trusted_heading = next(
        match for match in headings if match.group() == "## PyPI trusted publishing"
    )
    next_heading = next(
        (match for match in headings if match.start() > trusted_heading.start()),
        None,
    )
    section = publishing[
        trusted_heading.start() : next_heading.start() if next_heading else len(publishing)
    ].lower()

    assert "future work" in section
    assert "no publish workflow" in section

    forbidden = ("mcp-publisher", "pypa/gh-action-pypi-publish", "uv publish", "twine")
    workflow_files = sorted((REPO_ROOT / ".github" / "workflows").rglob("*"))
    for path in workflow_files:
        if path.is_file():
            contents = path.read_text(encoding="utf-8")
            assert not any(term in contents for term in forbidden), str(path.relative_to(REPO_ROOT))


def test_sync_version_check_is_clean():
    result = subprocess.run(
        [sys.executable, "scripts/sync_version.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_sync_version_rewrites_pinned_distribution_versions():
    module_path = REPO_ROOT / "scripts" / "sync_version.py"
    spec = importlib.util.spec_from_file_location("dontpanic_sync_version_test", module_path)
    assert spec is not None and spec.loader is not None
    sync_version = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = sync_version
    spec.loader.exec_module(sync_version)

    assert sync_version.rewrite_text(
        "uvx dontpanic-orchestrate==9.9.9", "1.2.3"
    ) == "uvx dontpanic-orchestrate==1.2.3"
