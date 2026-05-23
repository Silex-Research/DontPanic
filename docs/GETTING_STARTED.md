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
                                          (works without any broker)
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
