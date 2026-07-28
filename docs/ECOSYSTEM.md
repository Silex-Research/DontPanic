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
| Buzz — **strongly recommended** | A thin Buzz agent / YAML workflow shells out to the DontPanic CLI (`buzz-cli` speaks JSON), or connects as an MCP client; the DontPanic notify sink posts event projections into the operator's **private** community (fail-soft when unconfigured) | Buzz owns rooms, agent keypairs, and membership; DontPanic owns plan-locked delivery. Signup + private-community setup are strongly recommended for every operator running multi-agent work — see [Buzz as caller and notify surface](#buzz-as-caller-and-notify-surface-strongly-recommended) |
| OpenCode | Operator / planning surface: the OpenCode session runs the DontPanic CLI directly, or connects as an MCP client to `dontpanic mcp serve` | OpenCode owns the planning and editing session; DontPanic owns plan-locked delivery. OpenCode operates DontPanic and is never dispatched — see the [Agent Capability Matrix](./AGENT_CAPABILITY_MATRIX.md) |
| Claude Code | Claude reads `~/.dontpanic/agent-manifest.json` and invokes the CLI directly, or calls the MCP tools when `dontpanic mcp serve` is running | Claude already lives in the dev's terminal; DontPanic adds the verification loop |
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
  per-project config answers "how should DontPanic operate in this project?"
  — committable, lives with the repo, and is read by the supervisor at
  dispatch time.
- **No custom daemon until proven necessary.** Existing remote-agent
  infrastructure (Clawdbot-style runners, Claude dispatch, OpenClaw
  Gateway) already solves remote execution. DontPanic exposes a clean CLI
  + MCP surface; those systems handle reach.

## What DontPanic is NOT trying to be

- A chat interface
- A SaaS / hosted control plane
- A multi-channel messaging hub
- A Nostr relay or embedded Buzz client
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

## Concrete integration recipe (OpenClaw-as-broker, notify-while-away)

The caller pattern above (interactive: user types in chat, skill calls
DontPanic, surfaces output back to chat) handles the at-keyboard case.
The broker pattern handles the **away-from-keyboard** case: a volley
running on the operator's laptop emits events while the human is on
their phone, and the human responds from chat.

```text
# In the OpenClaw workspace, a skill named e.g. "dontpanic-notification-router":
#
# Outbound (DontPanic → human):
# 1. Skill subscribes to DontPanic NotifyEvents — either:
#    (a) DontPanic webhook → local HTTP receiver in OpenClaw, OR
#    (b) OpenClaw watches `<plan>/INBOX.md` for new events (pull-based,
#        recommended — no port management, survives restarts).
# 2. Skill applies a routing policy table:
#      severity=info + kind in {volley_start, signoff} → Discord (project room)
#      severity=action_required                       → Discord + Telegram
#      severity=escalation                            → Telegram + WhatsApp mirror
# 3. Skill renders per channel (Discord embed, Telegram MarkdownV2, etc.)
#    and posts.
#
# Inbound (human → DontPanic):
# 4. Skill listens for messages in subscribed channels.
# 5. Author identity check against allowlist (Discord user-ID / Telegram
#    user-ID). Non-allowlisted senders silently ignored.
# 6. Parse intent: read-only commands (`/dp status`, `/dp inbox`,
#    `/dp dispatch --dry-run`) allowed in all channels; owner-only state
#    changes (`/dp approve`, `/dp resume`, `/dp dispatch --confirm`)
#    routed only via Telegram private DM (per personal-axiom plan
#    2026-05-03-002 D003+D004).
# 7. Skill calls the corresponding DontPanic MCP tool (approve_gate /
#    dispatch / status / read_evidence). Reply in the originating channel
#    with the result summary.
```

That's the broker. DontPanic is unchanged — same MCP surface, same
NotifyEvent emission. OpenClaw absorbs all per-channel knowledge
(Discord webhooks, Telegram bot API, WhatsApp business API) and all
routing policy. **The same broker pattern applies to Claude.ai managed
agents** (read DontPanic state via MCP, surface in Anthropic's
hosted-agent dashboards, approve via MCP) — different runtime, same
data flow. The OpenClaw adapter plan's F006 is the OpenClaw-specific
reference implementation.

**When to use which recipe:**
- Caller (interactive) — operator at keyboard, agent reads state during
  active session. No notifications needed.
- Broker (notify-while-away) — operator on phone or away from
  workstation, runtime brokers event flow + commands over chat /
  hosted-agent surface. Pick the broker host whose surface the operator
  will actually check (chat for OpenClaw; dashboard/email for
  Claude.ai managed agents).

## Buzz as caller and notify surface (strongly recommended)

