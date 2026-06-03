# DontPanic

> Trust infrastructure for AI coding agents.

![DontPanic social preview](./docs/assets/dontpanic-social-preview.jpg)

**From vibe coding to governed software engineering.**

AI coding agents are getting good enough to build real software. The hard part
is no longer just capability; it is trust. DontPanic locks autonomous coding
work to a plan, sends it through an independent model-family audit, pauses at
human approval gates, and leaves an evidence trail before anything reaches
production.

**Plan-locked. Cross-model audited. Human approved.**

It works with Claude Code, OpenClaw / Hermes-style workflows, Codex, Gemini,
Grok, local models, and MCP-enabled tools.

**Status:** public alpha. DontPanic is ready for source installs by operators
who are comfortable with local agent CLIs, plan-driven workflows, and
preview-before-mutation commands.

## The Problem

AI coding agents are powerful.

They are not trustworthy by default.

AI agents can:

- confidently ship broken code
- approve their own work
- miss edge cases and security assumptions
- burn runaway token budgets
- retry endlessly without converging
- leave no durable audit trail
- make production changes without clear accountability

DontPanic exists for the moment between:

> "The agent says it's done."

and:

> "Should we actually merge this?"

## Why AI Coding Breaks At Scale

Vibe coding works surprisingly well for prototypes, demos, side projects, and
simple apps.

Production software changes the problem.

Real systems have hidden dependencies, security requirements, deployment
complexity, architectural constraints, cost limits, and people who need to know
who approved what. At that point, the question is no longer:

> "Can the AI generate code?"

It becomes:

> "Can we trust autonomous systems to safely evolve complex software?"

Most agent harnesses optimize for more autonomy. DontPanic optimizes for more
trust.

Capability is not reliability. Claude Code, Codex, Gemini, Grok, Cursor, local
models, and other agent runtimes are execution engines. They are built to
generate code, edit files, use tools, and complete tasks quickly. They are not,
by themselves, a governance system.

A brilliant engineer still needs peer review, QA, budgets, approvals,
architecture review, and deployment controls. Not because the engineer is bad.
Because complex systems require layered verification. Autonomous coding is the
same. The more capable the agent becomes, the larger the blast radius becomes
unless governance matures with it.

That is the gap DontPanic fills: it separates intelligence from trust.

## The Fix

DontPanic adds trust infrastructure around AI coding:

- **Immutable plans** — requirements and acceptance criteria are validated and locked before work starts. A locked plan still evolves *safely*: a **scope-change protocol** refuses silent drift (a budget-busting expand of a locked feature, or a lossy split) unless a rationale is recorded or the feature is split, and every decision lands in an append-only `decisions.jsonl` ledger.
- **Scope governance** — a deterministic, free scope lint catches over-scoped features, exemplar/weak acceptance criteria, and undeclared prerequisites *before* a paid run; an optional cross-model design-review volley red-teams the decomposition; cross-feature-edit detection flags a diff that bleeds into another feature's files.
- **Cross-model verification** — one agent builds; a different model family audits code, tests, security, docs, architecture, and plan compliance.
- **Human approval gates** — risky work pauses until a human sees the evidence and approves, requests changes, or rejects.
- **Circuit breakers** — eight automatic kill-switches (budget, iteration, no-progress, diminishing-returns, convergence-collapse, wall-clock, environmental-blocker, and a system-wide global breaker) stop waste and runaway loops.
- **Evidence trails** — transcripts, audit logs, artifacts, signoff, gate state, and INBOX entries stay on disk.
- **Budget controls** — token and cost visibility prevents runaway agent loops.

The core rule is simple:

> Never let the same AI that wrote the code be the only AI that approves it.

Plans are not bureaucracy. They preserve intent across autonomous execution.
A locked plan becomes the memory anchor, acceptance contract, architectural
constraint, verification target, and anti-drift mechanism. Without that anchor,
agents can appear coherent while slowly mutating the objective.

Cross-model audits are not theater. They create adversarial diversity. A single
model reviewing its own work tends to reinforce its assumptions and rationalize
internally coherent mistakes. Different model families catch different failures,
the same way human peer review catches what the author missed.

## Before / After

**Without DontPanic**

You ask an agent to add Stripe webhooks.

The agent writes code, says tests pass, claims completion, and misses webhook
signature verification. The change looks plausible, merges fast, and becomes a
production security problem.

**With DontPanic**

The request becomes a locked plan. The implementer agent writes the code. A
different model family audits the patch against the plan, tests, docs, security
assumptions, and architecture. The auditor catches the missing signature
verification. The run pauses. Evidence is packaged. A human approves the fix.
Only then can the work proceed.

