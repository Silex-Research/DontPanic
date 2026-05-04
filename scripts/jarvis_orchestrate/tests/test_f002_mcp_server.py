"""Plan 2026-05-03-003 F002 — thin local MCP server.

Tests cover the full F002 acceptance contract:

  - Tool surface = exactly the documented 6 (D002 — NO ``intake``).
  - Each tool's input is Pydantic-validated; unknown args refused.
  - Read-only tools return the documented shapes for a tmp_path-rooted
    registry (``list_projects`` / ``validate_plan`` / ``status`` /
    ``read_evidence``).
  - Mutating tools (``dispatch`` / ``approve_gate``) default to dry-run;
    parametric over ``confirm`` absent / ``confirm: false`` /
    ``confirm: true`` (D004).
  - Path validation refuses out-of-tree paths (D005). Parametric over
    absolute-outside / relative-outside / not-in-registry / bare-cwd.
  - Local-only invariant (D003): no non-loopback HTTP listener bound by
    any code path. ``--remote`` / ``--host`` / ``--port`` flags refuse.
  - Logging discipline: stdout is reserved for the JSON-RPC protocol;
    server logs land on stderr (parametric capsys assert).
  - Negative: ``intake`` is NOT in the registered tool list (D002).

All tests redirect ``$DONTPANIC_HOME`` to ``tmp_path`` so the user's
real ``~/.dontpanic/`` is never read or written. The autouse
``conftest._isolate_jarvis_state`` fixture handles the active-supervisors
/ quota / breaker-history paths.

Run: PYTHONPATH=scripts pytest \\
    scripts/jarvis_orchestrate/tests/test_f002_mcp_server.py
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import cli, gate_pause, mcp_server, projects_registry  # noqa: E402
from jarvis_orchestrate import global_config as gc  # noqa: E402

# ──────────────────────────────  fixtures  ──────────────────────────────


_PLAN_ID = "2026-05-03-003-feat-agent-access-manifest-thin-mcp"

_PLAN_MD_TEMPLATE = """---
id: {plan_id}
title: Synthetic plan for F002 MCP server tests
type: feat
tier: trivial
status: active
date: "2026-05-03"
description: |
  Synthetic plan exercising the F002 MCP tool surface.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# Synthetic F002 plan

## Target

```yaml
target_env: dev
target_project: none
```
"""


def _write_plan(repo: Path, plan_id: str = _PLAN_ID) -> Path:
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_PLAN_MD_TEMPLATE.format(plan_id=plan_id))
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
                        "description": "Synthetic feature.",
                        "steps": ["step a", "step b"],
                        "acceptance": "It works.",
                        "passes": False,
                        "depends_on": [],
                    },
                    {
                        "id": "F002",
                        "category": "test",
                        "phase": 1,
                        "description": "Synthetic feature 2.",
                        "steps": ["step a"],
                        "acceptance": "It works.",
                        "passes": False,
                        "depends_on": [],
                    },
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return plan_dir


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Reroute $DONTPANIC_HOME to tmp_path/.dontpanic so the real
    ~/.dontpanic/projects.json is never consulted. $JARVIS_HOME is
    unset so legacy fallback resolution is deterministic."""
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    home = tmp_path / ".dontpanic"
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(home))
    return home


@pytest.fixture
def registered_repo(tmp_path, isolated_home):
    """Build a tmp_path repo with a registered project and one plan dir.
    Returns (repo_path, plan_dir, project_name)."""
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    plan_dir = _write_plan(repo)
    projects_registry.add_project("demo", str(repo))
    return repo, plan_dir, "demo"


# ──────────────────────────────  TOOL SURFACE (D002)  ──────────────────────────────


class TestToolSurface:
    """The documented 6 tools — and nothing else (D002)."""

    EXPECTED_TOOLS = (
        "list_projects",
        "validate_plan",
        "dispatch",
        "status",
        "approve_gate",
        "read_evidence",
    )

    def test_exactly_six_tools_registered(self):
        names = mcp_server.list_tool_names()
        assert tuple(names) == self.EXPECTED_TOOLS, (
            f"Tool surface drift: got {names}, expected {list(self.EXPECTED_TOOLS)}. "
            "Adding tools beyond the documented 6 violates D002 — Phase C owns intake."
        )

    @pytest.mark.parametrize("forbidden", ["intake", "submit_plan", "create_plan"])
    def test_intake_and_phase_c_tools_not_registered(self, forbidden):
        """D002 negative assertion: intake (and adjacent Phase C surfaces)
        must NOT appear in the F002 tool list."""
        assert forbidden not in mcp_server.list_tool_names()

    def test_tools_list_jsonrpc_response_matches_registry(self):
        resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert resp is not None
        names = [t["name"] for t in resp["result"]["tools"]]
        assert tuple(names) == self.EXPECTED_TOOLS

    def test_each_tool_exposes_input_schema(self):
        resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        for entry in resp["result"]["tools"]:
            assert "inputSchema" in entry
            assert isinstance(entry["inputSchema"], dict)
            # Pydantic v2's model_json_schema produces 'type': 'object'.
            assert entry["inputSchema"].get("type") == "object"


