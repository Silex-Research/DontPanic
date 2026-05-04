"""Plan 2026-05-03-003 F002 — thin local MCP server.

Exposes a constrained tool surface that wraps existing Phase A / Phase B
runtime calls. The server speaks JSON-RPC 2.0 over stdio (default
transport). Phase B is local-only by design (D003): no HTTP listener, no
``--remote`` flag, no authentication scaffolding.

Tool surface (D002 — exactly 6 tools, NO ``intake``):

  read-only
    list_projects   — wraps :func:`projects_registry.load_registry`
    validate_plan   — wraps :func:`plan_loader.load`
    status          — wraps :func:`active_supervisors.list_active` +
                      :func:`gate_pause.evaluate`
    read_evidence   — returns evidence file contents for a registered
                      plan + iteration. Refuses out-of-tree paths.

  mutating (default to dry-run; require ``confirm: true``)
    dispatch        — wraps :func:`supervisor.dispatch_volley`
    approve_gate    — wraps :func:`gate_pause.approve_gate`

Path validation (D005): every tool that takes a plan or evidence path
resolves it through :func:`_resolve_safe_path`, which is stricter than
the CLI's ``_resolve_plan_dir`` — registered projects only, no
``cwd/docs/plans`` fallback. Out-of-tree paths refuse with a structured
error.

Logging discipline: stdout is reserved for the MCP JSON-RPC protocol;
all server logs go to stderr. Use :data:`_LOG` (configured to stderr at
serve time) or ``print(..., file=sys.stderr)`` exclusively. A naked
``print`` in this module is a defect — it would corrupt the protocol
stream.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from dontpanic_orchestrate import (
    active_supervisors,
    gate_pause,
    plan_loader,
    project_config,
    projects_registry,
    supervisor,
)

_LOG = logging.getLogger(__name__)

# JSON-RPC 2.0 error codes (https://www.jsonrpc.org/specification#error_object).
ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603

# MCP protocol version this server speaks. Matches the version string used
# by callers (Claude Code, Codex CLI, Cursor) at the time of writing. The
# initialize handshake is the only place this is sent.
MCP_PROTOCOL_VERSION = "2024-11-05"

# Canonical operator CLI invocation that the F001 manifest advertises.
# `python -m dontpanic_orchestrate ...` is reserved for module-invocation
# / packaging verification per D011 of plan 2026-05-03-003 (and D011 of
# plan 2026-05-03-001 ancestry).
MCP_SERVER_COMMAND = "dontpanic"
MCP_SERVER_ARGS = ["mcp", "serve"]


class MCPError(Exception):
    """Structured error surfaced as a JSON-RPC error response."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


# ──────────────────────────────  D005: path validation  ──────────────────────────────


def _registered_plan_roots() -> list[tuple[Path, str]]:
    """Build the set of registered (plan_root, project_name) tuples from the
    projects registry. Each project's ``plans_dir`` (per-project override
    from ``.dontpanic/dontpanic.json`` or the default ``docs/plans``)
    resolves under the project path. Returned roots are absolute. Used as
    the allowlist for :func:`_resolve_safe_path`."""
    reg = projects_registry.load_registry()
    out: list[tuple[Path, str]] = []
    for entry in reg.projects:
        proj_path = Path(entry.path).expanduser().resolve()
        cfg = project_config.load_project_config(proj_path)
        plans_dir = cfg.plans_dir if cfg is not None else project_config.DEFAULT_PLANS_DIR
        out.append((proj_path / plans_dir, entry.name))
    return out


