# DontPanic Discoverability Checklist

DontPanic should be easy for humans and agents to find, install, and call
without turning the project into a hosted service. This checklist is evidence
of readiness for a future public release; it is not a promise that every
external directory submission happens in this feature slice.

Safety rule for every agent caller:

**Always surface the plan to the user before calling dispatch(confirm=true). Do NOT auto-confirm.**

## Agent Manifest

- [x] `dontpanic manifest init` writes `~/.dontpanic/agent-manifest.json`.
- [x] The manifest advertises `dontpanic mcp serve` once the MCP server is
  importable.
- [x] The manifest contains the safety rule above.

## README Examples

- [x] README documents how Claude Code calls DontPanic.
- [x] README documents how Cursor calls DontPanic.
- [x] README documents how OpenClaw calls DontPanic.
- [x] README documents how Codex CLI calls DontPanic.
- [x] Each example shows discovery, MCP wiring, and a safe tool flow.
- [x] Each example keeps `dispatch(confirm=true)` behind user approval.

## MCP Client Snippet

Use this baseline when a runtime asks for an `mcp.json` block:

```json
{
  "mcpServers": {
    "dontpanic": {
      "command": "dontpanic",
      "args": ["mcp", "serve"]
    }
  }
}
```

## PyPI Readiness

- [ ] not yet submitted: package name reserved / published.
- [ ] not yet submitted: project description uses the DontPanic tagline.
- [ ] not yet submitted: project URLs point to GitHub, docs, SECURITY.md, and
  the roadmap.
- [ ] not yet submitted: install command documented as `pipx install
  dontpanic`.

## GitHub Readiness

- [x] repository description uses the DontPanic safety-layer positioning.
- [x] repository topics include `mcp-server`.
- [x] repository topics include `agent-orchestration`.
- [x] repository topics include `multi-agent`.
- [x] repository topics include `local-first`.
- [x] repository topics include `code-review`.
- [x] repository topics include `ai-agents`, `claude-code`, `codex`,
  `agent-governance`, and `ai-safety`.
- [ ] not yet submitted: README badges reflect package, tests, and security
  posture.

## MCP Directory Readiness

- [ ] not yet submitted: server name is `dontpanic`.
- [ ] not yet submitted: command is `dontpanic`.
- [ ] not yet submitted: args are `["mcp", "serve"]`.
- [ ] not yet submitted: tool list is exactly `list_projects`,
  `validate_plan`, `dispatch`, `status`, `approve_gate`, `read_evidence`.
- [ ] not yet submitted: directory copy states there is no `intake` tool in
  Phase B.

## Cross-References

- [README](../README.md) contains the runnable caller examples.
- [ECOSYSTEM.md](./ECOSYSTEM.md) explains who calls DontPanic and what
  DontPanic deliberately does not build.
- [ROADMAP.md](./ROADMAP.md) shows when the callable surfaces shipped and what
  remains deferred.
