# Jarvis Roadmap — Substrate → Access Layer → Intake → Agent-Native

This document is the canonical phased build plan that takes Jarvis from
"a private orchestration repo for one operator" to "a global tool that
agents and humans can install, configure, and use across many projects."

It is the long-form companion to [`PRODUCT.md`](./PRODUCT.md) (what
Jarvis is in plain English) and [`PLATFORM.md`](./PLATFORM.md) (the
five-layer architecture thesis).

## Substrate (already shipped)

The current platform substrate is structurally complete. Recent plans
that built it:

| Plan | What it shipped |
|---|---|
| `2026-04-19-001-infra-cross-agent-orchestration` | Parent platform: schemas, supervisor, executors, plan/features/audit contracts |
| `2026-05-01-005-feat-target-context-platform-fix` | EC5 audit_writer prelude auto-injection + severity classifier |
| `2026-05-02-002-fix-audit-envelope-filename` | Per-feature audit envelope isolation |
| `2026-05-02-003-feat-nested-orchestration-v1` | Parent/child plans + depth/cycle/repeated-finding guards + child charter + parent pause/fan-in |
| `2026-05-02-004-fix-diminishing-returns-signature-based` | Signature-based convergence detection (no false-positive count trips) |

What works today:

- plan-locked execution with adversarial volley
- human gates + circuit breakers + quota awareness
- per-plan audit envelopes, evidence, signoff, decisions log
- nested orchestration with anti-recursion guarantees
- target-context enforcement
- 24 reusable skills (autoresearch, plan-artifacts, security-review,
  cost-model, product-health-agent, kronos-agent, …)
- memory layer (durable lessons across sessions)
- security baseline (sanitization scan, CI hardening, SECURITY.md)

What is missing: **the access layer that lets anyone other than the
original operator reach the substrate**, plus the **intake layer that
turns ambiguous requests into valid plans** without forcing humans to
hand-author the conventions.

## Phase A — Global Install + Project Registry

**Status:** locked at `docs/plans/2026-05-03-001-feat-global-install-project-registry/`.

**Audience:** technical solo dev / friend / OSS user.

**Why first:** Jarvis should not be trapped inside one repo. It should
be a global tool that can work across many projects. Every later phase
assumes a global install + multi-project registry exist.

**Deliverables:**

- `pipx install jarvis-orchestrate` and a global `jarvis` console
  script (kills `PYTHONPATH=…` friction permanently and isolates Jarvis's
  own deps from project venvs).
- `jarvis projects add | list | show | remove` against
  `~/.jarvis/projects.json`.
- Per-project `.jarvis/jarvis.json` config (committable per project; can
  override global agent defaults).
- Global config at `~/.jarvis/config.json` (default agent pair, default
  tier, calibration pointers).
- `jarvis doctor` integrates global + per-project preflight checks.
- README quickstart: install → register one project → first dry-run in
  under 5 minutes.

**Acceptance:** see plan dir.

## Phase B — Project Init + Discovery

**Status:** outlined; not locked. Lock after Phase A ships.

**Audience:** any user adding Jarvis to a new or existing project.

**Goal:** make Jarvis adapt to projects without forcing the operator to
memorize six conventions.

**Likely deliverables:**

- `jarvis init` — walks the registered project, detects language /
  test runner / build system / `.firebaserc` / governance docs
  (CLAUDE.md, AGENTS.md, GLOBAL_STANDARDS, ADR/), proposes
  `environments.json` + default `human_gates` + `protected_paths` +
  agent registry.
- One confirmation screen before any commit.
- Idempotent: re-init refreshes detected config, never clobbers
  human-confirmed config.
- Distinguishes `detected` vs `suggested` vs `human-confirmed` config so
  re-runs are safe.
- Writes the **allowed-plans-directory** config used by future remote
  surfaces.

**Key rule:** Jarvis may suggest governance. It may not silently invent
it.

## Phase C — Intake Pipeline (turn messy input into a valid plan)

**Status:** outlined; not locked. The most ambitious phase — needs its
own multi-feature plan when the time comes.

**Audience:** developers, founders, product builders, AI agents.

**Goal:** bridge from "I have an idea / problem" to "agents can safely
work on this."

**Likely deliverables:**

- `jarvis intake prd <file>` — read PRD, run sufficiency check, draft
  plan or return clarification questions.
- `jarvis intake feature <file>` — feature brief → scoped plan.
- `jarvis intake issue <file>` — production issue → root-cause plan.
- `jarvis intake parity <source> <target>` — parity work → parity plan.
- **Sufficiency checker** — LLM-driven, runs against documented
  criteria per work-type (PRD vs incident vs parity vs feature).
- **Research / discovery mode** — when a request is vague, Jarvis
  inspects repo + docs + ADRs + prior plans + logs (if permitted)
  before drafting.
- **Discovery-plan fallback** — if implementation is premature, propose
  a research plan with its own acceptance criteria.
- Human approval before any implementation dispatch.

**Sufficiency criteria (what counts as "ready to plan"):**

For any work-type, Jarvis must be able to define: project, desired
outcome, target surface, constraints, acceptance criteria, risk level,
evidence needed, scope boundary. Per-type criteria are documented in
[`PRODUCT.md`](./PRODUCT.md).