def _resolve_safe_path(plan_arg: str) -> Path:
    """MCP-strict plan resolution — registered projects only.

    D005: this differs from :func:`cli._resolve_plan_dir` in two ways:
      - Even an absolute path must resolve to a directory under one of
        the registered projects' plans_dir trees. Bare ``/etc`` or
        ``/tmp/some-fake-plan/`` refuses regardless of whether the path
        happens to exist.
      - There is NO ``cwd/docs/plans/<plan_arg>`` Step 4 fallback. The
        CLI's smoke-test ergonomics (work from an un-registered repo
        root) are intentionally removed here — MCP callers must register
        their project first.

    Refuses with :class:`MCPError` (mapped to JSON-RPC ``InvalidParams``).
    """
    roots = _registered_plan_roots()
    p = Path(plan_arg)

    if p.is_absolute():
        # Branch A: absolute path. Must resolve to a directory AND lie
        # under one of the registered plan-root trees.
        try:
            resolved = p.resolve()
        except (OSError, ValueError) as exc:
            raise MCPError(
                ERR_INVALID_PARAMS,
                f"plan path {plan_arg!r} could not be resolved",
                {"reason": "resolve_failed", "error": str(exc)},
            ) from exc
        if not resolved.is_dir():
            raise MCPError(
                ERR_INVALID_PARAMS,
                f"plan path {plan_arg!r} is not a directory",
                {"reason": "not_a_directory"},
            )
        for root, _name in roots:
            try:
                resolved.relative_to(root.resolve())
            except (ValueError, OSError):
                continue
            return resolved
        raise MCPError(
            ERR_INVALID_PARAMS,
            (
                f"plan path {plan_arg!r} resolves outside any registered "
                "project's plans_dir; refusing"
            ),
            {
                "reason": "out_of_tree",
                "registered_projects": [n for _r, n in roots],
            },
        )

    # Branch B: relative / plan-id form. Walk every registered project's
    # plans_dir; first match wins. No cwd/docs/plans fallback (D005).
    # Traversal guard: a relative arg like ``../../../etc`` can resolve
    # outside the root even though it joined under it. After resolving,
    # require ``resolved.relative_to(root_resolved)`` to still hold.
    for root, _name in roots:
        root_resolved = root.resolve()
        candidate = (root / plan_arg).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            # Joined path escapes the registered root via traversal — skip.
            continue
        if candidate.is_dir():
            return candidate
    raise MCPError(
        ERR_INVALID_PARAMS,
        (
            f"plan {plan_arg!r} not found in any registered project; "
            "MCP does not consult cwd/docs/plans"
        ),
        {
            "reason": "not_in_registry",
            "registered_projects": [n for _r, n in roots],
        },
    )


def _resolve_evidence_path(plan_dir: Path, file: str) -> Path:
    """Resolve ``file`` (relative to the plan's evidence/ root) and refuse
    any escape outside it. Used by the ``read_evidence`` tool."""
    evidence_root = (plan_dir / "evidence").resolve()
    requested = (evidence_root / file).resolve()
    try:
        requested.relative_to(evidence_root)
    except ValueError as exc:
        raise MCPError(
            ERR_INVALID_PARAMS,
            f"file path {file!r} resolves outside evidence/ for the plan",
            {"reason": "out_of_evidence_tree"},
        ) from exc
    if not requested.is_file():
        raise MCPError(
            ERR_INVALID_PARAMS,
            f"evidence file not found: {file!r}",
            {"reason": "not_found"},
        )
    return requested


# ──────────────────────────────  Pydantic input models  ──────────────────────────────


class _StrictModel(BaseModel):
    """Reject unknown fields so callers don't silently send mistyped args."""

    model_config = ConfigDict(extra="forbid")


class ListProjectsInput(_StrictModel):
    """No arguments. Listed for schema-introspection completeness."""


class ValidatePlanInput(_StrictModel):
    plan: str


class DispatchInput(_StrictModel):
    plan: str
    feature: str = "F001"
    implementer: str | None = None
    auditor: str | None = None
    max_iterations: int | None = None
    mode: str | None = None
    confirm: bool = False


class StatusInput(_StrictModel):
    plan: str | None = None


class ApproveGateInput(_StrictModel):
    plan: str
    gate: str
    confirm: bool = False


class ReadEvidenceInput(_StrictModel):
    plan: str
    file: str


# ──────────────────────────────  tool handlers  ──────────────────────────────


def _stringify_gates(gates: Any) -> list[str]:
    return [g.value if hasattr(g, "value") else str(g) for g in (gates or [])]


