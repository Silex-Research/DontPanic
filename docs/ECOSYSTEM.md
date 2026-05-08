# DontPanic in the Agent Ecosystem

DontPanic is not an agent runtime. It does not own channels, sessions,
chat surfaces, mobile presence, or plugin marketplaces. Those are
solved problems in mature systems like
[OpenClaw](https://github.com/openclaw/openclaw),
[Claude Code](https://claude.com/claude-code),
[Codex CLI](https://github.com/openai/codex),
[Cursor](https://cursor.sh), and Claude-managed agents.

**DontPanic is the verified software-delivery layer those systems call.**

> The safety layer between “the agent says it’s done” and “you merge it.”

> OpenClaw helps agents do things across your digital life.
> DontPanic helps agents ship software safely.

## Who calls DontPanic

| Caller | How it reaches DontPanic | Why |
|---|---|---|
| OpenClaw | A small DontPanic skill / plugin in the OpenClaw workspace shells out to `dontpanic intake | dispatch | status | approve` | OpenClaw owns the chat / channel / session surface; DontPanic owns plan-locked delivery |
| Claude Code | Claude reads `~/.dontpanic/agent-manifest.json` (Phase B; legacy `~/.jarvis` fallback) and invokes the CLI directly, or calls the MCP tools when `dontpanic mcp serve` is running | Claude already lives in the dev's terminal; DontPanic adds the verification loop |
| Codex CLI | Same pattern as Claude Code: read manifest, call CLI or MCP tools | Cross-vendor verification — Codex implements while Claude audits, or vice versa |
| Cursor / IDE plugins | MCP client → `dontpanic mcp serve` localhost | IDE owns editing UX; DontPanic adds plan/audit/evidence rigor |
| Claude-managed agents | Skill descriptor points at the global manifest; long-running tasks dispatched via `dontpanic dispatch-from-plan` | Managed agent owns scheduling + presence; DontPanic owns the delivery contract |
| ChatGPT / Grok / other LLMs | Output an LLM-authored plan dir (schema documented in README); `dontpanic plan validate` accepts it | Bridge from any LLM to verified delivery without per-vendor integration |
| Direct human operator | `dontpanic` CLI from a registered project | The original use case; everything else is a generalization |

## External adapter ecosystem

DontPanic can also consume service-specific tools as evidence providers,
as long as they enter through DontPanic's own contract: explicit
allowlisting, read-only defaults, pinned provenance, redaction, normalized
evidence, and human-visible signoff.

The current adapter direction is inspired by and explicitly credits
[CLI Printing Press](https://github.com/mvanhorn/cli-printing-press) and
the [Printing Press Library](https://github.com/mvanhorn/printing-press-library).
Printing Press generates agent-native CLIs and MCP servers around services
such as Linear, Sentry, Slack, and other APIs. DontPanic's planned use is
not to rebrand or absorb those tools; it is to treat them as external
capability providers whose outputs can be normalized into plan evidence.

Near-term integration stays conservative:

- skill applicability may record inert `external_cli` metadata so operators
  can see that a matched skill depends on an external adapter;
- no generated CLI is installed, invoked, or trusted during plan dispatch
  without a separate adapter-governance plan;
- future adapter plans own binary/version pinning, cache disposition,
  read-only policy, and evidence normalization.

## Safety rules for agent callers

Every agent runtime should treat DontPanic as a human-gated delivery system,
not a background deploy button.

- Always surface the plan to the user before calling dispatch(confirm=true). Do NOT auto-confirm.
- Use `validate_plan`, `status`, and dry-run `dispatch` output as the preview
  surface before asking for approval.
- Keep approval explicit. `dispatch(confirm=true)` and `approve_gate` are the
  point where the caller must have user intent.

## What this means for the build plan

- **Don't replicate runtime concerns.** No messaging channels, no
  personal-assistant personality, no mobile nodes, no full Gateway
  clone, no plugin marketplace as a near-term priority.
- **Build the callable surface, not the daemon.** Phase B
  ships `~/.dontpanic/agent-manifest.json` (global discovery: "how do I
  invoke DontPanic on this machine?") and a thin MCP server exposing
  `list_projects | validate_plan | dispatch | status | approve_gate | read_evidence`.
  There is deliberately no `intake` tool in Phase B — Phase C owns intake.
  This is enough for any of
  the above callers.
- **Project behavior stays in `<repo>/.dontpanic/dontpanic.json`.** The
  per-project config that Phase A's F003 landed answers "how should
  DontPanic operate in this project?" — committable, lives with the repo,
  read by the supervisor at dispatch time. Legacy
  `<repo>/.jarvis/jarvis.json` remains readable during migration.
- **No custom daemon until proven necessary.** Existing remote-agent
  infrastructure (Clawdbot-style runners, Claude dispatch, OpenClaw
  Gateway) already solves remote execution. DontPanic exposes a clean CLI
  + MCP surface; those systems handle reach.

## What DontPanic is NOT trying to be

- A chat interface
- A SaaS / hosted control plane
- A multi-channel messaging hub
- A general-purpose agent runtime
- A plugin marketplace
- A custom remote daemon
- "One more agent"
- An OpenClaw competitor

These are deliberate non-goals. Each one is a different product bet
that someone else is making well; DontPanic stays narrow on its
differentiator: plan-locked, multi-agent-verified, evidence-backed,
commit-ready software delivery.

## Concrete integration recipe (OpenClaw-as-caller, sketch)

The OpenClaw side authors a small skill. DontPanic ships nothing on
the OpenClaw runtime; it just exposes a stable CLI and (Phase B) a
manifest + MCP surface.

```text
# In the OpenClaw workspace, a skill named e.g. "dontpanic-delivery":
#
# When user says: "DontPanic, build the creator hub from this PRD"
# 1. Skill reads ~/.dontpanic/agent-manifest.json to find the dontpanic CLI
# 2. Skill calls: dontpanic manifest show --json
# 3. Skill calls the MCP validate_plan tool for an existing plan
# 4. Skill returns DontPanic's plan / validation / dry-run output to user
# 5. On approval: skill calls dispatch with confirm=true
# 6. Skill polls status and surfaces gate pauses to the user
```

That recipe is the **whole** OpenClaw integration. No SDK, no
embedded library, no Gateway-side state. The same recipe shape works
for any caller.

## Pointers

- [`PRODUCT.md`](./PRODUCT.md) — what DontPanic is in plain English
- [`ROADMAP.md`](./ROADMAP.md) — phased build plan with the ecosystem
  position explicit
- [`DISCOVERABILITY.md`](./DISCOVERABILITY.md) — publish-readiness and MCP
  client checklist
- [`PLATFORM.md`](./PLATFORM.md) — architectural thesis
