# DontPanic

> The safety layer between “the agent says it’s done” and “you merge it.”

DontPanic turns AI coding from "one agent says it finished" into reviewed,
tested, evidence-backed software delivery. It locks the work into a plan,
runs implementer and auditor agents against that plan, pauses for human
approval at declared gates, and leaves behind durable proof before you merge.

Formerly **Jarvis**. The repo and public product are now DontPanic.
New installs use `dontpanic`, `dontpanic_orchestrate`, `~/.dontpanic`,
and `<repo>/.dontpanic/dontpanic.json`. Legacy `jarvis`,
`dontpanic_orchestrate`, `~/.jarvis`, and `<repo>/.jarvis/jarvis.json`
remain compatibility aliases while the migration happens in stages.

## DontPanic is self-contained

Install DontPanic. It works by itself. The schemas it validates against
are vendored under `claude/shared/`; no separate schema repo is required
to install or run. The upstream `agent-conventions` repo exists for
schema evolution and external tool authors — it is not a prerequisite
for using DontPanic.

**Optional ecosystem integrations** (only if you want them):

| Integration | Kind | What it adds | When you need it |
|---|---|---|---|
| Hermes `/goal` pattern | Conceptual | Vocabulary + workflow primitives for orchestrator → builder → reviewer dispatches | You want a shared mental model with other agent-driven teams; cited in the Vocabulary section below |
| OpenClaw | Runtime | Multi-channel agent UI (Telegram, Discord, Slack, WhatsApp, web chat) | Multi-channel agent UIs in front of DontPanic-orchestrated work |
| Firebase / Axiom dashboard adapter | Runtime | Realtime team kanban | Multi-operator collaboration |
| Printing Press adapters | Runtime | External service evidence providers | OpenAPI-shaped service wrapping |
| agent-conventions (upstream) | Maintainer | Schema authoring + external validators | You're building tools that validate DontPanic artifacts outside DontPanic |

Hermes and OpenClaw both interoperate with DontPanic but serve different
needs: Hermes is a pattern (you read it, you adopt the vocabulary); OpenClaw
is a runtime (you install it, it talks to your users). Use either, both, or
neither — DontPanic stands on its own.

Each integration is opt-in. None is installed automatically. The core
`dontpanic` install includes the CLI, supervisor/dispatch, doctor/init/new,
vendored schemas, validators, MCP server, state projection, static
dashboard/export, and docs/templates/examples.

**Status:** public alpha. DontPanic is ready for source installs by operators
who are comfortable with local agent CLIs, plan-driven workflows, and
preview-before-mutation commands. See [`docs/PRODUCT.md`](./docs/PRODUCT.md) for
the plain-English product overview, [`docs/ROADMAP.md`](./docs/ROADMAP.md) for
the current build plan, and [`docs/plans/`](./docs/plans/) for active work.

---

## What is DontPanic

DontPanic is a 4-layer hierarchy that lets multiple AI agents collaborate on
real work without going off the rails:

```
Identity & governance        ← SOUL.md, AGENTS.md, USER.md
Routing & contracts          ← claude/RESOLVER.md, claude/shared/ (agent-conventions subtree)
Execution units              ← claude/skills/, docs/plans/<id>/
Multi-agent panel + bounds   ← Claude / Codex / Gemini / Grok / OSS  +  CAWP tiers + circuit breakers
```

Each layer's output becomes the next layer's contract. Plans live in `docs/plans/<YYYY-MM-DD-NNN-type-name>/` with `features.json` as inviolable machine-checkable ground truth. Different model families audit each other so no single vendor self-approves.

The platform thesis is captured in [`docs/PLATFORM.md`](./docs/PLATFORM.md):
DontPanic is portable trust infrastructure for bounded agent work. It routes intent
through reusable skills and learned memory, turns non-trivial work into
machine-checkable plans, executes those plans across model/vendor boundaries, and
preserves proof through audits, evidence, signoff, and protected-path checks.