## Who It Is For

DontPanic is built for:

- Claude Code and Codex power users who want production-grade guardrails
- OpenClaw / Hermes-style operators routing work through AI agents
- teams scaling AI coding without letting one model self-approve
- enterprises adopting autonomous development with audit and approval needs
- anyone burned by confident-but-wrong AI output

## Why Not Just Claude Code?

Claude Code, Codex, Gemini, Grok, and local models make coding faster.

DontPanic makes AI-generated code trustworthy enough to ship.

Model vendors optimize for autonomy, speed, and usage. DontPanic optimizes for
verification, governance, accountability, auditability, and cost control.
Different model families catch different mistakes, which is why DontPanic uses
cross-model audits instead of self-approval.

Skills and better prompts improve execution. They do not automatically create
separation of duties, reproducibility, cost containment, or organizational
trust. In production, smarter agents need stronger guardrails, not fewer.

**vs. same-family multi-agent (Claude's Dynamic Workflows / Managed Agents,
etc.):** those orchestrate a swarm of one vendor's own sub-agents for speed and
scale — powerful, but everything shares one model family's blind spots, with no
independent cross-check and a boss that can improvise the plan mid-run.
DontPanic is the opposite posture: a vendor-neutral *meta-harness* that sits on
top of any of those engines, holds the plan locked, makes a **different** model
family audit the work, keeps a human in the approval loop, and trips circuit
breakers when a run goes sideways. Same-family swarms optimize for velocity;
DontPanic optimizes for code you can trust in production — and it can drive the
swarm as one of its implementers.

## See It In Action

```text
$ dontpanic dispatch-from-plan docs/plans/stripe-webhooks --confirm
✓ Plan locked: plan.md + features.json
✓ Dispatching to Claude Code (implementer)
✓ Audit assigned to Codex (auditor)
…
⚠ Gate paused: audit findings ready
  → INBOX.md updated
  → evidence packaged
  → waiting for your approval
```

As the run proceeds, DontPanic writes durable artifacts under the plan dir:

| Path | What it is |
|---|---|
| `audit/<agent>-<role>-i<N>.json` | Per-iteration audit JSON with machine-checkable verdicts |
| `audit/transcript.md` | Dispatch history: agent, role, tokens, verdict, audit link |
| `audit/signoff-<plan-id>.json` | Terminal verdict: signoff, reason, next action |
| `audit/gate-state.json` | Gate-clearance state and active breakers |
| `INBOX.md` | Append-only operator log: gate pauses, breakers, signoff |

## How DontPanic Works

1. **Plan lock** — convert work into `plan.md`, `features.json`, and `decisions.jsonl`.
2. **Build** — an implementer agent executes the plan inside guardrails.
3. **Cross-model audit** — a different model family audits the work.
4. **Human gate** — risky changes pause with evidence and a clear approval choice.
5. **Approve** — only approved work can proceed toward merge.

## What You Get

DontPanic is more than a dispatch command. The current platform gives humans
and agents a shared operating surface:

| Capability | What it solves | Command surface |
|---|---|---|
| Plan lifecycle | Turns vague work into a locked, auditable contract | `dontpanic plan lock`, `plan audit`, `plan close` |
| Scope governance | Catches over-scope / weak ACs / undeclared prereqs before a paid run; flags scope drift, cross-feature edits, and design-decomposition risk | `dontpanic plan-review`, `plan-review --since`, `plan lock --design-review` |
| Planning readiness | Shows which plans/features are ready, blocked, or risky to run in parallel | `dontpanic next` |
| Cross-model dispatch | Separates implementation from approval | `dontpanic dispatch-from-plan` |
| Human gates | Pauses risky work until the operator reviews evidence | `dontpanic approve`, `resume`, `ps` |
| Local dashboard | Shows What Now, status, capabilities, gates, warnings, and project scope | `dontpanic dashboard build`, `open`, `serve` |
| Multi-repo registry | Lets one DontPanic install manage many projects | `dontpanic projects add`, `list`, `show`, `remove` |
| Capability readiness | Shows which external integrations are ready, missing setup, or blocked | `dontpanic capabilities status`, `setup` |
| Install reconciliation | Detects stale local setup after the platform evolves | `dontpanic reconcile baseline`, `reconcile check` |
| Architecture map | Generates a visual map and detects drift after manual edits | `dontpanic architecture regen`, `status`, `diff` |
| Release impact advisory | Warns when public docs, changelog, schemas, dashboards, or onboarding may need updates | `dontpanic next`, `dontpanic plan lock` |
| Agent access | Lets Claude Code, Cursor, OpenClaw, Codex, and MCP clients call DontPanic safely | `dontpanic manifest`, `mcp serve` |
| State projection | Exposes read-only status for dashboards, agents, and adapters | `dontpanic state snapshot`, `state export-dashboard` |

