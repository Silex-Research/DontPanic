# Agent Quickstart

Agents should treat DontPanic as a local safety layer, not as permission to run
unreviewed work. The manifest is the first discovery surface:

```bash
dontpanic manifest show --json
```

The safety invariant is load-bearing:

> Always surface the plan to the user before calling dispatch(confirm=true). Do NOT auto-confirm.

## Minimal Flow

1. Read `~/.dontpanic/agent-manifest.json` or run `dontpanic manifest show --json`.
2. Validate the selected plan:

   ```bash
   python3 claude/shared/schemas/v1.0/validate.py docs/plans/<plan-id>/
   ```

3. Preview dispatch:

   ```bash
   dontpanic dispatch-from-plan <plan-id>
   ```

4. Show the user the plan, gates, agent roles, quota readiness, and target.
5. Only after explicit approval, run:

   ```bash
   dontpanic dispatch-from-plan <plan-id> --confirm
   ```

## MCP Shape

MCP-aware hosts can start the local server with:

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

The same approval rule applies through MCP: preview first, dispatch only after
the user approves `confirm=true`.

## What Not To Do

- Do not auto-lock, auto-dispatch, or auto-close plans without surfacing the
  decision to the user.
- Do not store API keys in DontPanic config. Store only role names, provider
  names, paths, or environment variable names.
- Do not treat a single model's success message as signoff. Let DontPanic write
  audit, evidence, and gate artifacts.