# ──────────────────────────────  INPUT VALIDATION  ──────────────────────────────


class TestInputValidation:
    """Each tool's Pydantic input model rejects unknown fields and
    enforces the declared types."""

    def test_validate_plan_requires_plan_arg(self, isolated_home):
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool("validate_plan", {})
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS

    def test_dispatch_rejects_unknown_field(self, isolated_home):
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool("dispatch", {"plan": "x", "rogue_field": True})
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS

    def test_unknown_tool_name_refused(self):
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool("does_not_exist", {})
        assert exc.value.code == mcp_server.ERR_METHOD_NOT_FOUND


# ──────────────────────────────  list_projects  ──────────────────────────────


class TestListProjects:
    def test_empty_registry(self, isolated_home):
        out = mcp_server.dispatch_tool("list_projects", {})
        assert out == {"projects": []}

    def test_lists_registered_project(self, registered_repo):
        repo, _plan_dir, name = registered_repo
        out = mcp_server.dispatch_tool("list_projects", {})
        names = [p["name"] for p in out["projects"]]
        assert name in names


# ──────────────────────────────  validate_plan  ──────────────────────────────


class TestValidatePlan:
    def test_happy_path_returns_documented_shape(self, registered_repo):
        _repo, _plan_dir, _name = registered_repo
        out = mcp_server.dispatch_tool("validate_plan", {"plan": _PLAN_ID})
        assert out["valid"] is True
        assert out["plan_id"] == _PLAN_ID
        assert out["target_env"] == "dev"
        assert out["target_project"] is None  # 'none' sentinel → None
        assert out["human_gates"] == ["pre_impl", "pre_merge"]
        assert sorted(out["feature_ids"]) == ["F001", "F002"]

    def test_validation_failure_returns_structured_error(self, registered_repo, tmp_path):
        _repo, plan_dir, _name = registered_repo
        # Corrupt features.json so plan_loader.load raises ValueError.
        (plan_dir / "features.json").write_text("not valid json")
        out = mcp_server.dispatch_tool("validate_plan", {"plan": _PLAN_ID})
        assert out["valid"] is False
        assert "error" in out


# ──────────────────────────────  PATH VALIDATION (D005)  ──────────────────────────────


