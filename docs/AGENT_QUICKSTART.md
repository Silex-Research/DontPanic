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

An explicit authorization can cover implementation of a whole bounded plan,
including continued dispatch and correction passes. Record its scope, budget,
target environment, and reserved human decisions in the plan's decisions before
starting. Continued work within that authorization does not need a new request
after every worker stop. Changes outside it require a new decision.

## Autonomous operation

An operator agent is optional. A human can use the CLI directly; Grok Bot,
OpenClaw, Hermes, or another CLI/MCP caller can take over day-to-day
administration. DontPanic supplies the supervised implementation-and-audit loop.
The calling runtime supplies the operator's persistence, scheduling, remote
access, and notifications.

For a well-developed, authorized plan, the operator can advance work through
implementation, correction, independent review, verification, and close-out
without a human relaying messages or restarting every step. Prepare the outcome,
acceptance criteria, feature dependencies, checkout, environment, tools, proof,
and budget first. Decide which actions are delegated and which remain human gates.

After each worker stop:

1. Inspect the selected feature's audit, transcript, signoff, and evidence.
   Read `INBOX.md` for the stop reason. Do not treat a CLI exit code alone as
   successful implementation.
2. Use `dontpanic what-now <plan> --feature F001` for feature guidance and
   `dontpanic next --format=json` for repo-level readiness. Neither takes the
   place of checking the acceptance criteria and required proof.
3. Continue the indicated correction or next ready feature within the existing
   authorization. Use explicit feature IDs and the intended checkout on every
   dispatch. The supervisor already passes findings between workers.
4. Clear only a specific gate whose decision has been authorized. A gate
   reserved for human judgment still needs that judgment. Honor circuit
   breakers; surface a scope, budget, credential, or environment blocker when
   you cannot resolve it within the authorization.
5. If further execution is indicated, re-dispatch. If signoff is complete,
   follow the close-out guidance and verify the feature's recorded status.
   Close the plan only when its required outcomes and proof are satisfied.

Keep the user informed at useful milestones: a feature completed, a concrete
decision needed, or a blocker that cannot be resolved autonomously. Active
workers may be quiet while thinking or building; follow evidence of progress
before interrupting them.

An execution host must have the tools needed for the promised proof. For
example, an operator running on Linux needs access to a Mac for Xcode builds
and iOS Simulator work. Keep durable checkouts and use Git to transfer source
and committed receipts. Machine-local credentials, paths, active processes,
and breaker history do not move with a Git push.

## Gate clearance and continuation

`dontpanic approve <plan> <gate>` and `dontpanic resume <plan> --gate <gate>`
clear a gate. They do not restart execution. Once a pending gate is authorized,
clear it and re-dispatch only when more execution is required:

```bash
dontpanic approve <plan> <pending-gate>
dontpanic dispatch-from-plan <plan> --feature F001 --confirm
```

The angle-bracket values are placeholders; substitute the actual plan and gate.
`resume --all` explicitly clears the declared gate set, so it is not a routine
restart command. A signed-off feature may need close-out rather than another
paid implementation pass.

## Minimal Flow

1. Read `~/.dontpanic/agent-manifest.json` or run `dontpanic manifest show --json`.
2. Validate the selected plan:

   ```bash
   python3 claude/shared/schemas/v1.0/validate.py docs/plans/<plan-id>/
   ```

3. Preview dispatch:

   ```bash
   dontpanic dispatch-from-plan <plan-id> --feature F001
   ```

4. Show the user the plan, gates, agent roles, quota readiness, and target.
5. Only after explicit approval, run:

   ```bash
   dontpanic dispatch-from-plan <plan-id> --feature F001 --confirm
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

The same approval rule applies through MCP: preview first, dispatch only under
the user's explicit authorization. Use the feature field exposed by the
installed server's dispatch tool schema for feature selection.

## What Not To Do

- Do not lock, dispatch, or close outside the authorization surfaced to the
  user. A reserved human gate is not delegated merely because the caller is an agent.
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

## Client recipes

### Claude Code

Add DontPanic as a local MCP server, then ask Claude to validate or dispatch a
registered plan. Claude must show the plan and obtain authorization before
passing `confirm=true`; that authorization may cover the full bounded workflow.

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

Example tool flow:

```text
1. call dontpanic.list_projects
2. call dontpanic.validate_plan with {"plan": "2026-05-03-003-feat-agent-access-manifest-thin-mcp"}
3. show the validation result and dispatch preview to the user
4. only after approval, call dontpanic.dispatch with {"plan": "...", "confirm": true}
```

### Cursor

Use the same local MCP process in Cursor's MCP settings. Cursor owns the IDE
experience; DontPanic owns plan validation, gates, evidence, and signoff.

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

Example tool flow:

```text
1. call dontpanic.validate_plan for the selected plan
2. call dontpanic.status to see active gates and signoff state
3. never call dontpanic.dispatch with confirm=true until the user approves
```

### OpenClaw

OpenClaw should treat DontPanic as a callable software-delivery skill, not a
runtime competitor. The OpenClaw skill reads `~/.dontpanic/agent-manifest.json`,
starts the local MCP server, and forwards plan and gate updates back to the user.

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

Example tool flow:

```text
1. read ~/.dontpanic/agent-manifest.json or call dontpanic manifest show --json
2. call dontpanic.validate_plan for the plan OpenClaw is about to run
3. surface the plan and gates in the OpenClaw conversation
4. call dontpanic.dispatch only after explicit user approval
```

### Codex CLI

Codex can shell out to the CLI today and use the same MCP shape inside an
MCP-aware host. The cross-vendor pattern is the common one: one model implements,
another audits, and DontPanic records the evidence.

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

Example tool flow:

```text
1. run dontpanic manifest show --json to discover the local command
2. call dontpanic.validate_plan or run dontpanic dispatch-from-plan <plan-id> --feature F001
3. show the dry-run/preflight output to the user
4. dispatch only when the user authorizes confirm=true
```