DontPanic may use external service adapters when they improve intake or
evidence quality. The planned Printing Press adapter work explicitly credits
[CLI Printing Press](https://github.com/mvanhorn/cli-printing-press) and the
[Printing Press Library](https://github.com/mvanhorn/printing-press-library)
for the agent-native CLI/MCP adapter pattern. Those tools remain external;
DontPanic's responsibility is the allowlist, provenance, read-only policy,
redaction, normalized evidence, and signoff boundary around any adapter it uses.

---

## Vocabulary (Hermes `/goal` mapping)

DontPanic implements the [Hermes `/goal` pattern](https://x.com/Saboo_Shubham_)
— one orchestrator, one builder, one reviewer, one verifier loop. If you already
know that pattern, this table maps the terminology directly:

| Hermes term          | DontPanic term                                        |
|----------------------|-------------------------------------------------------|
| HERMES orchestrator  | `supervisor.dispatch_volley`                          |
| `/goal` primitive    | Locked plan + `features.json` acceptance              |
| CODEX builder        | Implementer role (typically Claude)                   |
| CLAUDE CODE reviewer | Auditor role (typically Codex)                        |
| Verifier checklist   | Audit envelope schema + finding taxonomy              |
| "Done" criteria      | `features.json` acceptance + shell-verifiable commands |

DontPanic is one implementation of this pattern, not a rebrand of Hermes.

---

## Prerequisites

Required:

- **macOS** or Linux with **zsh** or **bash**
- **Python 3.10+** with `pip`
- **git**

Optional (depending on which agents you wire):

- **Claude Code / claude CLI** — common implementer
- **Codex CLI** — common cross-vendor auditor
- **gcloud SDK** / **firebase-tools** — only for Firebase-backed projects or backend evidence capture
- **jq** — useful for inspecting JSON evidence
- **ollama** — `brew install ollama` (local OSS models for safety/embeddings)
- **gemini CLI** — multimodal review + 2M context
- **terminal-notifier** — `brew install terminal-notifier` (INBOX async channel)

The editable install pulls the runtime Python dependencies from `pyproject.toml`.
Use the `dev` extra when you want to run tests and formatting locally.

---

## Quickstart

The preferred command is `dontpanic`. The legacy `jarvis` alias still works.

### 1. Install from source

```bash
git clone https://github.com/Silex-Research/DontPanic.git
cd DontPanic
python3 -m pip install -e ".[dev]"
```

Confirm the CLI is on your path:

```bash
dontpanic --version
dontpanic --help
```

### 2. Configure roles and local defaults

`dontpanic setup` is preview-only by default. It writes no secrets; it stores
agent role names and project runtime pointers only.

```bash
dontpanic setup \
  --implementer claude \
  --auditor codex \
  --goal-auditor codex
```

If the preview looks right:

```bash
dontpanic setup \
  --implementer claude \
  --auditor codex \
  --goal-auditor codex \
  --yes
```

Inspect what was written:

```bash
dontpanic config show
dontpanic manifest init --yes
dontpanic manifest show --json
```

Agent CLIs authenticate themselves. DontPanic does not store API keys.

### 3. Register a project

```bash
dontpanic projects add myapp /absolute/path/to/myapp --init-config
cd /absolute/path/to/myapp
dontpanic project config set roles.implementer claude
dontpanic project config set roles.auditor codex
```

Runtime evidence defaults are also project-scoped:

```bash
cd /absolute/path/to/myapp
dontpanic project config set runtime_evidence.web.base_url http://localhost:3000
```

### 4. Run the doctor

```bash
dontpanic doctor --skip-auth
```

For Firebase/backend projects, authenticate the relevant CLIs and run the full
doctor:

```bash
gcloud auth login
gcloud auth application-default login
firebase login
dontpanic doctor
```

### 5. Try the safe sample plan

This sample exercises the plan lifecycle without dispatching any paid agent
call. It validates, locks, and closes an exempt infra plan.

```bash
python3 claude/shared/schemas/v1.0/validate.py examples/plans/hello-dontpanic
tmp_plan="$(mktemp -d)/hello-dontpanic"
cp -R examples/plans/hello-dontpanic "$tmp_plan"
dontpanic plan lock "$tmp_plan"
dontpanic plan close "$tmp_plan"
```

The sample copy avoids mutating your checkout. It does not dispatch agents and
does not call any paid model API.

### 6. Run tests

```bash
PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/ -q
ruff check scripts/
ruff format --check scripts/
python3 scripts/sanitization_check.py
```

### 7. Dispatch real work

New plans live under `docs/plans/<YYYY-MM-DD-NNN-type-name>/` with `plan.md`,
`features.json`, and `decisions.jsonl`. Validate and lock before dispatch:

```bash
python3 claude/shared/schemas/v1.0/validate.py docs/plans/<plan-id>/
dontpanic plan lock docs/plans/<plan-id>/
```

Refresh quota state and preview dispatch:

```bash
python3 scripts/quota_check.py
dontpanic quota-caps init
dontpanic dispatch-from-plan <plan-id>
```

`dispatch-from-plan` is strict dry-run by default. It prints the resolved plan,
feature, tier, target, implementer, auditor, gates, max iterations, and quota
readiness, then exits without running agents.

After you review the preview:

```bash
dontpanic dispatch-from-plan <plan-id> --confirm
```

Close the plan after all features pass:

```bash
dontpanic plan close docs/plans/<plan-id>/
```

As the run proceeds, DontPanic writes durable artifacts under the plan dir:

| Path | What it is |
|---|---|
| `audit/<agent>-<role>-i<N>.json` | Per-iteration audit JSON (machine-checkable verdict) |
| `audit/transcript.md` | One row per dispatch — agent, role, tokens in/out, verdict, audit link |
| `audit/signoff-<plan-id>.json` | Volley-terminal verdict (signoff: true/false, reason, next_action) |
| `audit/gate-state.json` | Gate-clearance state (cleared_gates, history, active_breakers) |
| `INBOX.md` | Append-only operator log: gate_paused, breaker_tripped, signoff |

Clear gates when prompted:

```bash
dontpanic ps                                  # active supervisors
dontpanic approve <plan-id> <gate>            # clear one gate
dontpanic resume <plan-id> --all              # explicit bulk clear
```

See [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md) for a slower
walkthrough and [`docs/AGENT_QUICKSTART.md`](./docs/AGENT_QUICKSTART.md) for
the flow an AI caller should follow.

---

## How agents call DontPanic

Agents should discover DontPanic the same way a human does: read the
machine-level manifest, show the user the plan, then call the local tool
surface. The invariant is simple:

**Always surface the plan to the user before calling dispatch(confirm=true). Do NOT auto-confirm.**

That rule appears in `~/.dontpanic/agent-manifest.json` and in every caller
example below. The manifest is the first thing an agent should read:

```bash
dontpanic manifest show --json
```

It returns the canonical command surface, including the local MCP server:

```json
{
  "mcp_server": {
    "command": "dontpanic",
    "args": ["mcp", "serve"]
  },
  "supported_commands": ["dispatch-from-plan", "projects", "manifest", "mcp"],
  "safety_rules": [
    "Always surface the plan to the user before calling dispatch(confirm=true). Do NOT auto-confirm."
  ]
}
```

See [`docs/ECOSYSTEM.md`](./docs/ECOSYSTEM.md) for the non-goals and caller
patterns, [`docs/DISCOVERABILITY.md`](./docs/DISCOVERABILITY.md) for the
publish-readiness checklist, and [`docs/AUTHORING_PLANS.md`](./docs/AUTHORING_PLANS.md)
for the plan-directory contract once F004 lands.

### Claude Code

Add DontPanic as a local MCP server, then ask Claude to validate or dispatch a
registered plan. Claude must show the plan and ask before passing
`confirm=true`.

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

OpenClaw should treat DontPanic as a callable software-delivery skill, not as a
runtime competitor. The OpenClaw skill reads `~/.dontpanic/agent-manifest.json`,
starts the local MCP server, and forwards plan/gate updates back to the user.

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

Codex can shell out to the CLI today and use the same MCP shape when running in
an MCP-aware host. The cross-vendor pattern is common: one model implements,
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
2. call dontpanic.validate_plan or run dontpanic dispatch-from-plan <plan-id>
3. show the dry-run/preflight output to the user
4. dispatch only when the user authorizes confirm=true
```

---

## Project layout

```
DontPanic/
├── SOUL.md                          # values + safety guard
├── AGENTS.md                        # operating manual + role catalog
├── USER.md                          # who you're helping
├── CONTINUOUS_WORK_PROTOCOL.md      # 15-min cycle + tier-based approval matrix
├── MEMORY_ARCHITECTURE.md           # daily logs + long-term memory layout
│
├── claude/
│   ├── RESOLVER.md                  # intent → skill routing with precedence
│   ├── settings.json                # hooks, env, permissions
│   ├── skills/                      # 24 skills (plan-artifacts, brainstorm-gate, …)
│   ├── hooks/                       # session-start, security-gate, …
│   ├── commands/                    # slash commands
│   ├── registry/entities.md         # cross-project service registry
│   └── shared/                      # ← agent-conventions subtree (v1.1.0)
│       ├── conventions/             # firestore-security, error-handling, …
│       ├── resolver/SPEC.md         # RESOLVER.md format definition
│       ├── skill-standard/          # skill conformance + template
│       └── schemas/v1.0/            # plan/features/audit/signoff schemas + Pydantic
│
├── docs/plans/                      # directory plans (executable contracts)
│   └── <YYYY-MM-DD-NNN-type-name>/
│       ├── plan.md                  # frontmatter validates against plan.schema.json
│       ├── features.json            # validates against features.schema.json
│       ├── decisions.jsonl          # append-only decision log
│       ├── audit/*.json             # per-agent audit reports
│       └── evidence/                # small artifacts (large → Firebase Storage)
│
├── capabilities/                    # external capability manifests + setup/verify contracts
│   ├── agent-claude-cli.json         # agent CLI capability example
│   ├── discord-notify.json           # notification sink
│   ├── firebase-dashboard.json       # optional realtime dashboard adapter
│   └── linear.json                   # PM-tool adapter reference
│
├── examples/plans/hello-dontpanic/   # safe lifecycle sample
│
├── scripts/
│   ├── dontpanic_orchestrate/        # supervisor runtime + CLI package
│   ├── bootstrap.sh                  # optional GCP/Firebase setup
│   ├── dontpanic_doctor.py           # preflight health checks
│   ├── jarvis_doctor.py              # legacy doctor alias
│   ├── sanitization_check.py         # sanitization regression guard
│   └── quota_check.py                # LLM tokens → ~/.dontpanic/quota_state.json
│
├── dashboard/                       # operator-local visual console + optional Firebase adapter
│   ├── index.html                   # local dashboard shell
│   ├── pages/                       # What Now, Status, Capabilities, Mission Control, …
│   └── state/                       # generated projections: plans, gates, capabilities, costs, …
│
├── .secrets/                        # gitignored — service account keys (created by bootstrap --create-key)
├── environments.json                # gitignored; generated from environments.json.example
└── .firebaserc                      # gitignored; generated from .firebaserc.example
```

---

## Architecture in one diagram

```
SOUL / AGENTS / USER       ← who I am, what I can do, who I serve
        ↓
RESOLVER + claude/shared/  ← which skill fires, by which rules
        ↓
skills/  +  registry/      ← unit of work + cross-project knowledge
        ↓
plans/ + features.json     ← executable contract for any non-trivial work
        ↓
Claude / Codex / Gemini / Grok / OSS  ← panel that implements + audits
        ↓
CAWP tiers + quotas + dashboard       ← the throttle and the readout
```

Full design in [`docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md`](./docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md).

---

## Two-axis billing

DontPanic tracks cost on two independent axes:

| Axis | Source | Output | Use |
|---|---|---|---|
| GCP $ | Your billing-account BigQuery export | `dashboard/state/costs.json` | Cloud-spend dashboard (operator-supplied refresh script; not bundled) |
| LLM tokens | Per-model session logs (Claude/Codex/Gemini/Grok) + Ollama probe | `~/.dontpanic/quota_state.json` | Circuit breakers (defer dispatch when weekly quota near cap) |

Run `python3 scripts/quota_check.py` for LLM tokens (every ~30 min during active work). GCP $ refresh is operator-specific (project list, app categorization, billing-export project all vary) and is not shipped as a bundled script.

---

## Setup checklist (running list — what new users need)

This list grows as we build. If a feature requires new setup, it lands here.

First-use baseline:

- [x] Editable install from `pyproject.toml`
- [x] Top-level `dontpanic --help` and `dontpanic setup --help`
- [x] Preview-by-default setup flow
- [x] Global roles config at `~/.dontpanic/config.json`
- [x] Project config at `<repo>/.dontpanic/dontpanic.json`
- [x] Agent manifest at `~/.dontpanic/agent-manifest.json`
- [x] Safe sample plan at `examples/plans/hello-dontpanic/`

Supervisor + executor panel (shipped):

- [x] Single-agent + volley dispatch (Claude / Codex / Gemini / Grok / Ollama executors)
- [x] 7 circuit breakers (budget_ceiling, iteration_cap, no_progress, diminishing_returns, convergence_collapse, wall_clock, global_circuit_breaker)
- [x] Vendor-native quota tracker (`scripts/quota_check.py` v2 schema)
- [x] Operator caps + Claude calibration (`~/.dontpanic/quota_caps.json`, `~/.dontpanic/quota_calibration.json`; legacy `~/.jarvis` still readable)
- [x] Engagement surface (`INBOX.md`, `signoff-<plan-id>.json`, `transcript.md`, `gate-state.json`)
- [x] CLI surface: `dispatch-from-plan`, `quota-caps`, `calibrate-claude`, `approve`, `resume`, `ps`, `claude-touch`
- [x] Goal Governance V1 lock/close gates (`dontpanic plan lock`, `dontpanic plan audit`, `dontpanic plan close`)
- [x] Runtime evidence collectors for web, iOS, Android, and backend observability

Operator-local prerequisites (per machine):

- [ ] Codex / Gemini / Grok CLIs authed (only the agents your plans use)
- [ ] `terminal-notifier` installed (`brew install terminal-notifier`) for desktop pings — optional; INBOX.md is the durable channel
- [ ] `~/.dontpanic/quota_caps.json` initialized (`quota-caps init`) and Claude calibrated (`calibrate-claude --dashboard-pct N`)
- [ ] Re-calibrate Claude weekly (`quota_check.py` warns at >7 days)
- [ ] gcloud/firebase authenticated only for Firebase-backed projects or backend evidence capture
- [ ] BigQuery billing export configured (manual, Console only) — optional, only needed for app-level $ tracking

---

## See DontPanic on real repos

[`docs/showcase/`](./docs/showcase/README.md) holds artifacts generated by
running DontPanic's architecture map + strict-plan-validation + drift
probes from inside DontPanic against four real checkouts we own. No
DontPanic runtime code is copied into any target repo; the showcase is
the product surface.

- Visual architecture map of [`agent-conventions`](./docs/showcase/agent-conventions-architecture.html) (the shared schema repo)
- Visual architecture map of [`Glam`](./docs/showcase/glam-architecture.html) (largest target — iOS creator hub + commerce)
- DontPanic itself: [architecture](./docs/showcase/dontpanic-architecture.html) + [plan validation](./docs/showcase/dontpanic-validate-plans.json) + [drift](./docs/showcase/dontpanic-drift.json)

Regenerate with `make showcase` (or `scripts/showcase.sh`). Full index +
per-target regen commands + the local-integration deferral policy:
[`docs/showcase/README.md`](./docs/showcase/README.md).

---

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md). For substantial changes, read
`AGENTS.md`, follow the conventions in `claude/shared/conventions/`, and write
or update a plan before code.

## License

Apache-2.0. See [`LICENSE`](./LICENSE).