**Why this is hard:** the sufficiency checker is itself an LLM call
against documented criteria. It has cost-model implications and needs
its own circuit breakers (don't infinite-loop "ask one more
question"). When this phase locks, expect 4–5 features and substantive
locked decisions on what counts as sufficient and how the discovery
budget is bounded.

## Phase D — Agent Discovery + MCP

**Status:** outlined; not locked. Lock after Phases A + B (and ideally
C) ship.

**Audience:** AI agents — Claude Code, Cursor, OpenCode, Codex CLI when
it ships MCP, custom Anthropic / OpenAI SDK agents.

**Goal:** an agent reading the Jarvis GitHub URL should know how to
install, configure, and call Jarvis without operator hand-holding.

**Likely deliverables:**

- **Root `agent.json` manifest** — copy-paste install instructions,
  required config questions, safe-command list, MCP-tool catalog.
  Lives at the repo root so an agent can fetch it directly from
  GitHub.
- **`jarvis mcp serve` (localhost)** — typed tools for AI agents:
  - `jarvis.projects` — list/add registered projects
  - `jarvis.intake` — submit a brief, get plan / questions / discovery
  - `jarvis.plan_validate` — schema-validate a plan dir
  - `jarvis.dispatch` — start a volley
  - `jarvis.status` — check active supervisors + gate state
  - `jarvis.approve_gate` — clear a declared gate
  - `jarvis.read_evidence` — fetch evidence for a plan + iteration
- **Discoverability commitments** — PyPI metadata, GitHub topic tags
  (`mcp-server`, `ai-orchestration`, `multi-agent`, `local-first`,
  `code-review`), MCP-directory listing, copy-paste `mcp.json` snippet
  in the README.
- **Stable LLM-authored-plan schema** documented in the README so any
  LLM (ChatGPT, Grok, Claude.ai, local model) can produce a plan dir
  that `jarvis plan validate` accepts.

**Acceptance:** a user can paste the Jarvis GitHub URL into Claude
Code, Codex CLI, Cursor, or a Clawdbot-style agent and say "install
this and set it up for my project" and the agent succeeds.

## Phase E — Use Existing Remote Agent Surfaces (not a custom daemon)

**Status:** demand-driven. Do not build until the existing surfaces
prove insufficient.

**Goal:** make Jarvis easy for existing remote-agent infrastructure to
install, configure, and operate safely. Do **not** build a hosted
Jarvis SaaS or a custom remote daemon.

Existing surfaces that absorb the remote-execution burden:

- Clawdbot-style GitHub / agent runners
- Claude-managed agents
- Claude dispatch workflows
- Codex / Claude CLI running on the user's machine
- GitHub-based workflows where appropriate
- Remote MCP clients where safe

**Concrete change vs the prior roadmap:** earlier drafts had a custom
`jarvis serve` HTTP daemon as Phase C. That is now deprioritized.
After Phases A+B+C+D the remote-execution path runs through tools the
user already has, not a new server we have to build, secure, and
maintain. Build a custom daemon only if real usage proves these
existing surfaces cannot carry the load.

**If a daemon does become necessary later, the threat model is already
written:** allowed-plans-directory enforcement, API token + session
token distinction, `~/.jarvis/audit.jsonl` global audit, OpenAPI 3.1
spec for ChatGPT Custom Actions, Tailscale Funnel preferred over
ngrok. None of that needs to be built now.

## Phase F — Governance V2

**Status:** demand-driven on the first real recursive finding (D012
trigger of plan 2026-05-02-003).

**Goal:** governance bootstrap — objective contracts, governance
assessment, project maturity detection, governing-doc discovery, ADR
proposal workflow, standards-gap records, parity governance, UX/QA
matrices, stage-aware orchestration.

**Why deferred:** the substrate already prevents recursion chaos
(D013, plan 003). What's missing is the operating layer above it. But
that layer's shape is unknown without a real recursive case to
inform it. Build when projects prove the need; don't speculate at
shapes.

The candidate "Nested Orchestration V2 — Governance Bootstrap" plan is
already sketched in plan 2026-05-02-003 D013 with three features
(objective_contract + governing-docs inheritance; governance_assessment
+ standards_gap records; adr_proposal + parent approval). When the
trigger fires, that's the starting point.

## Sequencing Summary

```
Phase A (lock now)  →  Phase B (lock after A)  →  Phase C (lock after B)
                                                       ↓
            Phase D (lock alongside or after C — agent-native surface)
                                                       ↓
            Phase E — demand-driven (only if existing remote surfaces fail)
                                                       ↓
            Phase F — demand-driven (governance V2 trigger)
```

Each phase is lockable as its own plan with its own decisions. Don't
bundle. The discipline is the same the substrate followed: lock the
slice, ship it, learn from it, lock the next.

## What Each Stakeholder Gets

| Stakeholder | After Phase A | After Phase B | After Phase C | After Phase D |
|---|---|---|---|---|
| Solo dev / friend | global install, multi-project registry | one-command project setup | submit a brief, get a plan | agent in their IDE calls Jarvis as a tool |
| Founder / product builder | (not yet) | (not yet) | submit a PRD, get verified delivery | (richer; agent surfaces) |
| AI coding agent | install via pipx | discover project context | submit work via intake | invoke as MCP tool, read README to self-onboard |
| Remote operator | (not yet) | (not yet) | (not yet) | dispatch via Claude / ChatGPT / Clawdbot through their existing remote surfaces |

By Phase D, the marketing pitch in `PRODUCT.md` becomes deliverable
without building any custom remote infrastructure.