[Buzz](https://buzz.xyz) ([block/buzz](https://github.com/block/buzz)) is a
Nostr relay workspace: agent keypairs, communities, channels, YAML workflows,
`buzz-cli` with JSON I/O, and an ACP harness. It complements DontPanic the
same way OpenClaw does — **room vs delivery contract**:

```text
Buzz / OpenCode  =  where humans + agents sit and approve
DontPanic        =  plan lock, volley, evidence, signoff
```

Buzz signup and setup are **strongly recommended** for every operator running
multi-agent work — not a hard dependency. DontPanic stays local-first and
offline-capable. The first-hour setup checklist lives in
[GETTING_STARTED § Buzz setup](./GETTING_STARTED.md#buzz-strongly-recommended-private-community-setup).

> **Integration status: doctor check and notify sink shipped.**
> The setup/doctor Buzz check reads `~/.dontpanic/buzz.json` and treats
> missing Buzz config as an advisory WARN with a fix path — never a hard
> fail (`DONTPANIC_SKIP_BUZZ=1` silences it for CI/headless runs). The
> notify sink posts plan events into your **private** community via the
> Buzz CLI (`buzz messages send`, with your private community's relay URL
> as `BUZZ_RELAY_URL` — the relay is the community authority), fail-soft:
> unconfigured Buzz or a missing `buzz` binary
> silently disables it — never an error, never a hard dependency. Posts
> are projections only (summaries, hashes, gate links); secrets, home
> paths, and full transcripts never reach a relay. The caller sketch
> below — a thin Buzz agent/workflow that shells out to the DontPanic
> CLI — remains the path for driving DontPanic *from* Buzz.

### Community model: private by default

| Community type | Who creates it | Use for | Do not use for |
|---|---|---|---|
| **Private operator community** (default) | Each user/team | Notify sink, gate requests, builder≠auditor agent membership, plan status | Public links with secrets |
| **Silex community** (exists; the maintainers' **private** dogfood) | Maintainer / Silex-Research | The maintainers' own private multi-agent work | Public support or discovery — it is not a public surface, and users are never asked to join it |
| **DontPanic public community** (optional, may exist later) | Product maintainers | Announcements, support, recipes, non-sensitive Q&A | Production gates, private plan evidence, API keys |
| **Self-hosted relay** | Operator | High-sensitivity / air-gapped / compliance work | Required for day-one tryout |

**Product rule: DontPanic never requires you to join or post into a
maintainer-owned community.** The private community you create is the default
work surface; the `~/.dontpanic/buzz.json` config that `dontpanic doctor`
checks always points at **your** community (relay URL + channel + reporter
key reference) — no default community URL is ever written for you, public
or otherwise. The only public
maintainer-owned surface is the optional DontPanic community, if and when it
exists — discovery and support only, never the notify default and never a
prerequisite for any DontPanic feature. The Silex community is not a public
support surface at all (see maintainer dogfood below).

**Self-host vs buzz.xyz:** the hosted buzz.xyz relay is fine for day-one
tryout because the delivery contract only ever posts **projections**
(summaries, hashes, gate links) — never secrets, full transcripts, or raw
audit JSON. For high-sensitivity, air-gapped, or compliance-bound work,
self-host the relay (or skip Buzz entirely; it is never required).

**Maintainer dogfood:** the Silex community exists and is the maintainers'
own **private** community — where they run their own private multi-agent
work, exactly as the private-community default recommends for every
operator. It is not a support channel and is never something users join. A
public DontPanic community is optional, may come later for
announcements/support, and is not the notify default.

### Identity mapping: builder key ≠ auditor key

Giving the implementer and the auditor separate Buzz agent keys makes the
cross-vendor split **legible in the room** — you can see which identity
posted which status. This is a legibility convention only: Buzz community
membership is not authorization. The harness registry (`AGENT_REGISTRY`) and
role config remain the sole source of truth for who can be dispatched and in
which role — see the [Agent Capability Matrix](./AGENT_CAPABILITY_MATRIX.md).

### Concrete integration recipe (Buzz-as-caller, sketch)

Parallel to the OpenClaw recipe above. The Buzz side is a thin agent /
workflow; DontPanic ships nothing on the Buzz runtime. The full
operator-followable version — MCP tool map, confirm-gated flow, safety
checklist, smoke checklist — is committed at
[`examples/buzz-caller/README.md`](../examples/buzz-caller/README.md).

```text
# In the Buzz workspace, an agent/workflow named e.g. "dontpanic-delivery":
#
# 1. Workflow reads ~/.dontpanic/agent-manifest.json to find the dontpanic CLI
# 2. Workflow calls: dontpanic manifest show --json (buzz-cli speaks JSON)
# 3. Workflow calls validate_plan / status / dry-run dispatch as the preview
#    surface and posts the preview into the private community channel
# 4. On explicit approval by an allowlisted human operator key:
#    workflow calls dispatch with confirm=true
# 5. Workflow polls status and posts gate pauses to the gates channel
#    (e.g. #dontpanic-gates)
# 6. Gate approval maps an allowlisted human action back to approve_gate —
#    reactions/emoji never auto-confirm
```

### Buzz non-goals (locked)

- **No relay or Nostr client inside DontPanic.** DontPanic shells out to
  `buzz-cli` / posts projections; it does not become a Buzz client, chat hub,
  or relay.
- **No forced join of maintainer-owned communities.** Neither the Silex
  community nor any public DontPanic community is ever required.
- **No auto-confirm from chat.** `dispatch --confirm` and `approve_gate`
  always require explicit, allowlisted human intent; message reactions and
  chat text never trigger them automatically.
- **No secrets on relays.** Channel posts carry projections only —
  summaries, hashes, gate links.

## Pointers

- [`PRODUCT.md`](./PRODUCT.md) — what DontPanic is in plain English
- [`ROADMAP.md`](./ROADMAP.md) — phased build plan with the ecosystem
  position explicit
- [`DISCOVERABILITY.md`](./DISCOVERABILITY.md) — publish-readiness and MCP
  client checklist
- [`PLATFORM.md`](./PLATFORM.md) — architectural thesis

## Adapter contract

If you're building anything that consumes DontPanic state — dashboards,
brokers, CI runners, hosted agents, multi-operator sync — read the
[State Projection adapter governance contract](./STATE_PROJECTION.md).
Four invariants every adapter must follow: stable-ID discipline,
schema-version pinning, redaction respect, no-write-back.