class TestPathValidation:
    """Every tool that takes a plan path must refuse out-of-tree paths.
    Parametric over the four refusal shapes from D005."""

    @pytest.mark.parametrize(
        "tool,arg_factory",
        [
            ("validate_plan", lambda v: {"plan": v}),
            ("dispatch", lambda v: {"plan": v, "feature": "F001"}),
            ("status", lambda v: {"plan": v}),
            ("approve_gate", lambda v: {"plan": v, "gate": "pre_impl"}),
            ("read_evidence", lambda v: {"plan": v, "file": "x"}),
        ],
    )
    def test_absolute_path_outside_registry_refuses(
        self, tool, arg_factory, registered_repo, tmp_path
    ):
        """Absolute path that exists but is outside any registered project's
        plans_dir must hard-refuse."""
        rogue = tmp_path / "rogue-dir"
        rogue.mkdir()
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool(tool, arg_factory(str(rogue)))
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS
        assert exc.value.data is None or exc.value.data.get("reason") in (
            "out_of_tree",
            "not_a_directory",
        )

    @pytest.mark.parametrize(
        "tool,arg_factory",
        [
            ("validate_plan", lambda v: {"plan": v}),
            ("dispatch", lambda v: {"plan": v, "feature": "F001"}),
            ("status", lambda v: {"plan": v}),
        ],
    )
    def test_name_not_in_registry_refuses(self, tool, arg_factory, registered_repo):
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool(tool, arg_factory("not-a-real-plan-id"))
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS

    @pytest.mark.parametrize(
        "tool,arg_factory",
        [
            ("validate_plan", lambda v: {"plan": v}),
            ("dispatch", lambda v: {"plan": v, "feature": "F001"}),
            ("status", lambda v: {"plan": v}),
            ("approve_gate", lambda v: {"plan": v, "gate": "pre_impl"}),
            ("read_evidence", lambda v: {"plan": v, "file": "x"}),
        ],
    )
    @pytest.mark.parametrize(
        "traversal",
        [
            "../../../../etc",
            "../../../etc/passwd",
            "subdir/../../../escape",
            "..",
        ],
    )
    def test_relative_path_traversal_refuses(self, tool, arg_factory, traversal, registered_repo):
        """D005: a relative ``plan`` arg that resolves outside the registered
        plans_dir tree (e.g. ``../../../etc``) must hard-refuse, even if a
        directory exists at that location. Regression test for codex i0
        finding (high/security)."""
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool(tool, arg_factory(traversal))
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS
        # Must NOT be ``out_of_evidence_tree`` — we should refuse at plan
        # resolution, not after. Acceptable reasons: ``not_in_registry``
        # (traversal skipped, no match) or ``out_of_tree`` (absolute branch
        # refusal — not applicable here, but allow for future tightening).
        if exc.value.data is not None:
            assert exc.value.data.get("reason") in (
                "not_in_registry",
                "out_of_tree",
            )

    def test_bare_cwd_relative_path_refuses(self, registered_repo, monkeypatch, tmp_path):
        """D005: even if cwd has a docs/plans/<plan_id> directory, the MCP
        server does NOT consult cwd. Only the registry resolves names."""
        # Build a fake plan dir under cwd that mirrors the legacy CLI's
        # Step 4 fallback. The MCP tool must NOT find it.
        decoy_repo = tmp_path / "unregistered"
        decoy_repo.mkdir()
        (decoy_repo / "docs" / "plans" / "fake-id").mkdir(parents=True)
        monkeypatch.chdir(decoy_repo)
        # Still refuses because "fake-id" is not in the registry.
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool("validate_plan", {"plan": "fake-id"})
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS

    def test_registered_name_resolves(self, registered_repo):
        """Positive: registered plan_id resolves correctly."""
        out = mcp_server.dispatch_tool("validate_plan", {"plan": _PLAN_ID})
        assert out["valid"] is True

    def test_absolute_path_under_registered_root_resolves(self, registered_repo):
        """Positive: absolute path under a registered project's plans_dir
        resolves."""
        _repo, plan_dir, _name = registered_repo
        out = mcp_server.dispatch_tool("validate_plan", {"plan": str(plan_dir)})
        assert out["valid"] is True


# ──────────────────────────────  dispatch (D004 dry-run)  ──────────────────────────────


class TestDispatchDryRun:
    """D004: ``dispatch`` defaults to dry-run. Parametric over confirm
    absent / false / true."""

    @pytest.mark.parametrize(
        "args_extra",
        [
            {},  # confirm absent
            {"confirm": False},  # confirm: false
        ],
        ids=["confirm_absent", "confirm_false"],
    )
    def test_dry_run_does_not_invoke_dispatch_volley(
        self, registered_repo, monkeypatch, args_extra
    ):
        called: list[bool] = []

        def _spy(*a, **kw):  # pragma: no cover — must NOT fire
            called.append(True)
            raise AssertionError("dispatch_volley should not run in dry-run")

        monkeypatch.setattr("jarvis_orchestrate.mcp_server.supervisor.dispatch_volley", _spy)
        out = mcp_server.dispatch_tool(
            "dispatch", {"plan": _PLAN_ID, "feature": "F001", **args_extra}
        )
        assert out["dry_run"] is True
        assert "intent" in out
        assert out["intent"]["plan_id"] == _PLAN_ID
        assert out["intent"]["feature_id"] == "F001"
        assert out["intent"]["human_gates"] == ["pre_impl", "pre_merge"]
        assert called == []

    def test_confirm_true_invokes_dispatch_volley(self, registered_repo, monkeypatch):
        """Only confirm=true should reach the underlying supervisor."""

        class _FakeResult:
            final_status = "signed_off"
            rounds = 1
            reason = "ok"
            audit_paths: list = []

        called: list[dict] = []

        def _spy(**kw):
            called.append(kw)
            return _FakeResult()

        monkeypatch.setattr("jarvis_orchestrate.mcp_server.supervisor.dispatch_volley", _spy)
        out = mcp_server.dispatch_tool(
            "dispatch", {"plan": _PLAN_ID, "feature": "F001", "confirm": True}
        )
        assert out["dry_run"] is False
        assert out["result"]["final_status"] == "signed_off"
        assert len(called) == 1
        # The kwargs forwarded to dispatch_volley must include the resolved
        # plan_dir + feature.
        assert called[0]["feature_id"] == "F001"
        assert isinstance(called[0]["plan_dir"], Path)


