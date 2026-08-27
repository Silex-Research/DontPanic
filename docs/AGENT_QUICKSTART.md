# Agent Quickstart

Agents should treat DontPanic as a local safety layer, not as permission to run
unreviewed work. The manifest is the first discovery surface:

> **Brokering chat or hosted-agent surfaces? Don't build them into DontPanic.**
> If you're an MCP-aware runtime (OpenClaw, Claude.ai managed agents,
> Claude Code, Codex CLI, Cursor, Continue, custom MCP clients) and you
> want to bridge a chat channel OR a hosted-agent dashboard to DontPanic,
> the canonical pattern is: **subscribe to DontPanic NotifyEvents** (via
> webhook receiver, `INBOX.md` watcher, or `dontpanic status` polling),
> apply per-runtime routing on your side, and call DontPanic via the MCP
> tools below. DontPanic intentionally ships no Telegram/WhatsApp/Slack
> sinks and no hosted-agent integrations — those are your runtime's
> domain. The Discord direct sink in DontPanic is a no-broker solo-dev
> convenience only.
>
> **Reference implementations + setup paths:**
> - Plan [`2026-05-03-002-infra-personal-openclaw-axiom-jarvis`](../docs/plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/) F006 — OpenClaw broker (multi-channel chat).
> - [`ECOSYSTEM.md`](./ECOSYSTEM.md) — caller-pattern recipes + DontPanic's place in the agent ecosystem.
> - [`GETTING_STARTED.md` § Setup tracks](./GETTING_STARTED.md#setup-tracks--pick-yours) — picks the right runtime track for the operator's deployment.
> - [`CONFIGURATION.md`](./CONFIGURATION.md) — every operator-facing knob the broker may need to honor.

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

Sit Grok Bot, Hermes, OpenClaw, or a thin CLI watcher on `dontpanic approve` and `dontpanic dispatch-from-plan`. Clipboard paste between Claude and Codex is a fallback, not the product.

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

## Adapter contract

If you're building anything that consumes DontPanic state — dashboards,
brokers, CI runners, hosted agents, multi-operator sync — read the
[State Projection adapter governance contract](./STATE_PROJECTION.md).
Four invariants every adapter must follow: stable-ID discipline,
schema-version pinning, redaction respect, no-write-back.