def _tier_str(tier: Any) -> str:
    return str(tier.value) if hasattr(tier, "value") else str(tier)


def tool_list_projects(args: dict[str, Any]) -> dict[str, Any]:
    """Read-only: return registered projects from ``~/.dontpanic/projects.json``."""
    ListProjectsInput.model_validate(args)
    reg = projects_registry.load_registry()
    return {
        "projects": [projects_registry.to_public_dict(p) for p in reg.projects],
    }


def tool_validate_plan(args: dict[str, Any]) -> dict[str, Any]:
    """Read-only: load + Pydantic-validate the plan directory. Returns the
    resolved plan_id, tier, target, gates, and feature IDs on success."""
    inp = ValidatePlanInput.model_validate(args)
    plan_dir = _resolve_safe_path(inp.plan)
    try:
        loaded = plan_loader.load(plan_dir)
    except (FileNotFoundError, ValueError) as exc:
        return {
            "valid": False,
            "plan_dir": str(plan_dir),
            "error": str(exc),
        }
    return {
        "valid": True,
        "plan_id": loaded.plan_id,
        "plan_dir": str(loaded.plan_dir),
        "tier": _tier_str(loaded.plan.tier),
        "target_env": loaded.target_env,
        "target_project": loaded.target_project,
        "human_gates": _stringify_gates(loaded.plan.human_gates),
        "agents_required": [str(a) for a in (loaded.plan.agents_required or [])],
        "feature_ids": [f.id for f in loaded.features.features],
    }


def tool_dispatch(args: dict[str, Any]) -> dict[str, Any]:
    """Mutating: wraps :func:`supervisor.dispatch_volley`. D004: defaults to
    dry-run; the dry-run output is structured (intent, not result). Caller
    must pass ``confirm: true`` to actually dispatch.

    Agent-facing reminder: surface the plan to the user before passing
    ``confirm: true`` (D007 / SAFETY_RULE_NO_AUTO_DISPATCH)."""
    inp = DispatchInput.model_validate(args)
    plan_dir = _resolve_safe_path(inp.plan)
    try:
        loaded = plan_loader.load(plan_dir)
    except (FileNotFoundError, ValueError) as exc:
        raise MCPError(
            ERR_INVALID_PARAMS,
            f"plan validation failed: {exc}",
            {"reason": "plan_validation_failed"},
        ) from exc

    intent = {
        "plan_id": loaded.plan_id,
        "plan_dir": str(loaded.plan_dir),
        "feature_id": inp.feature,
        "implementer": inp.implementer,
        "auditor": inp.auditor,
        "max_iterations": inp.max_iterations,
        "mode": inp.mode,
        "target_env": loaded.target_env,
        "target_project": loaded.target_project,
        "human_gates": _stringify_gates(loaded.plan.human_gates),
        "tier": _tier_str(loaded.plan.tier),
    }

    if not inp.confirm:
        return {
            "dry_run": True,
            "intent": intent,
            "message": (
                "dry-run; pass confirm=true to invoke supervisor.dispatch_volley. "
                "Always surface the plan to the user before confirming."
            ),
        }

    result = supervisor.dispatch_volley(
        plan_dir=plan_dir,
        feature_id=inp.feature,
        implementer_agent=inp.implementer,
        auditor_agent=inp.auditor,
        max_iterations=inp.max_iterations,
        mode=inp.mode,
    )
    return {
        "dry_run": False,
        "intent": intent,
        "result": {
            "final_status": result.final_status,
            "rounds": result.rounds,
            "reason": result.reason,
            "audit_paths": [str(p) for p in result.audit_paths],
        },
    }