# ──────────────────────────────  approve_gate (D004 dry-run)  ──────────────────────────────


class TestApproveGateDryRun:
    @pytest.mark.parametrize(
        "args_extra",
        [{}, {"confirm": False}],
        ids=["confirm_absent", "confirm_false"],
    )
    def test_dry_run_does_not_clear_gate(self, registered_repo, args_extra):
        _repo, plan_dir, _name = registered_repo
        out = mcp_server.dispatch_tool(
            "approve_gate", {"plan": _PLAN_ID, "gate": "pre_impl", **args_extra}
        )
        assert out["dry_run"] is True
        assert out["intent"]["currently_cleared"] is False
        assert out["intent"]["would_clear"] is True
        # Gate-state file should not exist or, if it does, gate is not cleared.
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_confirm_true_clears_gate(self, registered_repo):
        _repo, plan_dir, _name = registered_repo
        out = mcp_server.dispatch_tool(
            "approve_gate",
            {"plan": _PLAN_ID, "gate": "pre_impl", "confirm": True},
        )
        assert out["dry_run"] is False
        assert out["result"]["changed"] is True
        assert gate_pause.is_gate_cleared(plan_dir, "pre_impl")


# ──────────────────────────────  status  ──────────────────────────────


class TestStatus:
    def test_no_plan_returns_active_supervisors_only(self, isolated_home):
        out = mcp_server.dispatch_tool("status", {})
        assert "active_supervisors" in out
        assert "gate_status" not in out
        # Empty active list (autouse fixture isolates the registry path).
        assert out["active_supervisors"] == []

    def test_with_plan_includes_gate_status(self, registered_repo):
        out = mcp_server.dispatch_tool("status", {"plan": _PLAN_ID})
        assert "gate_status" in out
        gs = out["gate_status"]
        assert gs["plan_id"] == _PLAN_ID
        assert gs["paused"] is True  # Both pre_impl and pre_merge are unmet
        assert sorted(gs["unmet"]) == ["pre_impl", "pre_merge"]


# ──────────────────────────────  read_evidence (D005)  ──────────────────────────────


class TestReadEvidence:
    def test_returns_evidence_file_contents(self, registered_repo):
        _repo, plan_dir, _name = registered_repo
        evidence = plan_dir / "evidence" / "iteration-0"
        evidence.mkdir(parents=True)
        target = evidence / "report.md"
        target.write_text("hello evidence\n")
        out = mcp_server.dispatch_tool(
            "read_evidence",
            {"plan": _PLAN_ID, "file": "iteration-0/report.md"},
        )
        assert out["content"] == "hello evidence\n"
        assert "evidence/iteration-0/report.md" in out["file"]

    def test_path_traversal_refused(self, registered_repo, tmp_path):
        _repo, plan_dir, _name = registered_repo
        # Create a sibling file outside evidence/
        outside = plan_dir.parent / "secret.md"
        outside.write_text("secret")
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool(
                "read_evidence",
                {"plan": _PLAN_ID, "file": "../secret.md"},
            )
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS

    def test_missing_file_refused(self, registered_repo):
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool(
                "read_evidence",
                {"plan": _PLAN_ID, "file": "does-not-exist.md"},
            )
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS


# ──────────────────────────────  D003: local-only invariant  ──────────────────────────────


