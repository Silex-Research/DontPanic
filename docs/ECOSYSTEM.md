# Jarvis in the Agent Ecosystem

Jarvis is not an agent runtime. It does not own channels, sessions,
chat surfaces, mobile presence, or plugin marketplaces. Those are
solved problems in mature systems like
[OpenClaw](https://github.com/openclaw/openclaw),
[Claude Code](https://claude.com/claude-code),
[Codex CLI](https://github.com/openai/codex),
[Cursor](https://cursor.sh), and Claude-managed agents.

**Jarvis is the verified software-delivery layer those systems call.**

> OpenClaw helps agents do things across your digital life.
> Jarvis helps agents ship software safely.

## Who calls Jarvis

| Caller | How it reaches Jarvis | Why |
|---|---|---|
| OpenClaw | A small Jarvis skill / plugin in the OpenClaw workspace shells out to `jarvis intake | dispatch | status | approve` | OpenClaw owns the chat / channel / session surface; Jarvis owns plan-locked delivery |
| Claude Code | Claude reads `~/.jarvis/agent-manifest.json` (Phase B) and invokes the CLI directly, or calls the MCP tools when `jarvis mcp serve` is running | Claude already lives in the dev's terminal; Jarvis adds the verification loop |
| Codex CLI | Same pattern as Claude Code: read manifest, call CLI or MCP tools | Cross-vendor verification — Codex implements while Claude audits, or vice versa |
| Cursor / IDE plugins | MCP client → `jarvis mcp serve` localhost | IDE owns editing UX; Jarvis adds plan/audit/evidence rigor |
| Claude-managed agents | Skill descriptor points at the global manifest; long-running tasks dispatched via `jarvis dispatch-from-plan` | Managed agent owns scheduling + presence; Jarvis owns the delivery contract |
| ChatGPT / Grok / other LLMs | Output an LLM-authored plan dir (schema documented in README); `jarvis plan validate` accepts it | Bridge from any LLM to verified delivery without per-vendor integration |
| Direct human operator | `jarvis` CLI from a registered project | The original use case; everything else is a generalization |

## What this means for the build plan

- **Don't replicate runtime concerns.** No messaging channels, no
  personal-assistant personality, no mobile nodes, no full Gateway
  clone, no plugin marketplace as a near-term priority.
- **Build the callable surface, not the daemon.** Phase B
  ships `~/.jarvis/agent-manifest.json` (global discovery: "how do I
  invoke Jarvis on this machine?") and a thin MCP server exposing
  `intake | dispatch | status | approve` — that's enough for any of
  the above callers.
- **Project behavior stays in `<repo>/.jarvis/jarvis.json`.** The
  per-project config that Phase A's F003 landed answers "how should
  Jarvis operate in this project?" — committable, lives with the repo,
  read by the supervisor at dispatch time.
- **No custom daemon until proven necessary.** Existing remote-agent
  infrastructure (Clawdbot-style runners, Claude dispatch, OpenClaw
  Gateway) already solves remote execution. Jarvis exposes a clean CLI
  + MCP surface; those systems handle reach.

## What Jarvis is NOT trying to be

- A chat interface
- A SaaS / hosted control plane
- A multi-channel messaging hub
- A general-purpose agent runtime
- A plugin marketplace
- A custom remote daemon
- "One more agent"
- An OpenClaw competitor

These are deliberate non-goals. Each one is a different product bet
that someone else is making well; Jarvis stays narrow on its
differentiator: plan-locked, multi-agent-verified, evidence-backed,
commit-ready software delivery.

## Concrete integration recipe (OpenClaw-as-caller, sketch)

The OpenClaw side authors a small skill. Jarvis ships nothing on
the OpenClaw runtime; it just exposes a stable CLI and (Phase B) a
manifest + MCP surface.

```text
# In the OpenClaw workspace, a skill named e.g. "jarvis-delivery":
#
# When user says: "Jarvis, build the creator hub from this PRD"
# 1. Skill reads ~/.jarvis/agent-manifest.json to find the jarvis CLI
# 2. Skill calls: jarvis intake prd <path> --project creator-hub --json
# 3. Skill returns Jarvis's plan / questions / discovery output to user
# 4. On approval: jarvis dispatch-from-plan <plan-id> --confirm
# 5. Skill polls: jarvis status <plan-id> --json
# 6. On gate pause: skill surfaces the gate to user, calls jarvis approve
```

That recipe is the **whole** OpenClaw integration. No SDK, no
embedded library, no Gateway-side state. The same recipe shape works
for any caller.

## Pointers

- [`PRODUCT.md`](./PRODUCT.md) — what Jarvis is in plain English
- [`ROADMAP.md`](./ROADMAP.md) — phased build plan with the ecosystem
  position explicit
- [`PLATFORM.md`](./PLATFORM.md) — architectural thesis
