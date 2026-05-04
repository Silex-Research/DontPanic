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

**Status:** alpha — bootstrap phase. See [`docs/PRODUCT.md`](./docs/PRODUCT.md)
for the plain-English product overview, [`docs/ROADMAP.md`](./docs/ROADMAP.md)
for the current build plan, and [`docs/plans/`](./docs/plans/) for active work.

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

---

## Prerequisites

Required:

- **macOS** (Linux likely works, untested) with **zsh** or **bash**
- **gcloud SDK** 500+ — `brew install --cask google-cloud-sdk`
- **firebase-tools** 15+ — `npm install -g firebase-tools` (Node 20+)
- **Python 3.10+** with `pip` — `brew install python@3.11`
- **jq** — `brew install jq`
- **bq** (BigQuery CLI) — bundled with gcloud
- **git** with `git subtree` (default in modern git)

Optional (depending on which agents you wire):

- **ollama** — `brew install ollama` (local OSS models for safety/embeddings)
- **codex CLI** — adversarial auditor (different vendor → no self-approval)
- **gemini CLI** — multimodal review + 2M context
- **xAI API key** — Grok currency check / third opinion
- **terminal-notifier** — `brew install terminal-notifier` (INBOX async channel)

Python deps: `pip3 install firebase-admin pydantic jsonschema pyyaml datamodel-code-generator`

---

## Quickstart

The preferred command is `dontpanic`. The legacy `jarvis` alias still works.

### 1. Clone

```bash
git clone https://github.com/Silex-Research/DontPanic.git
cd DontPanic
python3 -m pip install -e .
```

### 2. Bootstrap your own GCP/Firebase project