The default posture is local-first and preview-before-mutation. External
systems such as Firebase, Discord, Linear, OpenClaw, and Printing Press are
capabilities you opt into; they are not required for core use.

## 60-Second Start

The preferred command is `dontpanic`. You need Python 3.10+, git, and at least
one local agent CLI if you want to dispatch real work.

### 1. Install

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

### 2. Orient A New Agent, Then Configure Roles

A new agent (human or AI) starts by reading the generated operating brief — the
operator-vs-worker distinction, role catalog, and the canonical command flow:

```bash
dontpanic agent brief          # the onboarding brief; `dontpanic agent` alone prints it too
dontpanic agent whoami         # classify THIS agent (operator vs registered worker)
```

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

### 3. Onboard An Agent And A Repo

DontPanic distinguishes two roles: an **operator** (a human or interactive agent
that *runs* DontPanic — locks plans, approves gates, reads guidance) and a
**worker** (an agent DontPanic *dispatches* to implement or audit, e.g.
claude / codex). A worker must be a registered executor; an operator-only agent
cannot be assigned the `implementer`/`auditor` roles.

**New agent — read the operating brief and check agent readiness:**

```bash
dontpanic agent brief            # human-readable operating brief
dontpanic doctor --agent         # CLI, manifest, roles, homes readiness
```

**New repo — register and onboard in one step.** `--onboard` writes the managed
`AGENTS.md` block so a fresh clone is agent-ready immediately:

```bash
dontpanic projects add myapp /absolute/path/to/myapp --onboard
dontpanic doctor --project myapp     # this project's onboarding/config/roles
```

Re-onboarding an already-registered repo requires the explicit overwrite flags
(`--onboard --force --yes`).

**Assign roles** (workers must be registered executors) and set project-scoped
runtime evidence:

```bash
cd /absolute/path/to/myapp
dontpanic project config set roles.implementer claude
dontpanic project config set roles.auditor codex
dontpanic project config set runtime_evidence.web.base_url http://localhost:3000
```

**See what is configured and what still needs setup** — across machine and
project scope, classed `ok` / `needs_setup` / `missing` / `human_required`:

```bash
dontpanic config inventory               # current repo / machine scope
dontpanic config inventory --project myapp
```

