# DontPanic Configuration

> Everything you can configure, where the knobs live, and how a human or
> agent can discover what's available in 30 seconds.

This document is the operator-facing inventory. For the architectural why,
see [`PLATFORM.md`](./PLATFORM.md). For the long-form roadmap, see
[`ROADMAP.md`](./ROADMAP.md). For the recommended **setup order across
optional layers**, see [`GETTING_STARTED.md` § Setup tracks](./GETTING_STARTED.md#setup-tracks--pick-yours).

## Setup order (the short version)

Each layer assumes the one above is already in place — don't skip ahead:

1. **DontPanic core** (required) — `pipx install`, `dontpanic doctor`, register a project.
2. **Notification sink** (optional) — pick one of three:
   - **Direct Discord webhook** (zero-config, no broker needed): set `DONTPANIC_DISCORD_WEBHOOK_URL` or `~/.dontpanic/discord.json`. Receive-only; you respond from terminal. Best for solo dev who doesn't run a chat or hosted-agent runtime.
   - **OpenClaw broker** (multi-channel chat: Discord/Telegram/WhatsApp): see plan `2026-05-03-002` F006. Skip the direct webhook — point DontPanic at OpenClaw's local receiver, OR have OpenClaw watch `INBOX.md`.
   - **Claude.ai managed-agent broker** (cloud dispatch + dashboard/email surfaces): the managed agent reads DontPanic state via MCP polling or `INBOX.md` watching, surfaces blockers in Claude.ai's UI, and approves via MCP `approve_gate`. Same pattern, different runtime.
   - **No broker, interactive only**: if you're using Claude Code, Cursor, Codex CLI, or Continue at the keyboard, skip notifications entirely. The agent reads DontPanic state via MCP during your active session — there's nowhere to "notify" you that you aren't already.
3. **Per-project tuning** (optional) — `<repo>/.dontpanic/dontpanic.json` overrides global agents, tier, plans_dir.
4. **Quota caps** (optional) — `~/.dontpanic/quota_caps.json` for per-vendor weekly token caps.

The architectural invariant: any MCP-aware runtime can be the broker. DontPanic
ships only the direct Discord webhook because it's the no-broker zero-config
case. Telegram, WhatsApp, Slack, hosted-agent dashboards, and email are all
intentionally **not** built into DontPanic — the broker absorbs that domain.

### Dataflow per track (visual)

```
TRACK 1 — Solo dev, terminal only
─────────────────────────────────
   ┌──────────┐                        ┌─────────┐
   │ DontPanic│ ──── INBOX.md ─────►   │Operator │
   │  volley  │ ──── stderr   ─────►   │(at term)│
   └──────────┘                        └─────────┘
   • Operator reads stderr / INBOX during volley
   • Approves via:  dontpanic approve <plan> <gate>


TRACK 2 — Solo dev + Discord webhook (no broker)
──────────────────────────────────────────────────
   ┌──────────┐                  ┌──────────┐         ┌─────────┐
   │ DontPanic│ ──webhook POST►  │ Discord  │ ──────► │Operator │
   │  volley  │   (receive-only) │ channel  │         │(reads)  │
   │          │                  └──────────┘         └─────────┘
   │          │                                            │
   │          │◄───────── dontpanic approve ───────────────┘
   └──────────┘                  (operator runs command in terminal)
   • DontPanic → Discord = outbound only
   • Approvals = terminal-only (no inbound from Discord)


TRACK 3a — OpenClaw broker (multi-channel, bidirectional)
──────────────────────────────────────────────────────────
   ┌──────────┐                  ┌──────────────┐
   │ DontPanic│ ─event stream──► │ OpenClaw     │
   │  volley  │  (INBOX.md       │ broker skill │
   │          │   watcher OR     │              │
   │          │   local webhook) │  routing     │
   │          │                  │  policy      │
   │          │                  └──────┬───────┘
   │          │                         │
   │          │                ┌────────┼────────┐
   │          │                ▼        ▼        ▼
   │          │             Discord  Telegram WhatsApp
   │          │                ▲        ▲        ▲
   │          │                │        │        │
   │          │                └────────┴────────┘
   │          │                         │
   │          │                ┌────────┴────────┐
   │          │◄── MCP call ── │ Operator-typed  │
   │          │   (approve_gate│ command in any  │
   │          │    / dispatch  │ channel         │
   │          │    / status)   └─────────────────┘
   └──────────┘
   • Per-channel routing in OpenClaw policy (severity → channel set)
   • Owner-only state changes gated to Telegram private DM


TRACK 3b — Claude.ai managed-agent broker (hosted)
────────────────────────────────────────────────────
   ┌──────────┐                  ┌────────────────┐
   │ DontPanic│ ─event stream──► │ Claude.ai      │
   │  volley  │  (MCP polling    │ managed agent  │
   │          │   OR file watch) │                │
   │          │                  └───────┬────────┘
   │          │                          │
   │          │                  ┌───────▼────────┐
   │          │                  │ Claude.ai chat │
   │          │                  │ + dashboard +  │
   │          │                  │ email surfaces │
   │          │                  └───────┬────────┘
   │          │                          ▲
   │          │                          │
   │          │◄── MCP call ── (operator approves via Claude.ai chat)
   └──────────┘
   • No Discord/Telegram/WhatsApp involved
   • Anthropic owns the notification surface


TRACK 3c — Interactive IDE/CLI (Claude Code, Cursor, Codex CLI)
───────────────────────────────────────────────────────────────
   ┌──────────┐                  ┌────────────────┐
   │ DontPanic│ ◄── MCP ───────► │ IDE/CLI agent  │
   │  volley  │   (live during   │ in operator's  │
   │          │    session)      │ active session │
   └──────────┘                  └────────────────┘
   • No notifications — operator already at keyboard
   • Agent reads state, surfaces via IDE/terminal UI
```

**Common shape:** DontPanic emits events through its single MCP/webhook
surface; the broker (or interactive runtime) absorbs that surface and shapes it
for the operator. DontPanic doesn't grow per-channel knowledge; brokers don't
duplicate volley orchestration.

## What's available — at a glance

| Surface | Default | Configurable | Reference |
|---|---|---|---|
| **Agents (models)** | `claude`, `codex` | Yes — agent registry | [Agents](#agents-models) |
| **Implementer/auditor pair** | `claude` impl + `codex` aud | Per-plan or global | [Agent pairing](#agent-pairing) |
| **Notification sinks** | terminal (macOS) | Discord webhook (optional) | [Notifications](#notifications) |
| **Quota awareness** | per-vendor weekly caps | `~/.dontpanic/quota_caps.json` | [Quota](#quota--caps) |
| **Circuit breakers** | 8 kinds, all on | Cleared via `dontpanic approve` | [Breakers](#circuit-breakers) |
| **Project registry** | `~/.dontpanic/projects.json` | `dontpanic projects add` | [Projects](#project-registry) |
| **Per-project config** | `<repo>/.dontpanic/dontpanic.json` | Hand-edit per project | [Per-project](#per-project-config) |
| **Plan validation** | agent-conventions v1.x schemas | Schemas live in `claude/shared/schemas/` | [Plans](#plans) |
| **Run mode** | autonomous | `interactive` or `--mode=...` | [Run mode](#run-mode) |

## Quick start — everything in one config

A minimal `~/.dontpanic/config.json` covers the global knobs:

```json
{
  "agents": { "default_implementer": "claude", "default_auditor": "codex" },
  "tier": "trivial",
  "notification_level": "normal"
}
```

A minimal `~/.dontpanic/discord.json` enables Discord:

```json
{ "webhook_url": "https://discord.com/api/webhooks/<id>/<token>" }
```

A minimal `<repo>/.dontpanic/dontpanic.json` for a project that overrides
the global agent pair:

```json
{ "agents": { "implementer": "claude", "auditor": "codex" } }
```

The rest of this document explains each knob.

---

## Agents (models)

The supervisor dispatches **two cross-vendor agents per volley** — one
implementer, one auditor (per plan 2026-04-19-001 F005 and the cross-vendor
adversarial design).

**Currently supported agents:**

| Agent | Vendor | Surface |
|---|---|---|
| `claude` | Anthropic | Claude Code CLI |
| `codex` | OpenAI | Codex CLI |

These are the names used throughout `agents_required:` in plan frontmatter
and `--implementer / --auditor` flags on `dontpanic dispatch`. The
canonical source of truth is `scripts/dontpanic_orchestrate/executors/__init__.py:15`.

> **Adding a model:** drop a new executor class under
> `scripts/dontpanic_orchestrate/executors/` extending `BaseExecutor`,
> register it in `AGENT_REGISTRY`, and add a quota_caps entry. No
> agent-conventions schema bump required.

### Agent pairing

The supervisor's two-agent assignment resolves in this order at dispatch:

1. **Plan frontmatter** — `agents_required: [<impl>, <aud>]` if the plan
   names them.
2. **CLI flags** — `--implementer <agent> --auditor <agent>` overrides the plan.
3. **Per-project config** — `<repo>/.dontpanic/dontpanic.json` →
   `agents.implementer` / `agents.auditor`.
4. **Global config** — `~/.dontpanic/config.json` →
   `agents.default_implementer` / `agents.default_auditor`.
5. **Hardcoded fallback** — `claude` impl + `codex` aud.

The cross-vendor invariant is policy: **no plan should pair the same
vendor with itself** (auditor blindness — the same model that wrote the
diff is the worst possible reviewer). The supervisor refuses
same-vendor pairings unless explicitly overridden via D006-style
operator decision.

---

## Notifications

Two sinks ship; neither is required. The durable record is always
`<plan_dir>/INBOX.md` — the sinks are live signals.

### Terminal (macOS)

`terminal-notifier` if installed. macOS-only. Silent on Linux/CI.

| Knob | Where | Effect |
|---|---|---|
| `JARVIS_NOTIFY_DISABLE=1` | env | Silences ALL sinks (terminal + Discord) |

### Discord (cross-machine)

Posts the same events to a Discord webhook. Modern brand wins on
conflict; legacy `JARVIS_*` env vars stay readable.

| Knob | Where | Effect |
|---|---|---|
| `DONTPANIC_DISCORD_WEBHOOK_URL` | env | Modern: webhook URL |
| `JARVIS_DISCORD_WEBHOOK_URL` | env | Legacy fallback |
| `~/.dontpanic/discord.json` `webhook_url` | file | Modern: webhook URL |
| `~/.jarvis/discord.json` `webhook_url` | file | Legacy fallback |
| `DONTPANIC_DISCORD_DISABLE=1` | env | Discord-only kill switch |
| `JARVIS_DISCORD_DISABLE=1` | env | Legacy Discord kill switch |
| `DONTPANIC_NOTIFY_LEVEL` | env | `quiet` / `normal` / `verbose` |
| `JARVIS_NOTIFY_LEVEL` | env | Legacy notify level |

**Level matrix:**

- `quiet` — escalation events only (cap hit, breaker tripped, calibration
  required).
- `normal` (default) — escalation + action_required + plan-boundary kinds
  (`volley_start`, `volley_terminal`, `signoff`).
- `verbose` — every event.

**Emit points (which events Discord sees):** volley_start, gate_paused,
breaker_tripped, signoff, calibration_required. Each one writes to
INBOX.md FIRST, then fires the sinks. If Discord is silent, the durable
record is unaffected.

**Security:** webhook URLs never appear in committed code. The pattern
`https://discord(app)?.com/api/webhooks/<id>/<token>` is in
`scripts/sanitization_check.py` so any accidental commit fails the
preflight.

---

## Quota & caps

Every dispatch checks weekly token usage against per-vendor caps.

| Surface | Path | Notes |
|---|---|---|
| Per-vendor caps | `~/.dontpanic/quota_caps.json` | `{claude: {weekly: ...}}`; tier-aware |
| Live quota state | `~/.dontpanic/quota_state.json` | Updated by `dontpanic quota-check` |
| Calibration sample | `~/.dontpanic/quota_state.json` `claude.calibration` | Run `dontpanic calibrate-claude --window weekly --dashboard-pct N` |

| Env knob | Effect |
|---|---|
| `JARVIS_QUOTA_ENFORCE=hard` | Halt at threshold (vs default `soft` warn) |
| `JARVIS_QUOTA_DEFER_THRESHOLD=80` | Override default 90% defer threshold |
| `JARVIS_QUOTA_STATE_PATH=...` | Test isolation |
| `JARVIS_QUOTA_CAPS_PATH=...` | Test isolation |

A volley near the cap fires `breaker:budget_ceiling` — operator clears
via `dontpanic approve <plan> breaker:budget_ceiling` after either
calibrating or topping up.

---

## Circuit breakers

Eight kinds. Six fall through the pause-for-approval flow; the **global
breaker** is hard stop (24h window, no operator clearance).

| Breaker | Trips when | Approval needed |
|---|---|---|
| `iteration_cap` | `max_iterations` reached without signoff | Yes |
| `budget_ceiling` | Per-agent quota cap exceeded | Yes |
| `wall_clock` | Volley exceeds wall-clock budget | Yes |
| `no_progress` | Auditor verdict unchanged across rounds | Yes |
| `diminishing_returns` | Findings reduction stalled | Yes |
| `convergence_collapse` | Same finding signature recurring | Yes |
| `environmental_blocker` | Round-0 env-only auditor finding | Yes |
| `global_circuit_breaker` | 3 hard cap-hits in 24h across plans | **No — hard stop** |

Operator clearance:

```bash
# Clear one breaker on one plan
dontpanic approve <plan-id> breaker:no_progress

# Clear all approval-required breakers + gates on one plan
dontpanic resume <plan-id> --all
```

Breaker history lives at `~/.dontpanic/breaker_history.jsonl` — append-only.

---

## Project registry

`dontpanic projects` is the multi-project registry (Phase A, plan 2026-05-03-001).

```bash
# What's registered?
dontpanic projects list

# Register a new project
dontpanic projects add <name> <path>

# Show one project's config
dontpanic projects show <name>

# Per-project preflight (paths / agents / gates / dontpanic.json validity)
dontpanic doctor <name>
```

Backing file: `~/.dontpanic/projects.json` (legacy `~/.jarvis/projects.json`
fallback).

---

## Per-project config

Each registered project may carry a `<repo>/.dontpanic/dontpanic.json`:

```json
{
  "agents": { "implementer": "claude", "auditor": "codex" },
  "tier": "trivial",
  "plans_dir": "docs/plans"
}
```

Override precedence at dispatch time: **per-project > global > hardcoded
fallback** (per plan 2026-05-03-001 D004).

The legacy `<repo>/.jarvis/jarvis.json` shape stays readable — operators
don't have to migrate.

---

## Plans

Plans are directories under `docs/plans/<id>/` containing:

| File | Purpose | Schema |
|---|---|---|
| `plan.md` | YAML frontmatter + thesis + scope | `claude/shared/schemas/v1.x/plan.schema.json` |
| `features.json` | Feature list with acceptance + passes | `features.schema.json` |
| `decisions.jsonl` | Append-only D-entry log | (no schema; conventional shape) |
| `audit/` | Per-feature auditor envelopes | `audit-envelope.schema.json` |
| `evidence/` | Artifacts referenced by features | (free-form) |
| `signoff.json` | Closeout verdict (written by supervisor) | `signoff.schema.json` |

The agent-conventions repo at
[`$HOME/Documents/GitHub/agent-conventions/`](../../agent-conventions)
is the source of truth for schemas and is consumed via git subtree.

For plan authoring, see [`AUTHORING_PLANS.md`](./AUTHORING_PLANS.md).

---

## Run mode

Three dispatch classes:

| Mode | When to use | Knob |
|---|---|---|
| `autonomous` | Default — agents run unattended | (no flag) |
| `interactive` | Operator at workstation watching | `--mode=interactive` |
| `p0` | Production-tier plans (`tier: p0` in plan.md) | Plan-driven |

Interactive backoff (after a gate-paused interactive volley resumes) is
controlled by `JARVIS_INTERACTIVE_BACKOFF_MINUTES` (default 30).

---

## Agent discovery — for AI agents calling DontPanic

Phase B (plan 2026-05-03-003) shipped:

- **Global manifest** at `~/.dontpanic/agent-manifest.json` — agents read
  this to discover the CLI path, MCP server command, registered projects,
  and supported intake types.
- **Local MCP server** via `dontpanic mcp serve` — typed tool surface
  with `list_projects` / `validate_plan` / `dispatch` (dry-run by
  default) / `status` / `approve_gate` / `read_evidence`.

Caller-pattern recipes for Claude Code, Codex CLI, Cursor, and OpenClaw
are in [`ECOSYSTEM.md`](./ECOSYSTEM.md). The plan-authoring contract LLMs
need to produce a valid plan dir is in [`AUTHORING_PLANS.md`](./AUTHORING_PLANS.md).

---

## Preflight — `dontpanic doctor`

Single command verifies the operator's machine has everything needed:

```bash
dontpanic doctor [--strict]
dontpanic doctor <project-name>     # project-specific
dontpanic doctor --skip-auth        # skip vendor auth checks
```

Exit codes: 0 (pass) / 1 (warnings) / 2 (errors). Checks include: CLI
binary on PATH, agent CLIs available, project paths exist, plans_dir
resolvable, agent-conventions schemas present, secrets dir mode 0700.

---

## File-system map (where everything lives)

```
~/.dontpanic/                      # operator-global, modern brand
├── config.json                    # default agent pair, tier, level
├── projects.json                  # registered projects
├── discord.json                   # webhook URL (gitignored)
├── quota_caps.json                # per-vendor weekly caps
├── quota_state.json               # live token usage
├── breaker_history.jsonl          # 24h global-breaker window
├── interactive_state.json         # interactive-mode backoff
├── active_supervisors.jsonl       # cross-process registry (F023 EC13)
├── agent-manifest.json            # Phase B agent-discovery manifest
└── .secrets/                      # mode 0700, service-account keys

~/.jarvis/                         # legacy fallbacks (read-compat)
└── …                              # same shapes, all still honored

<repo>/.dontpanic/                 # per-project, modern brand
└── dontpanic.json                 # per-project agent + plan config

<repo>/.jarvis/                    # legacy fallbacks (read-compat)
└── jarvis.json                    # same shape, still honored
```

Everything that ships out-of-the-box has a sensible default and can be
overridden without editing code. If you find yourself editing supervisor
internals to change a knob, that's a bug — open an issue.
