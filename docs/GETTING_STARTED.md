# Getting Started With DontPanic

This guide is for private-alpha users installing from source. It assumes you
are comfortable with a terminal and local agent CLIs, but it does not assume a
Firebase project or any cloud account for the first smoke test.

## Setup tracks — pick yours

DontPanic has one **required** layer and several **optional** layers. The order
is strict: each layer assumes the one above is already in place.

> See [`USE_CASES.md`](./USE_CASES.md) for the full matrix mapping each track
> to required core, optional core, external runtimes, and engagement surfaces.

```
Required:
  1. DontPanic core (this doc)        ← install + register a project + doctor

Optional layers (add as needed):
  2. Notification sink                ← see below — direct Discord webhook
                                          (works without any broker).
                                          Strongly recommended for multi-agent
                                          work: a Buzz private community as
                                          the notify surface — see § Buzz
                                          setup below
  3. Broker runtime (pick ONE)        ← only if you want bidirectional
                                          commands from chat / dashboard /
                                          hosted agent surface
       3a. OpenClaw                   ← chat-channel runtime (Discord /
                                          Telegram / WhatsApp). Best for
                                          notify-while-away over chat.
       3b. Claude dispatch            ← Claude.ai managed agents OR
                                          Claude Code subagents. Best when
                                          your runtime already has a
                                          notification surface (dashboard,
                                          email, hosted task queue).
       3c. Cursor / Continue / IDE    ← Interactive desktop integration via
                                          MCP. No "broker" needed — agents
                                          read DontPanic state during your
                                          active session.
       3d. Custom MCP client          ← Anything that speaks MCP can call
                                          DontPanic. Same pattern as 3a/3b.
  4. Broker-specific skill            ← The skill INSIDE your chosen broker
                                          that subscribes to DontPanic events
                                          and routes them. Replaces the direct
                                          sink in #2 once installed.
```