def tool_status(args: dict[str, Any]) -> dict[str, Any]:
    """Read-only: live supervisor list + (optional) per-plan gate state."""
    inp = StatusInput.model_validate(args)
    out: dict[str, Any] = {
        "active_supervisors": [
            {
                "pid": e.pid,
                "plan_id": e.plan_id,
                "target_env": e.target_env,
                "target_project": e.target_project,
                "started_at": e.started_at,
                "supervisor_config_dir": e.supervisor_config_dir,
            }
            for e in active_supervisors.list_active()
        ],
    }
    if inp.plan is not None:
        plan_dir = _resolve_safe_path(inp.plan)
        loaded = plan_loader.load(plan_dir)
        declared = list(loaded.plan.human_gates or [])
        check = gate_pause.evaluate(plan_dir, declared)
        out["gate_status"] = {
            "plan_id": loaded.plan_id,
            "plan_dir": str(plan_dir),
            "paused": check.paused,
            "declared": list(check.declared),
            "cleared": list(check.cleared),
            "unmet": list(check.unmet),
        }
    return out


def tool_approve_gate(args: dict[str, Any]) -> dict[str, Any]:
    """Mutating: wraps :func:`gate_pause.approve_gate`. D004: dry-run by
    default; ``confirm: true`` is the only mutation path."""
    inp = ApproveGateInput.model_validate(args)
    plan_dir = _resolve_safe_path(inp.plan)
    loaded = plan_loader.load(plan_dir)
    is_cleared = gate_pause.is_gate_cleared(plan_dir, inp.gate)
    intent = {
        "plan_id": loaded.plan_id,
        "plan_dir": str(plan_dir),
        "gate": inp.gate,
        "currently_cleared": is_cleared,
        "would_clear": not is_cleared,
    }
    if not inp.confirm:
        return {
            "dry_run": True,
            "intent": intent,
            "message": "dry-run; pass confirm=true to clear the gate.",
        }
    changed = gate_pause.approve_gate(plan_dir, inp.gate, plan_id=loaded.plan_id)
    return {
        "dry_run": False,
        "intent": intent,
        "result": {"changed": changed},
    }


def tool_read_evidence(args: dict[str, Any]) -> dict[str, Any]:
    """Read-only: returns the contents of a file under the plan's evidence/
    tree. Path is constrained to ``<plan_dir>/evidence/`` (D005)."""
    inp = ReadEvidenceInput.model_validate(args)
    plan_dir = _resolve_safe_path(inp.plan)
    requested = _resolve_evidence_path(plan_dir, inp.file)
    return {
        "plan_id": plan_dir.name,
        "plan_dir": str(plan_dir),
        "file": str(requested.relative_to(plan_dir)),
        "content": requested.read_text(),
    }


# ──────────────────────────────  tool registry  ──────────────────────────────


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


def _build_tools() -> dict[str, ToolDef]:
    """Construct the canonical 6-tool surface. The order is preserved in
    ``tools/list`` responses and used by tests as the documented surface."""
    return {
        td.name: td
        for td in (
            ToolDef(
                name="list_projects",
                description=(
                    "Read-only. Return registered projects from ~/.dontpanic/projects.json."
                ),
                input_model=ListProjectsInput,
                handler=tool_list_projects,
            ),
            ToolDef(
                name="validate_plan",
                description=(
                    "Read-only. Load and validate a plan directory against "
                    "the agent-conventions v1.0 schema."
                ),
                input_model=ValidatePlanInput,
                handler=tool_validate_plan,
            ),
            ToolDef(
                name="dispatch",
                description=(
                    "Mutating. Dispatch an implementer/auditor volley for a "
                    "plan + feature. Defaults to dry-run; pass confirm=true "
                    "to actually invoke supervisor.dispatch_volley. Always "
                    "surface the plan to the user before confirming."
                ),
                input_model=DispatchInput,
                handler=tool_dispatch,
            ),
            ToolDef(
                name="status",
                description=(
                    "Read-only. Return active supervisors and (optionally) "
                    "gate state for a specific plan."
                ),
                input_model=StatusInput,
                handler=tool_status,
            ),
            ToolDef(
                name="approve_gate",
                description=(
                    "Mutating. Clear a single human gate on a plan. Defaults "
                    "to dry-run; pass confirm=true to mutate."
                ),
                input_model=ApproveGateInput,
                handler=tool_approve_gate,
            ),
            ToolDef(
                name="read_evidence",
                description=(
                    "Read-only. Return the contents of a file under the "
                    "plan's evidence/ directory. Path is constrained to "
                    "the plan's evidence tree; out-of-tree paths refuse."
                ),
                input_model=ReadEvidenceInput,
                handler=tool_read_evidence,
            ),
        )
    }