class TestLocalOnlyInvariant:
    """D003: stdio is the only transport. Adding ``--remote`` / ``--host``
    / ``--port`` must hard-refuse — no HTTP listener bound to any
    interface in any code path."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--remote",
            "--host",
            "--port",
            "--bind",
            "--listen",
            "--port=8080",
            "--host=0.0.0.0",
            "--bind=127.0.0.1",
        ],
    )
    def test_remote_flags_refused(self, flag, capsys):
        rc = mcp_server.serve_main([flag])
        assert rc == 2
        err = capsys.readouterr().err
        assert "REFUSED" in err or "local-only" in err

    def test_module_does_not_import_http_server(self):
        """No HTTP listener module is imported by mcp_server. Searches the
        module's source for the canonical web-framework imports the auditor
        will grep for."""
        src = Path(mcp_server.__file__).read_text()
        for forbidden in (
            "import aiohttp",
            "import flask",
            "import uvicorn",
            "import starlette",
            "import fastapi",
            "import http.server",
            "import socketserver",
            "from aiohttp",
            "from flask",
            "from uvicorn",
            "from starlette",
            "from fastapi",
            "from http.server",
            "from socketserver",
        ):
            assert forbidden not in src, (
                f"mcp_server.py imports {forbidden!r} — D003 forbids any "
                "non-loopback transport in Phase B."
            )

    def test_module_does_not_bind_non_loopback(self):
        """No call to bind() / listen() / 0.0.0.0 in the module source."""
        src = Path(mcp_server.__file__).read_text()
        for forbidden in ("0.0.0.0", ".bind(", ".listen(", 'host="0.0.0.0"'):
            assert forbidden not in src, (
                f"mcp_server.py contains {forbidden!r} — D003 forbids "
                "binding a non-stdio transport in Phase B."
            )


# ──────────────────────────────  logging discipline  ──────────────────────────────


class TestLoggingDiscipline:
    """Stdout is reserved for MCP JSON-RPC protocol. All server logs go
    to stderr."""

    def test_serve_main_refusal_writes_to_stderr_only(self, capsys):
        rc = mcp_server.serve_main(["--port=8080"])
        assert rc == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "REFUSED" in captured.err

    def test_main_help_writes_to_stderr_only(self, capsys):
        rc = mcp_server.main([])
        assert rc == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "usage:" in captured.err

    def test_serve_stdio_emits_responses_on_stdout_and_logs_on_stderr(self, capsys):
        """JSON-RPC responses go to the provided stdout stream; logs (if any)
        go to stderr. Verified by feeding a single ``initialize`` request
        through serve_stdio with explicit streams."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
        stdin = io.StringIO(json.dumps(request) + "\n")
        stdout = io.StringIO()
        rc = mcp_server.serve_stdio(stdin=stdin, stdout=stdout)
        assert rc == 0
        # Response landed on the provided stdout buffer.
        out_lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
        assert len(out_lines) == 1
        assert out_lines[0]["result"]["protocolVersion"] == mcp_server.MCP_PROTOCOL_VERSION
        # Real stdout (sys.stdout) was NOT written to — the function honored
        # the explicit stream parameter.
        assert capsys.readouterr().out == ""


# ──────────────────────────────  JSON-RPC dispatch  ──────────────────────────────


class TestJsonRpcDispatch:
    """End-to-end: handle_request returns the canonical JSON-RPC envelope."""

    def test_initialize_handshake(self):
        resp = mcp_server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {},
            }
        )
        assert resp["result"]["protocolVersion"] == mcp_server.MCP_PROTOCOL_VERSION
        assert resp["result"]["serverInfo"]["name"] == "dontpanic-mcp"

    def test_initialized_notification_returns_no_response(self):
        resp = mcp_server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert resp is None

    def test_unknown_method_returns_method_not_found(self):
        resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": 99, "method": "does/not/exist"})
        assert resp["error"]["code"] == mcp_server.ERR_METHOD_NOT_FOUND

    def test_tools_call_envelope_is_text_content_block(self, isolated_home):
        resp = mcp_server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "list_projects", "arguments": {}},
            }
        )
        result = resp["result"]
        assert result["isError"] is False
        # MCP tool result envelope is a list of content blocks; the first is
        # JSON-text that parses back into the tool's dict.
        block = result["content"][0]
        assert block["type"] == "text"
        parsed = json.loads(block["text"])
        assert "projects" in parsed

    def test_tools_call_with_invalid_args_returns_error_envelope(self, isolated_home):
        resp = mcp_server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "validate_plan", "arguments": {}},
            }
        )
        assert "error" in resp
        assert resp["error"]["code"] == mcp_server.ERR_INVALID_PARAMS


# ──────────────────────────────  CLI integration  ──────────────────────────────


class TestCLIIntegration:
    """``dontpanic mcp serve`` is wired up and dispatches to the server
    module. ``dontpanic mcp`` (no subcommand) prints usage to stderr."""

    def test_cli_mcp_no_subcommand_returns_2(self, capsys):
        rc = cli.main(["mcp"])
        assert rc == 2
        assert "usage:" in capsys.readouterr().err

    def test_cli_mcp_unknown_subcommand_returns_2(self, capsys):
        rc = cli.main(["mcp", "publish"])
        assert rc == 2
        assert "unknown subcommand" in capsys.readouterr().err

    def test_cli_mcp_serve_with_remote_flag_refuses(self, capsys):
        rc = cli.main(["mcp", "serve", "--port=8080"])
        assert rc == 2
        assert "REFUSED" in capsys.readouterr().err