Pick a fresh GCP project ID (do NOT reuse the maintainer's campaign project)
and a billing account, then run:

```bash
gcloud auth login
gcloud auth application-default login
firebase login

scripts/bootstrap.sh \
  --project your-project-id \
  --billing-account XXXXXX-XXXXXX-XXXXXX
```

The script links billing, enables required APIs, creates the orchestrator
service account with scoped roles, deploys storage + firestore rules, and
generates a local `environments.json` + `.firebaserc` from the tracked
`.example` templates. SA keys are **off by default** — pass `--create-key`
explicitly if your local agents need one (the script verifies `.secrets/`
is gitignored before writing).

Pass `--dry-run` to preview every command without executing.

### 3. Verify

```bash
export DONTPANIC_FIREBASE_PROJECT=your-project-id

# Full check — needs `gcloud auth login` + `firebase login` first
python3 scripts/jarvis_doctor.py

# Or, before you've authenticated the CLIs (fresh clone smoke):
python3 scripts/jarvis_doctor.py --skip-auth
```

Both modes should print `✓ N/N checks passed — DontPanic is ready`. Each
red check includes a remediation line. Then run the storage smoke test:

```bash
PYTHONPATH=scripts python3 -m dontpanic_orchestrate.smoke_test_storage
```

If it prints `✓ F002 acceptance PASS`, evidence storage is wired.

### 4. Validate your first plan

```bash
python3 claude/shared/schemas/v1.0/validate.py \
  docs/plans/2026-04-19-001-infra-cross-agent-orchestration
```

Should print all green checkmarks.

### 5. Run the test suite

```bash
PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/ -q
ruff check scripts/
ruff format --check scripts/
```

These four commands are the exact local equivalents of the
[GitHub Actions CI workflow](.github/workflows/ci.yml). See
[CONTRIBUTING.md](./CONTRIBUTING.md) for the contributor flow.

### 6. Run your first volley

End-to-end flow from a fresh checkout to a signed-off dispatch:

**1. Refresh the local quota signal** (writes `~/.jarvis/quota_state.json`):

```bash
python3 scripts/quota_check.py
```

**2. Seed your operator caps file** (`~/.jarvis/quota_caps.json`):

```bash
dontpanic quota-caps init
dontpanic quota-caps show
```

**3. Calibrate Claude** against your real plan-usage dashboard at
[claude.ai/settings/usage](https://claude.ai/settings/usage). Read the percent
shown in the weekly bar and pass it as `--dashboard-pct`:

```bash
dontpanic calibrate-claude --dashboard-pct 13
```

This writes a sticky calibration to `~/.jarvis/quota_calibration.json`. Re-run
weekly; `quota_check.py` warns at >7 days. Calibration is Claude-only — Codex
and Gemini meter against direct local signals.

**4. Author or pick a plan.** New plans go under
`docs/plans/<YYYY-MM-DD-NNN-type-name>/` with `plan.md`, `features.json`, and
`decisions.jsonl`. Validate before dispatching:

```bash
python3 claude/shared/schemas/v1.0/validate.py docs/plans/<plan-id>/
```

**5. Preview the dispatch.** `dispatch-from-plan` is **strict dry-run by default**
— it prints a 10-field pre-flight context block (resolved plan path, feature,
tier, target_env, target_project, implementer, auditor, gates, max_iterations,
quota readiness) and exits 0 without dispatching, regardless of TTY state:

```bash
dontpanic dispatch-from-plan <plan-id>
```

If quota readiness is one of `missing_state` / `config_required` /
`calibration_required` / `unit_mismatch`, the preview prints the label and the
matching remediation pointer; `--confirm` will refuse with exit 3 until you fix
it. `dispatch-from-plan --help` lists the four states with one-line fixes.

**6. Authorize the dispatch.** Add `--confirm` to call
`supervisor.dispatch_volley` in-process (no subprocess shell-out, same Python
interpreter). Forwarded flags: `--feature F001`, `--implementer claude`,
`--auditor codex`, `--max-iterations N`, `--mode interactive|autonomous`. P0
class is plan-derived only and cannot be forced via `--mode`.

```bash
dontpanic dispatch-from-plan <plan-id> --confirm
```

`target_env: prod` blocks dispatch unless `plan.tier=p0`. Use `dev` until ready.

**7. Watch the run.** Five operator-facing artifacts land under the plan dir as
the volley runs:

| Path | What it is |
|---|---|
| `audit/<agent>-<role>-i<N>.json` | Per-iteration audit JSON (machine-checkable verdict) |
| `audit/transcript.md` | One row per dispatch — agent, role, tokens in/out, verdict, audit link |
| `audit/signoff-<plan-id>.json` | Volley-terminal verdict (signoff: true/false, reason, next_action) |
| `audit/gate-state.json` | Gate-clearance state (cleared_gates, history, active_breakers) |
| `INBOX.md` | Append-only operator log: gate_paused, breaker_tripped, signoff |

**8. Engage when paused.** The supervisor pauses on declared `human_gates`
(`pre_impl`, `pre_merge`, …) and on tripped breakers (`breaker:budget_ceiling`,
`breaker:diminishing_returns`, …). INBOX names the gate; clear it with:

```bash
dontpanic ps                                  # active supervisors
dontpanic approve <plan-id> <gate>            # clear one gate
dontpanic resume <plan-id> --all              # explicit bulk clear
```

**Gotchas:** `--max-iterations 1` still permits two rounds (iter 0 + iter 1)
before the diminishing-returns breaker can fire. The Codex auditor runs
`--sandbox read-only` and **cannot independently rerun pytest** — it inspects
the implementer's recorded evidence rather than re-running tests. The cross-
vendor adversarial invariant (no Claude grading Claude) only holds in
`--volley` mode; single-agent `--role auditor` resolves the agent from
`agents_required[0]` today.

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
├── scripts/
│   ├── dontpanic_orchestrate/          # supervisor runtime
│   ├── bootstrap.sh                 # one-shot GCP/Firebase setup
│   ├── jarvis_doctor.py             # preflight health checks
│   ├── sanitization_check.py        # sanitization regression guard
│   └── quota_check.py               # LLM tokens → ~/.jarvis/quota_state.json
│
├── dashboard/                       # Firebase Hosting static SPA
│   └── state/                       # agents.json, tasks.json, …
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
| LLM tokens | Per-model session logs (Claude/Codex/Gemini/Grok) + Ollama probe | `~/.jarvis/quota_state.json` | Circuit breakers (defer dispatch when weekly quota near cap) |

Run `python3 scripts/quota_check.py` for LLM tokens (every ~30 min during active work). GCP $ refresh is operator-specific (project list, app categorization, billing-export project all vary) and is not shipped as a bundled script.

---

## Setup checklist (running list — what new users need)

This list grows as we build. If a feature requires new setup, it lands here.

Bootstrap (`scripts/bootstrap.sh`):

- [x] gcloud + firebase CLI authenticated
- [x] Firebase project linked to billing
- [x] APIs enabled: Firestore, Firebase Storage, IAM, IAM Credentials
- [x] GCS evidence bucket created
- [x] `orchestrator` service account + 4 roles + JSON key in `.secrets/`
- [x] firebase-admin Python SDK installed
- [x] Storage smoke test passes

Supervisor + executor panel (shipped):

- [x] Single-agent + volley dispatch (Claude / Codex / Gemini / Grok / Ollama executors)
- [x] 7 circuit breakers (budget_ceiling, iteration_cap, no_progress, diminishing_returns, convergence_collapse, wall_clock, global_circuit_breaker)
- [x] Vendor-native quota tracker (`scripts/quota_check.py` v2 schema)
- [x] Operator caps + Claude calibration (`~/.jarvis/quota_caps.json`, `~/.jarvis/quota_calibration.json`)
- [x] Engagement surface (`INBOX.md`, `signoff-<plan-id>.json`, `transcript.md`, `gate-state.json`)
- [x] CLI surface: `dispatch-from-plan`, `quota-caps`, `calibrate-claude`, `approve`, `resume`, `ps`, `claude-touch`

Operator-local prerequisites (per machine):

- [ ] Codex / Gemini / Grok CLIs authed (only the agents your plans use)
- [ ] `terminal-notifier` installed (`brew install terminal-notifier`) for desktop pings — optional; INBOX.md is the durable channel
- [ ] `~/.jarvis/quota_caps.json` initialized (`quota-caps init`) and Claude calibrated (`calibrate-claude --dashboard-pct N`)
- [ ] Re-calibrate Claude weekly (`quota_check.py` warns at >7 days)
- [ ] BigQuery billing export configured (manual, Console only) — optional, only needed for app-level $ tracking

---

## Contributing

`CONTRIBUTING.md` and `CODE_OF_CONDUCT.md` coming with the open-source push (parent F022). For now: read `AGENTS.md`, follow the conventions in `claude/shared/conventions/`, and write plans before code.

## License

License coming with F022. Until then, treat as all rights reserved.