TOOLS: dict[str, ToolDef] = _build_tools()


def list_tool_names() -> list[str]:
    """Stable-ordered tool names. Order matches the documented surface."""
    return list(TOOLS.keys())


def tool_schema(name: str) -> dict[str, Any]:
    """JSON Schema for a tool's input arguments. Sourced from the Pydantic
    input model so the schema stays in lock-step with validation."""
    if name not in TOOLS:
        raise KeyError(name)
    return TOOLS[name].input_model.model_json_schema()


def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Top-level entry: route to the named tool, validate arguments, raise
    :class:`MCPError` for caller-visible failures. Tests call this directly
    rather than going through the JSON-RPC stdio loop."""
    td = TOOLS.get(name)
    if td is None:
        raise MCPError(
            ERR_METHOD_NOT_FOUND,
            f"unknown tool: {name!r}",
            {"available_tools": list_tool_names()},
        )
    try:
        return td.handler(arguments or {})
    except ValidationError as exc:
        raise MCPError(
            ERR_INVALID_PARAMS,
            f"invalid arguments for tool {name!r}: {exc.errors()}",
            {"validation_errors": exc.errors()},
        ) from exc
    except MCPError:
        raise
    except (FileNotFoundError, KeyError, ValueError, OSError, RuntimeError) as exc:
        raise MCPError(
            ERR_INTERNAL,
            f"tool {name!r} failed: {exc}",
            {"error_type": type(exc).__name__},
        ) from exc


# ──────────────────────────────  JSON-RPC handler  ──────────────────────────────


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _serialize_tools_for_list() -> list[dict[str, Any]]:
    return [
        {
            "name": td.name,
            "description": td.description,
            "inputSchema": td.input_model.model_json_schema(),
        }
        for td in TOOLS.values()
    ]


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch a single JSON-RPC request object. Returns the response dict,
    or ``None`` for notifications (which don't carry an ``id`` and produce
    no response per JSON-RPC 2.0)."""
    if not isinstance(message, dict):
        return _err(None, ERR_INVALID_REQUEST, "request must be a JSON object")
    method = message.get("method")
    params = message.get("params") or {}
    req_id = message.get("id")
    is_notification = "id" not in message

    if not isinstance(method, str):
        if is_notification:
            return None
        return _err(req_id, ERR_INVALID_REQUEST, "missing/invalid method")

    if method == "initialize":
        return _ok(
            req_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "dontpanic-mcp", "version": _server_version()},
            },
        )
    if method == "notifications/initialized":
        return None  # client confirms init; no response
    if method == "tools/list":
        return _ok(req_id, {"tools": _serialize_tools_for_list()})
    if method == "tools/call":
        if not isinstance(params, dict):
            return _err(req_id, ERR_INVALID_PARAMS, "params must be an object")
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            return _err(req_id, ERR_INVALID_PARAMS, "tools/call requires string 'name'")
        try:
            result = dispatch_tool(name, arguments if isinstance(arguments, dict) else {})
        except MCPError as exc:
            return _err(req_id, exc.code, exc.message, exc.data)
        # MCP tool result envelope: a list of content blocks. Use a single
        # JSON-text block — agent runtimes parse this back into a dict.
        return _ok(
            req_id,
            {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": False,
            },
        )

    if is_notification:
        return None
    return _err(req_id, ERR_METHOD_NOT_FOUND, f"unknown method: {method!r}")


def _server_version() -> str:
    from dontpanic_orchestrate import __version__

    return __version__


# ──────────────────────────────  stdio transport  ──────────────────────────────