| Track | What you get | Time | Reference |
|---|---|---|---|
| **Solo dev, terminal only** | DontPanic core + agent CLIs | ~10 min | This doc → [`AGENT_QUICKSTART.md`](./AGENT_QUICKSTART.md) |
| **Solo dev, want Discord notifications** | Above + receive-only Discord webhook (no broker) | +2 min | This doc → [`CONFIGURATION.md` § Notifications](./CONFIGURATION.md#notifications) |
| **Multi-agent operator — Buzz private community (strongly recommended)** | Above + your own private Buzz community as the notify/coordination surface: plan status, gate requests, builder≠auditor agent identities in one room | +15 min | This doc → [§ Buzz setup](#buzz-strongly-recommended-private-community-setup) → [`ECOSYSTEM.md` § Buzz](./ECOSYSTEM.md#buzz-as-caller-and-notify-surface-strongly-recommended) |
| **Personal multi-channel surface** | Above + OpenClaw as multi-channel router (Discord/Telegram/WhatsApp) with bidirectional commands | +1-2 days | This doc → OpenClaw adapter plan |
| **Hosted-agent flow (Claude.ai managed agents)** | DontPanic events surfaced through Claude.ai's dashboard/email; approvals via Claude.ai chat → MCP | varies | This doc → [`AGENT_QUICKSTART.md`](./AGENT_QUICKSTART.md) → operator-side wiring |
| **AI agent integrating DontPanic interactively** (Claude Code, Cursor, Codex CLI, Continue) | DontPanic core + agent-manifest + MCP server. No broker needed — agents read state in your active session | ~5 min | [`AGENT_QUICKSTART.md`](./AGENT_QUICKSTART.md) → [`ECOSYSTEM.md`](./ECOSYSTEM.md) |

The first track is the only required one. **Don't install a broker just for
notifications** — the direct Discord webhook in the second track is zero-config
relative to standing up another runtime. Add a broker only when you want
bidirectional commands from a chat or hosted-agent surface.

**Picking 3a vs 3b vs 3c:** the axis is *interactive vs. notify-while-away*.
If you're at the keyboard, your IDE/CLI agent (3c) reads DontPanic via MCP
during the active session — no notification broker needed. If you want
status when *not* at the keyboard, pick the broker (3a or 3b) whose native
surface you'll actually check. OpenClaw owns chat channels; Claude.ai owns
hosted-agent dashboards/email. Same architectural pattern, different host.

## Install

```bash
git clone https://github.com/Silex-Research/DontPanic.git
cd DontPanic
python3 -m pip install -e ".[dev]"
dontpanic --version
dontpanic --help
```

Required for the first smoke test: Python 3.10+, git, and a POSIX shell.
Claude, Codex, Firebase, Playwright, Xcode, Android, and backend providers are
only needed when you enable plans that use them.

## Configure Roles

Preview config writes first:

```bash
dontpanic setup --implementer claude --auditor codex --goal-auditor codex
```

Apply once the preview is correct:

```bash
dontpanic setup --implementer claude --auditor codex --goal-auditor codex --yes
dontpanic config show
```

DontPanic stores role names and runtime pointers, not API keys. Agent CLIs and
cloud CLIs keep their own credentials.

## Register a Project

```bash
dontpanic projects add myapp /absolute/path/to/myapp --init-config
cd /absolute/path/to/myapp
dontpanic project config set roles.implementer claude
dontpanic project config set roles.auditor codex
dontpanic project config set runtime_evidence.web.base_url http://localhost:3000
```

Runtime evidence defaults are project-local because base URLs, simulator
targets, Android package names, and backend projects are project-specific.

Operating multiple repos from one install (mobile app + backend + schema +
DontPanic itself)? Register each with the command above. See
[`DASHBOARD_PROJECT_SELECTOR.md`](./DASHBOARD_PROJECT_SELECTOR.md) for the
fleet/project scope model, cache layout, and `dontpanic dashboard build|serve
--project <name>|all` usage. Single-repo mode keeps working unchanged when
no projects are registered.

## Run Readiness Checks

```bash
dontpanic doctor --skip-auth
```

Use the full doctor only after authenticating the optional provider CLIs your
project actually needs:

```bash
gcloud auth login
gcloud auth application-default login
firebase login
dontpanic doctor
```

## Buzz (Strongly Recommended): Private Community Setup

If you run multi-agent work, Buzz signup and setup are **strongly
recommended** — DontPanic works fine without it (local-first,
offline-capable), but a private [Buzz](https://buzz.xyz) community gives you
one room where plan status, gate requests, and your builder/auditor agent
identities are all visible.

> **Integration status:** both halves have shipped. `dontpanic doctor`
> reads `~/.dontpanic/buzz.json` and reports missing Buzz config as an
> **advisory WARN, never a failure** (CI/headless runs can silence it with
> `DONTPANIC_SKIP_BUZZ=1`). The notify sink posts plan events into your
> private community via the Buzz CLI (`buzz messages send`) and is
> **fail-soft**: when `buzz.json`
> is absent or the `buzz` binary is not installed, the sink silently stays quiet —
> nothing breaks and nothing is required. You can also drive DontPanic
> *from* Buzz with a thin workflow that shells out to the CLI — see the
> caller sketch in
> [`ECOSYSTEM.md` § Buzz](./ECOSYSTEM.md#buzz-as-caller-and-notify-surface-strongly-recommended).

The default work surface is a **private community that you create and own**.
The maintainers' Silex community is their own **private** dogfood workspace —
it is not a public support surface and not something you join. The only
public maintainer-owned surface is an optional DontPanic community that may
come later for discovery and support. **You are never required to join or
post into a maintainer-owned community**, and no DontPanic feature depends
on one.

First-hour checklist:

1. Install the Buzz desktop app (you can move to a self-hosted relay later —
   recommended for high-sensitivity or compliance-bound work).
2. Create a **private** community (or reuse an existing private one you own).
3. Create channels, e.g. `#dontpanic-status` and `#dontpanic-gates` (names
   are suggestions, not prescribed).
4. Create a reporter agent key (or use the Buzz CLI with `BUZZ_PRIVATE_KEY`)
   used only for DontPanic notifications.
5. Write `~/.dontpanic/buzz.json` so `dontpanic doctor` reports the Buzz
   surface as configured and the notify sink starts posting. Keys:
   `relay_url` (your **private** community's relay URL — in Buzz the relay
   URL *is* the community/workspace authority, handed to the CLI as
   `BUZZ_RELAY_URL`; there is no default, and never a public one — do not
   paste a public support community's relay here), `channels` (channel
   UUIDs from your private community; the sink posts to the first entry),
   and `reporter_key_ref` (a reference such as an env var name — never the
   private key itself; buzz.json stays secret-free and the fail-soft notify
   sink resolves the reference at send time). Example:

   ```json
   {
     "relay_url": "https://relay.your-team.example",
     "channels": ["11111111-2222-4333-8444-555555555555"],
     "reporter_key_ref": "env:BUZZ_PRIVATE_KEY"
   }
   ```

   `relay_url` must point at a **private** community you own — never a
   public support or discovery community. The sink only ever posts
   projections (summaries, hashes, gate links) and never secrets, home
   paths, or full transcripts, but private work belongs in a private room
   regardless.

   **Optional — Buzz agent ↔ worker-profile bindings (off by default).**
   If your community has agent identities (say Fizz/Honey/Bumble) that
   correspond to DontPanic worker profiles, an `agent_bindings` key maps
   the Buzz agent id or display name to the local profile id so docs and
   status can show the chain Buzz agent → profile → harness + model:

   ```json
   {
     "relay_url": "https://relay.your-team.example",
     "channels": ["11111111-2222-4333-8444-555555555555"],
     "reporter_key_ref": "env:BUZZ_PRIVATE_KEY",
     "agent_bindings": { "Fizz": "fizz", "Honey": "honey" }
   }
   ```

   Inspect the join with `dontpanic workers buzz-bindings`. Bindings are
   **display-only**: Buzz remains the UX for membership; DontPanic's
   roles/profiles remain the dispatch authority, and model selection
   stays single-sourced in the profile — the binding carries no
   harness or model of its own. A binding never confers dispatch
   authority (a Buzz name that happens to equal a profile id dispatches
   via the profile table, never via the binding), an unbound agent
   gains nothing, and no Buzz message auto-dispatches anything —
   Buzz-initiated runs still go through the confirm-gated caller
   recipe (`examples/buzz-caller/README.md`). The
   notify reporter key above stays a separate thin identity, unrelated
   to these bindings.

   **Optional — Buzz gate bridge (off by default).** A `gate_bridge` key
   lets an **allowlisted human** clear a *pending* DontPanic gate by
   posting a **signed Nostr event** whose content is the exact ceremony
   `dontpanic approve plan=<plan_id> gate=<gate>`. Reactions / emoji
   **never** auto-confirm (ECOSYSTEM.md non-goal). Apply via
   `dontpanic buzz-gate <plan> --payload <file|->` or
   `dontpanic buzz-gate <plan> --poll` (shells out to configured
   `poll_command` — typically the Buzz CLI; DontPanic still has no relay
   client of its own):

   ```json
   {
     "relay_url": "https://relay.your-team.example",
     "channels": ["11111111-2222-4333-8444-555555555555"],
     "reporter_key_ref": "env:BUZZ_PRIVATE_KEY",
     "gate_bridge": {
       "enabled": true,
       "approver_pubkeys": ["<hex pubkey of a HUMAN operator>"],
       "agent_pubkeys": ["<hex pubkeys of your agent identities>"],
       "channel": "11111111-2222-4333-8444-555555555555",
       "gate_kinds": ["pre_impl", "pre_merge"],
       "poll_command": ["buzz", "timeline", "--json"],
       "webhook_secret_ref": "env:BUZZ_GATE_WEBHOOK_SECRET"
     }
   }
   ```

   The bridge stays off unless `enabled: true`, `approver_pubkeys` is
   non-empty, **and** `agent_pubkeys` is present as a list (empty list is
   an explicit “no agent identities”; omitting the key fails closed).
   `approver_pubkeys` lists **human** operator pubkeys only — any key in
   `agent_pubkeys` is refused even if it also appears in the allowlist
   (D006: agent keys may post status and request approval, never
   self-clear). Cryptographic verification is **in-process** (BIP-340 /
   NIP-01): the payload must wrap a raw signed event; the legacy
   `sig_verified: true` flat shape is rejected. Webhook deliveries also
   require a valid HMAC-SHA256 over the event id using
   `webhook_secret_ref`. An accepted approval records the durable actor
   `buzz:<pubkey>` in gate-state history, an INBOX `gate_cleared` event,
   a consumed-event ledger entry, and a `decisions.jsonl` audit note.
   Synthetic gates (`breaker:*`, `defer:*`, …) and any non-pending gate
   always refuse — those stay on the operator CLI (`dontpanic approve`).
6. Point your Buzz-side workflow (the caller sketch in `ECOSYSTEM.md`) at
   the DontPanic CLI, with your relay URL, channels, and reporter key in the
   workflow's own config. DontPanic's notify sink posts projections itself
   using the same `buzz.json` (fail-soft when it or the `buzz` binary is
   absent).
7. Optionally join the public DontPanic community for help and recipes if
   one exists — keep it separate from your private work community.

Remember the split: your private community carries work (status, gates,
agent membership); public communities carry support and discovery. The
delivery contract only ever posts projections (summaries, hashes, gate
links) — never secrets or full transcripts. See
[`ECOSYSTEM.md` § Buzz](./ECOSYSTEM.md#buzz-as-caller-and-notify-surface-strongly-recommended)
for the full community model, the Buzz-as-caller recipe, and the locked
non-goals.

## Onboarding A New Agent Or A New Repo

DontPanic distinguishes two roles, and the onboarding path differs for each:

- **Operator** — a human (or an interactive agent like Claude Code / Cursor)
  who *runs* DontPanic: locks plans, approves gates, reads guidance, opens the
  dashboard. An operator does not need a registered worker executor.
- **Worker** — an agent that DontPanic *dispatches* to do implementation or
  audit work (claude / codex). A worker must have a registered executor; an
  operator-only agent cannot be assigned to the `implementer`/`auditor` roles.

**New agent — get the operating brief.** Any agent operating DontPanic should
read the generated brief first; it states the current command set, executors,
and conventions so nobody works from stale assumptions:

```bash
dontpanic agent brief            # human-readable operating brief
dontpanic doctor --agent         # agent-level readiness (CLI, manifest, roles, homes)
```

**New repo — register and onboard in one step.** `--onboard` writes the managed
`AGENTS.md` block (the in-repo brief) at registration time so a fresh clone is
agent-ready immediately:

```bash
dontpanic projects add myapp /absolute/path/to/myapp --onboard
dontpanic doctor --project myapp     # this project's onboarding/config/roles surface
```

Re-onboarding an already-registered repo (after a generator-version bump or to
refresh a drifted block) requires the explicit overwrite flags:

```bash
dontpanic projects add myapp /absolute/path/to/myapp --onboard --force --yes
```

**Assign roles.** Roles resolve from project config, then global config, then
defaults. Set them per project (workers must be registered executors):

```bash
dontpanic project config set roles.implementer claude
dontpanic project config set roles.auditor codex
```

## Configuration Inventory / Setup Cockpit

`config inventory` is the one-screen answer to "what is configured, what still
needs setup, and what only a human can decide" — across machine and project
scope. It is the same data the dashboard Settings/Setup cards render:

```bash
dontpanic config inventory               # current repo / machine scope
dontpanic config inventory --project myapp
```

Items are classed `ok` / `needs_setup` / `missing` / `human_required`. When any
item needs a human, the response carries exactly **one** dashboard hint (the
active URL if a dashboard is running, otherwise the start command) — it is never
repeated per item.

## What-Now: Operations Guidance For Blocked Work

When a dispatch is blocked — quota cooldown, budget ceiling, iteration cap, a
cleared `pre_merge` signoff waiting to finalize, a tripped breaker, or a setup
gap — `what-now` turns it into a short, ranked decision set with an exact
command where one is safe to emit:

```bash
dontpanic what-now <plan-id> --feature F001
```

It recommends the safer default (usually wait-then-redispatch), names the
alternatives, and marks any choice that needs a human judgment call. Like the
inventory, it shows the dashboard pointer **once per response** even when many
choices require human input.

## Skill Invocation Recommendations

For a plan whose repo ships `claude/skills`, DontPanic can recommend which
skills to invoke for the current work (and which are not yet ready):

```bash
dontpanic skills recommend <plan-id>
```

The CLI and the dashboard render the same recommendation data, so guidance never
drifts between surfaces.

## Dispatch With `orchestrate`

`orchestrate` runs the supervised implement→audit loop for a plan/feature.
It is dry-run until you confirm:

```bash
dontpanic orchestrate <plan-id>            # preview the resolved dispatch
dontpanic orchestrate <plan-id> --confirm  # run the volley
```

Budget and iteration limits come from the plan's `loop_caps`; when a cap is
reached, `what-now` (above) is where you decide whether to wait, raise the cap,
finalize, or close.

## Dashboard: When And How To Open It

The dashboard is **operator-local by definition** — it binds `127.0.0.1` only.
Decision flow:

1. **Is one already running?** Guidance and inventory tell you: if a dashboard
   is live they print its URL; if not, they print `dontpanic dashboard serve`.
2. **Start it** when you want the visual console:

   ```bash
   dontpanic dashboard serve                 # build + serve + file-watch refresh
   dontpanic dashboard serve --project all   # fleet view across registered repos
   ```

3. **One server per home.** Starting a second `serve` for the same DontPanic
   home is refused with the existing URL — open that instead of stacking
   servers. To intentionally take over (e.g. a previous server is stuck):

   ```bash
   dontpanic dashboard serve --replace        # stop the old one, serve here
   ```

   A crashed server leaves a stale record; the next `serve` prunes it
   automatically, so you only need `--replace` when the old server is genuinely
   still alive. Ordinary same-port conflicts still surface as a normal bind
   error.

4. **Headless / CI?** Use `dontpanic dashboard build` to write state without
   binding a server, or `dontpanic dashboard open --no-launch` to print the
   local path.

## Try A Safe Plan

The sample plan is exempt from goal governance and never dispatches agents.
Copy it to a temporary directory so your checkout stays clean:

```bash
python3 claude/shared/schemas/v1.0/validate.py examples/plans/hello-dontpanic
tmp_plan="$(mktemp -d)/hello-dontpanic"
cp -R examples/plans/hello-dontpanic "$tmp_plan"
dontpanic plan lock "$tmp_plan"
dontpanic plan close "$tmp_plan"
```

Expected result: `plan lock` flips `draft -> active`; `plan close` flips
`active -> completed` through the exempt infra path.

## Dispatch Real Work

For real work, create or choose a plan under `docs/plans/<plan-id>/`, validate
it, lock it, then preview dispatch:

```bash
python3 claude/shared/schemas/v1.0/validate.py docs/plans/<plan-id>/
dontpanic plan lock docs/plans/<plan-id>/
dontpanic dispatch-from-plan <plan-id>
```

`dispatch-from-plan` is dry-run by default. It prints the resolved context and
does not run agents until you add `--confirm`.

```bash
dontpanic dispatch-from-plan <plan-id> --confirm
dontpanic plan close docs/plans/<plan-id>/
```

Goal-gated plans run a sufficiency check at lock and a completion audit at
close. Blocking findings require an explicit operator override reason that is
recorded under the plan's evidence directory.
