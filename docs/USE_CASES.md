# DontPanic Use Cases

> What kind of operator/agent are you? What does DontPanic look like for
> you? What DontPanic features are required vs optional vs intentionally
> absent? This doc lets a human or agent see the matrix at a glance.

For the architectural why, see [`PLATFORM.md`](./PLATFORM.md). For the
phased build plan, see [`ROADMAP.md`](./ROADMAP.md). For per-knob
configuration, see [`CONFIGURATION.md`](./CONFIGURATION.md). For the
linear setup walkthrough by track, see
[`GETTING_STARTED.md` § Setup tracks](./GETTING_STARTED.md#setup-tracks--pick-yours).

## The architectural invariant

**Every use case is layered configuration on top of the same DontPanic
core.** A use case never modifies DontPanic; it composes existing
features. If a use case appears to require a DontPanic platform change,
that's a signal the change belongs in a separate platform plan — and
once it ships, the use case becomes pure configuration again.

DontPanic has one shape; use cases pick which optional layers to attach.

## At-a-glance matrix

| Use case | Required core | Optional core | Required external runtime | Human-engagement surface | Setup time |
|---|---|---|---|---|---|
| **U1. Solo dev — terminal-only** | core CLI, plan/gate/audit substrate | — | Claude / Codex / Gemini CLI (≥1) | Terminal + INBOX.md | ~10 min |
| **U2. Solo dev — Discord receive-only** | + notify_event surface | + Discord webhook sink | — | Discord channel (read-only) + terminal | +2 min |
| **U3. Interactive IDE agent (Claude Code, Cursor, Codex CLI)** | + MCP server + agent-manifest | — | One MCP-aware IDE/CLI | Active IDE session | ~5 min |
| **U4. Personal-axiom (operator + friends)** | + MCP server + NotifyEvent | + Discord webhook OFF | OpenClaw runtime + Discord/Telegram bots | Multi-channel chat (bidirectional) + dashboard (when F004 lands) | ~1-2 days |
| **U5. Hosted-agent flow (Claude.ai managed agent)** | + MCP server | — | Anthropic-hosted agent runtime | Claude.ai chat + dashboard/email | varies (Anthropic-side) |
| **U6. Team collaboration (multi-operator + shared dashboard)** | + MCP server + NotifyEvent + dashboard sync | + Firestore mirror of plan/gate/agent state | OpenClaw OR equivalent + Firebase/Firestore (`<firebase-project-id>`) | Kanban dashboard + chat + terminal | ~1 week |
| **U7. OSS contributor / forker** | core CLI + plan substrate | — (BYO agent CLIs) | — | Their own setup; DontPanic is a dep | ~10 min |

**Required core** = features that MUST be present. **Optional core** =
features in DontPanic that this use case may or may not enable.
**Required external runtime** = software the operator must install
themselves (DontPanic doesn't ship it).

---

## What's "DontPanic core" — the always-required substrate

Every use case requires this. It's the layer below all configuration:

- **Plan/feature/audit/signoff schemas** (agent-conventions v1.x via subtree).
- **Supervisor + dispatch_volley + dispatch_single_agent** loop.
- **Cross-vendor agent registry** (`claude`, `codex`; extensible).
- **Circuit breakers** (8 kinds, including `environmental_blocker`).
- **Gate-pause + reconciliation** (pre_impl, pre_merge, breaker:*, defer:*).
- **INBOX.md durable event log per plan** + signoff.json closeout.
- **Quota awareness** (caps, calibration, soft/hard enforcement).
- **`dontpanic doctor` preflight** + `dontpanic projects` registry.
- **Agent CLIs** the operator authenticates separately.

If a feature is in this list and we ever consider making it optional,
that's a signal we're carving out a profile — discuss it as a roadmap
question, not a use-case-side configuration.

---

## What's "DontPanic optional core" — wired only when a use case needs it

These are features inside the DontPanic repo that some use cases enable
and others don't:

| Feature | What it does | Enabled by | Use cases |
|---|---|---|---|
| `notify_discord` direct sink | POSTs NotifyEvents to a Discord webhook | `~/.dontpanic/discord.json` or `DONTPANIC_DISCORD_WEBHOOK_URL` | U2 (yes), U4 (no — broker absorbs), U6 (no — broker + dashboard) |
| `notify_event.dispatch_event` + NotifyEvent envelope | Channel-agnostic event surface for any broker to subscribe to | Always present; broker subscription configured externally | U2, U4, U5, U6 |
| MCP server (`dontpanic mcp serve`) | Typed tool surface for agents/brokers | Always available; clients opt in | U3, U4, U5, U6 |
| `~/.dontpanic/agent-manifest.json` | Agent discovery file | Always available; agents read it | U3, U4, U5 |
| Per-project `<repo>/.dontpanic/dontpanic.json` | Per-project agent/tier overrides | Operator opt-in via `dontpanic project config` | All when relevant |
| Goal Governance (sufficiency gate, completion audit) | Pre-impl / post-impl audit gates | Plan-driven (plan declares `goal_type`) | All |
| Skill applicability sidecar (advisory) | Plan-lock-time skill-compatibility hints | Plan-lock-time, advisory only | All |

**Nothing in this list is a "use-case fork" of DontPanic** — they're all
toggles operators configure externally. Adding a new use case never
requires forking the optional-core list.

---

## What's NOT in DontPanic and never will be

These are intentionally omitted — they belong to broker/runtime layers:

| Concern | Why it's not in DontPanic | Where it lives |
|---|---|---|
| Telegram bot integration | Channel adapter — broker domain | OpenClaw / Claude.ai managed agent / etc. |
| WhatsApp Business API | Same | OpenClaw |
| Slack integration | Same | OpenClaw or any future broker |
| Mobile push notifications | Hosted-runtime concern | Broker / hosted-agent runtime |
| Email notifications | Hosted-runtime concern | Hosted-agent runtime / SaaS adapter |
| Custom remote daemon (`dontpanic serve`) | Architecturally rejected per ROADMAP.md "no custom remote daemon" | n/a (replaced by Phase D ecosystem hooks) |
| Hosted control plane / SaaS UI | Architecturally rejected per PRODUCT.md positioning | n/a |
| Plugin marketplace | Architecturally rejected | n/a |
| Multi-tenant orchestration | Personal-first design | (Future plan if real demand emerges) |

---

## Per-use-case detail

### U1. Solo dev — terminal only

**Who:** A developer with `pipx`, a Claude or Codex CLI, and a project to ship.

**What they install:**
```zsh
pipx install dontpanic
dontpanic projects add myapp /path/to/myapp
dontpanic doctor
```

**Engagement surface:** terminal. INBOX.md is the durable record.
Operators read events as they happen, run `dontpanic approve` /
`dontpanic resume` directly.

**What this use case proves:** DontPanic is useful as a standalone tool,
zero broker required.

---

### U2. Solo dev — Discord receive-only notifications

**Adds to U1:**
- `~/.dontpanic/discord.json` with `webhook_url`, OR
- `DONTPANIC_DISCORD_WEBHOOK_URL` env var.

**Engagement surface:** Discord channel (read-only) + terminal for state
changes. Operator sees "volley_start", "breaker_tripped", "signoff" in
Discord; runs commands in terminal to act.

**Tradeoff:** zero-config vs no inbound commands. For inbound, jump to U4.

---

### U3. Interactive IDE agent (Claude Code, Cursor, Codex CLI, Continue)

**Who:** Solo or team dev using an MCP-aware IDE/CLI agent.

**Adds to U1:**
- IDE/CLI's MCP client config pointing at `dontpanic mcp serve` (the
  tool inventory is automatic; agents discover via `dontpanic manifest
  show --json`).

**Engagement surface:** the active IDE/CLI session. The agent reads
DontPanic state during your conversation; no notification broker needed
because you're already at the keyboard. Volley state surfaces in the
IDE/CLI naturally.

**No notification sink required** — this is the only use case where
DontPanic events don't need to leave the local machine.

---

### U4. Personal-axiom (operator + maybe friends)

**Who:** Operator who wants chat-shaped notify-while-away access. May
collaborate with friends running their own local DontPanics.

**Adds to U1:**
- OpenClaw runtime (`openclaw@2026.5.2` or later) installed locally.
- OpenClaw workspace bootstrap files (SOUL.md, AGENTS.md, TOOLS.md).
- OpenClaw skills:
  - `dontpanic-bridge` (F003 of plan `2026-05-03-002`) — narrow MCP wrapper
    enforcing allowlists.
  - `dontpanic-notification-router` (F006 of plan `2026-05-03-002`) —
    channel-agnostic event router.
- Discord/Telegram/WhatsApp credentials in `~/.openclaw/openclaw.json`.
- Discord/Telegram allowlists (operator user IDs).

**Disables in DontPanic:**
- The direct Discord webhook in `~/.dontpanic/discord.json` is REMOVED
  or unset. OpenClaw absorbs that delivery; per-channel routing is
  policy in OpenClaw, not in DontPanic.

**Engagement surface:** Discord (project coordination, read-only
commands like `/dp status`), Telegram private DM (owner approvals),
WhatsApp optional (notify-only mirror), terminal still available.

**This is plan `2026-05-03-002`'s scope.** The plan is 100% operator
configuration — no DontPanic core changes.

---

### U5. Hosted-agent flow (Claude.ai managed agents)

**Who:** Operator who lets Anthropic's hosted-agent runtime dispatch
work and surface state through Anthropic's UI.

**Adds to U1:**
- Claude.ai managed agent configured to run DontPanic via `dontpanic
  mcp serve` (locally) OR poll DontPanic state remotely if/when remote
  exposure is ever supported.
- Notification surface = Claude.ai's dashboard + email; no Discord /
  Telegram / WhatsApp needed.

**Engagement surface:** Claude.ai chat (operator types approval, agent
calls MCP). No chat-channel broker needed because the runtime owns its
own UI.

**Same broker pattern as U4, different runtime.** The plan-shape work
isn't drafted yet; will be a separate plan when an operator commits to
this track.

---

### U6. Team collaboration with shared dashboard

**Who:** Multiple operators on the same project (you + friends),
wanting a kanban-style shared progress view.

**Adds to U4:**
- Axiom dashboard (currently in `axiom/packages/dashboard/`) repointed
  at `<firebase-project-id>` Firestore.
- A sync layer (Cloud Function or background script) that mirrors local
  DontPanic state into Firestore:
  - Plan dirs → `plans` collection (one doc per plan, `status` =
    column).
  - `~/.dontpanic/active_supervisors.jsonl` → `agents` collection.
  - `INBOX.md` events → `activity` collection (last 50 newest-first).
  - `gate-state.json` aggregated → `approvals` collection (Security
    view's Approval Queue).
  - `~/.dontpanic/quota_state.json` → `metrics/tokens` doc.
  - `decisions.jsonl` → `decisions` collection.
- Drag-card-to-column → Cloud Function → MCP `approve_gate` /
  `dispatch` call (state-changing actions go through MCP, not direct
  Firestore writes).

**Engagement surface:** all of U4 + interactive Kanban board with
drag-and-drop status flow + Decision Audit Log + Approval Queue.

**Status:** F004 of plan `2026-05-03-002` is the entry point but is
significantly under-scoped today. The dashboard already has the right
*shape* (5 views, real-time Firestore subscriptions, kanban with DnD,
modal detail). What's missing: **the sync layer + repointing from
`<axiom-firebase-project-id>` to `<firebase-project-id>`.** This is high-leverage work
because it transforms the human-engagement surface from
"INBOX.md + chat" to "interactive board the whole team sees."

**Recommendation:** before doing F003 (bridge skill) or F006
(notification router), expand F004 with explicit sub-features for the
sync layer + Firestore schema. The dashboard is more valuable than the
chat broker for the operator+friends scenario.

---

### U7. OSS contributor / forker

**Who:** Anyone who clones DontPanic and uses it on their own repo.

**Adds to U1:** nothing. DontPanic is the dependency; the contributor
brings their own agents and projects.

**Notable:** sanitization invariants (no committed secrets, no Telegram
tokens, no Discord webhooks in repo) protect this case. The
sanitization scan added today (plan `2026-05-01-002` F004) catches
Discord webhook URLs.

---

## What this means for plan `2026-05-03-002`

The plan is currently labeled "Personal Axiom Runtime" and frames U4 as
a single scope. Per the matrix above, it actually spans **U4 + U6**
(personal-axiom chat + team-collaboration dashboard). Two clarifying
moves are worth considering:

1. **Confirm F004 dashboard scope.** What's currently in F004 is "repoint
   dashboard at DontPanic plan dirs + OpenClaw health summary" — but
   the actual gap is the sync-layer work (file artifacts → Firestore at
   `<firebase-project-id>`). Either expand F004's acceptance, or split it into a
   separate plan focused on team-dashboard sync.

2. **Confirm Firebase target.** The plan implicitly assumes
   `<firebase-project-id>` (now "DontPanic Firebase project" post-rename). The
   old `<axiom-firebase-project-id>` should be archived per D002. Worth a
   D-entry to make this explicit.

The architectural invariant holds: even after these clarifications,
plan `2026-05-03-002` remains 100% operator configuration. None of it
modifies DontPanic core.

---

## How an agent should use this doc

An MCP-aware agent reading this:

1. Identifies the operator's use case (ask, or infer from project shape).
2. Reads the matrix row for that use case.
3. Uses the "Required core" + "Optional core" columns to decide which
   DontPanic features must be enabled.
4. Uses the "Required external runtime" column to know what the
   operator needs to install (and whether the agent can install it).
5. Cross-references [`GETTING_STARTED.md` § Setup tracks](./GETTING_STARTED.md#setup-tracks--pick-yours)
   for the linear setup walkthrough.

Future enhancement: `dontpanic doctor --use-case=personal-axiom` could
verify each row's requirements programmatically.