def _configure_stderr_logging() -> None:
    """All server logs land on stderr. Stdout is reserved for the MCP
    JSON-RPC protocol stream — any stdout pollution would corrupt it. Tests
    parametric-assert this invariant via capsys."""
    if logging.getLogger().handlers:
        # Honor the caller's existing config (e.g. tests) — but make sure no
        # handler is attached to stdout. We don't reconfigure here.
        return
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="[%(asctime)s] %(name)s %(levelname)s %(message)s",
    )


def serve_stdio(
    *,
    stdin: Any | None = None,
    stdout: Any | None = None,
) -> int:
    """Run the JSON-RPC stdio loop. Reads one JSON message per line from
    stdin, writes one JSON response per line to stdout. Returns 0 on clean
    EOF.

    This is the only transport F002 ships. D003: stdio is local-only by
    construction — there is no socket bound to any interface."""
    _configure_stderr_logging()
    in_stream = stdin or sys.stdin
    out_stream = stdout or sys.stdout

    for raw_line in in_stream:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _err(None, ERR_PARSE, f"invalid JSON: {exc}")
            out_stream.write(json.dumps(response) + "\n")
            out_stream.flush()
            continue
        response = handle_request(message)
        if response is None:
            continue
        out_stream.write(json.dumps(response) + "\n")
        out_stream.flush()
    return 0


# ──────────────────────────────  CLI entrypoint  ──────────────────────────────


_SERVE_USAGE = (
    "usage: dontpanic mcp serve\n  starts a stdio MCP server exposing the F002 tool surface."
)


def serve_main(argv: list[str]) -> int:
    """Entry point for ``dontpanic mcp serve``. Stdio is the only supported
    transport in Phase B (D003 — local-only). A future remote-MCP plan
    will own the threat model + transport for non-loopback callers; until
    then, ``--remote``, ``--host``, ``--port`` are explicitly refused so a
    careless flag doesn't open a network listener."""
    forbidden_flags = {"--remote", "--host", "--port", "--bind", "--listen"}
    for arg in argv:
        if arg in forbidden_flags or any(
            arg.startswith(prefix + "=") for prefix in forbidden_flags
        ):
            print(
                f"[mcp serve] REFUSED flag {arg!r} — Phase B MCP is local-only "
                "(stdio). Remote transports are out of scope; see "
                "docs/plans/2026-05-03-003-feat-agent-access-manifest-thin-mcp/decisions.jsonl D003.",
                file=sys.stderr,
            )
            return 2
    if argv:
        print(
            f"[mcp serve] unknown arguments: {argv!r}\n{_SERVE_USAGE}",
            file=sys.stderr,
        )
        return 2
    return serve_stdio()


def main(argv: list[str]) -> int:
    """``dontpanic mcp <subcommand>`` dispatcher. ``serve`` is the only
    subcommand in Phase B; ``tools`` (introspection) is reserved for a
    future slice and intentionally not implemented here."""
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: dontpanic mcp serve\n  serve   start the local stdio MCP server",
            file=sys.stderr,
        )
        return 0 if argv else 2
    sub = argv[0]
    rest = argv[1:]
    if sub == "serve":
        return serve_main(rest)
    print(
        f"[mcp] unknown subcommand: {sub!r}\nusage: dontpanic mcp serve",
        file=sys.stderr,
    )
    return 2


__all__ = [
    "ApproveGateInput",
    "DispatchInput",
    "ERR_INTERNAL",
    "ERR_INVALID_PARAMS",
    "ERR_INVALID_REQUEST",
    "ERR_METHOD_NOT_FOUND",
    "ERR_PARSE",
    "ListProjectsInput",
    "MCP_PROTOCOL_VERSION",
    "MCP_SERVER_ARGS",
    "MCP_SERVER_COMMAND",
    "MCPError",
    "ReadEvidenceInput",
    "StatusInput",
    "TOOLS",
    "ToolDef",
    "ValidatePlanInput",
    "dispatch_tool",
    "handle_request",
    "list_tool_names",
    "main",
    "serve_main",
    "serve_stdio",
    "tool_approve_gate",
    "tool_dispatch",
    "tool_list_projects",
    "tool_read_evidence",
    "tool_schema",
    "tool_status",
    "tool_validate_plan",
]