When any item needs a human, the response carries exactly **one** dashboard hint
(the active URL if a dashboard is running, otherwise the start command). The full
new-agent / new-repo / role-assignment / inventory walkthrough lives in
[`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md).

### 4. Run The Doctor

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

### 5. Open The Local Dashboard

The dashboard is local-first. It does not require Firebase.

```bash
dontpanic dashboard build
dontpanic dashboard open
```

For a live localhost view while you work:

```bash
dontpanic dashboard serve
```

The dashboard binds `127.0.0.1` only and runs **one server per DontPanic home**.
A second `serve` for the same home is refused with the URL of the one already
running — open that instead of stacking servers. Pass `--replace` (alias
`--force-single`) to intentionally stop a stuck server and take over; a crashed
server's stale record is pruned automatically on the next `serve`. When work is
blocked, `dontpanic what-now <plan>` and `dontpanic config inventory` tell you
whether a dashboard is already running (and its URL) or print the start command
— see [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md) for the full
new-agent / new-repo onboarding and dashboard decision flow.

### 6. Try A Safe Sample Plan

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

### 7. Dispatch Real Work

New plans live under `docs/plans/<YYYY-MM-DD-NNN-type-name>/` with `plan.md`,
`features.json`, and `decisions.jsonl`. Validate and lock before dispatch:

```bash
python3 claude/shared/schemas/v1.0/validate.py docs/plans/<plan-id>/
dontpanic plan lock docs/plans/<plan-id>/
```

Before you dispatch, ask DontPanic what is actually ready:

```bash
dontpanic next
dontpanic next --format=json
```

`dontpanic next` reads plan dependencies, feature dependencies, gate state,
capability requirements, active supervisors, and release-impact signals. It
does not dispatch anything. It explains which work is ready, which work is
blocked, where parallel work may collide, and which public docs or changelog
surfaces may need attention before merge.

For a per-stage skill rubric, and a ranked decision set when work is blocked:

```bash
dontpanic skills recommend <plan-id>      # which skills to invoke for this stage
dontpanic what-now <plan-id> --feature F001   # ranked moves when blocked
```

`what-now` turns a blocked dispatch (quota cooldown, budget ceiling, iteration
cap, a cleared `pre_merge` signoff, a tripped breaker, a setup gap) into a short
list with an exact command where one is safe to emit. The supervised
implement→audit loop is `dontpanic orchestrate <plan-id>` (preview) /
`--confirm` (run); the lower-level `dispatch-from-plan` below is the same engine
with explicit per-step control.

Preview dispatch:

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

Clear gates when prompted:

```bash
dontpanic ps
dontpanic approve <plan-id> <gate>
dontpanic resume <plan-id> --all
```

Close the plan after all features pass:

```bash
dontpanic plan close docs/plans/<plan-id>/
```

## Prerequisites

Required:

- **macOS** or Linux with **zsh** or **bash**
- **Python 3.10+** with `pip`
- **git**

Optional, depending on which agents and evidence surfaces you wire:

- **Claude Code / claude CLI** — common implementer
- **Codex CLI** — common cross-vendor auditor
- **gcloud SDK** / **firebase-tools** — only for Firebase-backed projects or backend evidence capture
- **jq** — useful for inspecting JSON evidence
- **ollama** — local OSS models for safety/embeddings
- **gemini CLI** — multimodal review + long-context review
- **terminal-notifier** — desktop pings; `INBOX.md` remains the durable channel

The editable install pulls the runtime Python dependencies from `pyproject.toml`.
Use the `dev` extra when you want to run tests and formatting locally.

## Run Tests

```bash
PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/ -q
ruff check scripts/
ruff format --check scripts/
python3 scripts/sanitization_check.py
```

## Self-Contained By Default

Install DontPanic. It works by itself. The schemas it validates against are
vendored under `claude/shared/`; no separate schema repo is required to install
or run. External integrations are optional.

| Integration | Kind | What it adds | When you need it |
|---|---|---|---|
| OpenClaw | Runtime | Multi-channel agent UI | Multi-channel surfaces in front of DontPanic-orchestrated work |
| Hermes `/goal` pattern | Conceptual | Shared workflow vocabulary | You want a shared mental model with other agent-driven teams |
| Firebase dashboard adapter | Runtime | Realtime team dashboard | Multi-operator collaboration |
| Printing Press adapters | Runtime | External service evidence providers | OpenAPI-shaped service wrapping |
| agent-conventions upstream | Maintainer | Schema authoring and external validators | You are building tools that validate DontPanic artifacts outside DontPanic |

Each integration is opt-in. None is installed automatically. The core
`dontpanic` install includes the CLI, supervisor/dispatch, doctor/init/new,
vendored schemas, validators, MCP server, state projection, static dashboard,
docs, templates, and examples.

## Deeper Architecture

DontPanic is portable trust infrastructure for bounded agent work. It routes
intent through reusable skills and learned memory, turns non-trivial work into
machine-checkable plans, executes those plans across model/vendor boundaries,
and preserves proof through audits, evidence, signoff, and protected-path
checks.

The implementation has four layers:

```
Identity & governance        ← SOUL.md, AGENTS.md, USER.md
Routing & contracts          ← claude/RESOLVER.md, claude/shared/
Execution units              ← claude/skills/, docs/plans/<id>/
Multi-agent panel + bounds   ← Claude / Codex / Gemini / Grok / OSS + circuit breakers
```

Each layer's output becomes the next layer's contract. Plans live in
`docs/plans/<YYYY-MM-DD-NNN-type-name>/` with `features.json` as machine-checkable
ground truth. Different model families audit each other so no single vendor
self-approves.

The platform thesis is captured in [`docs/PLATFORM.md`](./docs/PLATFORM.md).
The plain-English product overview is in [`docs/PRODUCT.md`](./docs/PRODUCT.md).
The current build plan is in [`docs/ROADMAP.md`](./docs/ROADMAP.md).

## Vocabulary

See [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md) for a slower
walkthrough and [`docs/AGENT_QUICKSTART.md`](./docs/AGENT_QUICKSTART.md) for
the flow an AI caller should follow. If you already use Hermes-style `/goal`
workflows, DontPanic maps that pattern to locked plans, implementer/auditor
roles, audit envelopes, and human approval gates.

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
- [x] 8 circuit breakers (budget_ceiling, iteration_cap, no_progress, diminishing_returns, convergence_collapse, wall_clock, environmental_blocker, global_circuit_breaker)
- [x] Vendor-native quota tracker (`scripts/quota_check.py` v2 schema)
- [x] Operator caps + Claude calibration (`~/.dontpanic/quota_caps.json`, `~/.dontpanic/quota_calibration.json`)
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
