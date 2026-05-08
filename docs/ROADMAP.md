# DontPanic Roadmap — Substrate → Agent Access → Intake → Ecosystem

This document is the canonical phased build plan that takes DontPanic from
"a private orchestration repo for one operator" to "the verified
software-delivery layer that OpenClaw, Claude Code, Codex CLI,
Cursor, Claude-managed agents, and MCP clients can call across many
projects."

It is the long-form companion to [`PRODUCT.md`](./PRODUCT.md) (what
DontPanic is in plain English), [`ECOSYSTEM.md`](./ECOSYSTEM.md) (who
calls DontPanic and what it is *not* trying to be), and
[`PLATFORM.md`](./PLATFORM.md) (the five-layer architecture thesis).

## Strategic frame

> DontPanic: the safety layer between “the agent says it’s done” and
> “you merge it.”

DontPanic is the verified software-delivery layer. It is not a
personal-agent runtime. Mature systems already own the runtime
surface — chat, channels, mobile, scheduling, plugin marketplaces — and
DontPanic is designed to be **called by** those systems. Every phase
below names the build that makes that calling pattern progressively
more accessible. See [`ECOSYSTEM.md`](./ECOSYSTEM.md) for the explicit
caller-pattern recipes and the deliberate non-goals.

## Substrate (already shipped, before Phase A)

The platform substrate that Phase A built on top of:

| Plan | What it shipped |
|---|---|
| `2026-04-19-001-infra-cross-agent-orchestration` | Parent platform: schemas, supervisor, executors, plan/features/audit contracts |
| `2026-05-01-005-feat-target-context-platform-fix` | EC5 audit_writer prelude auto-injection + severity classifier |
| `2026-05-02-002-fix-audit-envelope-filename` | Per-feature audit envelope isolation |
| `2026-05-02-003-feat-nested-orchestration-v1` | Parent/child plans + depth/cycle/repeated-finding guards + child charter + parent pause/fan-in |
| `2026-05-02-004-fix-diminishing-returns-signature-based` | Signature-based convergence detection (no false-positive count trips) |
| `2026-05-03-001-feat-global-install-project-registry` | **Phase A.** Global install, project registry, per-project config, override precedence, `dontpanic doctor` / `jarvis doctor` compatibility |

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
- **global install + multi-project registry + per-project config +
  override precedence + `dontpanic doctor`** (Phase A, just shipped)

What is missing: **the agent-callable access surface** (Phase B —
manifest + thin MCP) and **the intake pipeline** that turns
ambiguous requests into valid plans (Phase C). After those, DontPanic
delivers on the ecosystem-position framing in
[`ECOSYSTEM.md`](./ECOSYSTEM.md).

Planned external adapter work should credit the source ecosystem rather
than present it as native DontPanic capability. In particular, the
Printing Press adapter direction builds on
[CLI Printing Press](https://github.com/mvanhorn/cli-printing-press) and
the [Printing Press Library](https://github.com/mvanhorn/printing-press-library),
which supply the agent-native CLI/MCP pattern DontPanic is evaluating for
SaaS evidence sources. DontPanic's boundary remains the trust layer:
allowlists, provenance, read-only policy, redaction, normalized evidence,
and signoff.

## Phase A — Global Install + Project Registry  [SHIPPED]

**Status:** **shipped 2026-05-03** in plan
`docs/plans/2026-05-03-001-feat-global-install-project-registry/`
(F001 + F002 + F003, all signed off).

**Audience:** technical solo dev / friend / OSS user.

**Why first:** DontPanic should not be trapped inside one repo. It is
now a global tool that can work across many projects. Every later
phase builds on top of this substrate.

**What shipped:**

- `pipx install` and a global `dontpanic` console script via PEP 621
  packaging (kills `PYTHONPATH=…` friction permanently and isolates
  DontPanic's own deps from project venvs). The legacy `jarvis` alias
  remains available during the staged migration.
- `dontpanic projects add | list | show | remove` backed by
  `~/.dontpanic/projects.json` (legacy `~/.jarvis/projects.json`
  fallback; D003 name regex, non-clobber semantics, `--json` output
  across all subcommands).
- Per-project `<repo>/.dontpanic/dontpanic.json` config (committable
  per project; legacy `<repo>/.jarvis/jarvis.json` remains readable;
  overrides global agent defaults).
- Global config at `~/.dontpanic/config.json` (legacy `~/.jarvis`
  fallback; default agent pair, default tier, calibration pointers).
- Override precedence at dispatch time: per-project > global >
  hardcoded fallbacks (D004), wired into both `dispatch_volley` and
  `dispatch_single_agent`.
- `dontpanic doctor` per-project preflight (path / dontpanic.json /
  legacy jarvis.json / plans_dir / agents / gates) with the 0/1/2
  strict exit-code matrix.
- `_resolve_plan_dir` is registry-aware: cwd-anchored project →
  walk-the-registry → gated cwd-fallback for un-registered repos.

## Phase B — Agent Access Manifest + Thin MCP Surface

**Status:** shipped in plan
`docs/plans/2026-05-03-003-feat-agent-access-manifest-thin-mcp/`.
F001 shipped the global manifest, F002 shipped the thin local MCP server,
F003 shipped agent discoverability docs, and F004 shipped the LLM-authored-plan
schema documentation.

**Audience:** AI agents (OpenClaw skills, Claude Code, Codex CLI,
Cursor, Claude-managed agents, custom MCP clients) and the runtimes
that host them.

**Strategic frame:** this is the phase that makes DontPanic
**callable** by the ecosystem. The shape of "DontPanic is the verified
software-delivery layer" requires (a) any agent can find DontPanic on a
machine without operator hand-holding, and (b) a thin tool surface
those agents can call without a full-runtime integration. See
[`ECOSYSTEM.md`](./ECOSYSTEM.md) for the caller-pattern recipes.

**Likely deliverables:**

- **`~/.dontpanic/agent-manifest.json`** — global discovery file answering
  "how does an agent find and invoke DontPanic on this machine?" Contains:
  DontPanic version, install source, CLI path, common commands, MCP server
  command, safety rules, project registry pointer, supported intake
  types, default agent roles. Machine-level — not committed to
  project repos. Legacy `~/.jarvis/agent-manifest.json` may be read for
  compatibility but new writes use `~/.dontpanic`. (Locked decision:
  this is the global manifest; project behavior stays in
  `<repo>/.dontpanic/dontpanic.json` from Phase A with legacy read
  compatibility. No per-project `agent.json` in v1.)
- **`dontpanic mcp serve` (local stdio MCP server)** — thin typed tool
  surface for agents. Shipped tools:
  - `list_projects` — read registered projects
  - `validate_plan` — validate a plan before asking the user to run it
  - `dispatch` — dry-run by default; `confirm: true` required to mutate
  - `status` — check active supervisors + gate state
  - `approve_gate` — dry-run by default; `confirm: true` required to mutate
  - `read_evidence` — read evidence under a registered plan
  There is deliberately no `intake` tool in Phase B. Phase C owns intake.
- **Discoverability commitments** — README caller examples, PyPI metadata,
  GitHub topic tags
  (`mcp-server`, `ai-orchestration`, `multi-agent`, `local-first`,
  `code-review`), MCP-directory listing, copy-paste `mcp.json` snippet
  in the README. See [`DISCOVERABILITY.md`](./DISCOVERABILITY.md).
- **Stable LLM-authored-plan schema** documented in
  [`AUTHORING_PLANS.md`](./AUTHORING_PLANS.md) so any LLM (ChatGPT, Grok,
  Claude.ai, local model) can produce a plan dir that `dontpanic plan
  validate` accepts.

**Acceptance:** an agent in OpenClaw / Claude Code / Codex CLI /
Cursor can read the global manifest and call the MCP tools (or shell
out to the CLI) without operator hand-holding. Phrased as the
non-goal: **DontPanic ships no chat surface, no scheduling, no
custom remote daemon, no plugin marketplace.** The caller's runtime
owns those concerns.

## Phase C — Intake Pipeline (turn messy input into a valid plan)

**Status:** outlined; not locked. Pulled forward from previous Phase
C since intake is DontPanic's core differentiation: this is what
"verified software-delivery layer" actually means in practice.

**Audience:** developers, founders, product builders, and the AI
agents calling DontPanic through Phase B's manifest + MCP surface.

**Goal:** bridge from "I have an idea / problem" to "agents can safely
work on this." A bounded bootstrap — start with PRD / issue / feature
intake to a draft plan; defer the broader intake operating model
until real usage informs it.

**Likely deliverables:**

- `dontpanic intake prd <file>` — read PRD, run sufficiency check, draft
  plan or return clarification questions.
- `dontpanic intake issue <file>` — production issue → root-cause plan.
- `dontpanic intake feature <file>` — feature brief → scoped plan.
- `dontpanic intake parity <source> <target>` — parity work → parity plan.
- **Sufficiency checker** — LLM-driven, runs against documented
  criteria per work-type. Has its own cost-model implications and
  circuit breakers (don't infinite-loop "ask one more question").
- **Research / discovery mode** — when a request is vague, DontPanic
  inspects repo + docs + ADRs + prior plans + logs (if permitted)
  before drafting. Subsumes the old "Project Init + Discovery"
  phase — discovery is a feature of intake, not a separate slice.
- **Discovery-plan fallback** — if implementation is premature, propose
  a research plan with its own acceptance criteria.
- Human approval before any implementation dispatch.
- The MCP `dontpanic.intake` tool from Phase B becomes the canonical
  caller surface for OpenClaw / Claude Code / Codex CLI agents.
- **External SaaS evidence adapters (planned, credited).** Evaluate
  Printing Press-generated or library-provided CLIs/MCP servers as
  read-only intake/sufficiency inputs for services such as Linear, Sentry,
  Slack, and Notion. Attribute this adapter pattern to CLI Printing Press;
  DontPanic owns only the adapter governance and evidence normalization.

**Sufficiency criteria (what counts as "ready to plan"):**

For any work-type, DontPanic must be able to define: project, desired
outcome, target surface, constraints, acceptance criteria, risk level,
evidence needed, scope boundary. Per-type criteria are documented in
[`PRODUCT.md`](./PRODUCT.md).

## Phase D — Ecosystem Hooks (light)

**Status:** outlined; not locked. Lock after Phase B ships and at
least one Phase C intake type ships, so we have something for the
ecosystem to call.

**Audience:** the operators of OpenClaw / Claude / Codex / Clawdbot-style
runtimes integrating DontPanic as a callable skill.

**Goal:** make DontPanic easy to integrate, **without** building a custom
daemon. This phase is mostly documentation + small enabling helpers.

**Likely deliverables:**

- **OpenClaw caller recipe** — a published skill template / plugin
  example showing how an OpenClaw skill calls
  `dontpanic intake | dispatch | status | approve` (sketched in
  [`ECOSYSTEM.md`](./ECOSYSTEM.md), formalized here).
- **Claude-managed-agent recipe** — same shape, expressed against
  Claude's managed-agent surface.
- **MCP client examples** — Cursor, Continue, IDE plugins.
- **Status webhook (optional)** — if existing runtimes need push
  notifications (gate paused, signoff complete) instead of polling
  `dontpanic status`, ship a thin webhook hook. Defer until real demand.
- **No custom remote daemon.** Existing surfaces (Clawdbot-style
  runners, Claude dispatch, OpenClaw Gateway, Codex / Claude CLI on
  the user's machine, GitHub-based workflows, remote MCP clients)
  carry the remote-execution burden. Build a custom daemon only if
  real usage proves these existing surfaces cannot carry the load —
  and the threat model is already pre-written if it ever becomes
  necessary (allowed-plans-directory enforcement, API + session token
  distinction, `~/.dontpanic/audit.jsonl` global audit, OpenAPI 3.1 spec
  for ChatGPT Custom Actions, Tailscale Funnel preferred over ngrok).

**Acceptance:** an operator running OpenClaw can install a small
DontPanic skill, paste their DontPanic CLI path, and have OpenClaw dispatch
real software work to DontPanic with full plan + audit + signoff
discipline. No SDK, no embedded library, no Gateway-side state.

## Phase E — Governance V2

**Status:** demand-driven on the first real recursive finding (D012
trigger of plan 2026-05-02-003). Renumbered from old Phase F since
the prior Phase E (custom daemon) is removed.

**Goal:** governance bootstrap — objective contracts, governance
assessment, project maturity detection, governing-doc discovery, ADR
proposal workflow, standards-gap records, parity governance, UX/QA
matrices, stage-aware orchestration.

**Why deferred:** the substrate already prevents recursion chaos
(D013, plan 003). What's missing is the operating layer above it. But
that layer's shape is unknown without a real recursive case to
inform it. Build when projects prove the need; don't speculate at
shapes.

The candidate "Nested Orchestration V2 — Governance Bootstrap" plan
is already sketched in plan 2026-05-02-003 D013 with three features
(objective_contract + governing-docs inheritance; governance_assessment
+ standards_gap records; adr_proposal + parent approval). When the
trigger fires, that's the starting point.

## What was removed from the prior roadmap

Two earlier phases are explicitly off the build plan:

- **Custom remote daemon (`dontpanic serve` HTTP service)** — replaced by
  Phase D's ecosystem-callers approach. Existing remote-agent
  infrastructure already solves remote execution; we don't need to
  build, secure, and maintain another server. The threat model
  remains pre-written if real usage ever proves the need.
- **Standalone "Project Init + Discovery" phase** — discovery is now a
  feature of Phase C intake's research mode, not a separate slice.
  `dontpanic init` may still ship as a thin convenience helper inside
  Phase C, but it is not a phase boundary.

## Sequencing Summary

```
Phase A [SHIPPED]  →  Phase B (lock next — agent manifest + thin MCP)
                                                       ↓
                      Phase C (lock after B — intake pipeline + discovery)
                                                       ↓
                      Phase D (lock after a Phase C type ships — ecosystem hooks)
                                                       ↓
                      Phase E — demand-driven (governance V2 trigger)
```

Each phase is lockable as its own plan with its own decisions. Don't
bundle. The discipline is the same the substrate followed: lock the
slice, ship it, learn from it, lock the next.

## What Each Stakeholder Gets

| Stakeholder | After Phase A [now] | After Phase B | After Phase C | After Phase D |
|---|---|---|---|---|
| Solo dev / friend | global install, multi-project registry, doctor preflight | their AI tools find DontPanic automatically | submit a brief / PRD / issue, get a plan | richer ecosystem callers |
| Founder / product builder | (not yet) | (not yet) | submit a PRD, get verified delivery | (richer; managed-agent surfaces) |
| AI coding agent (Claude Code, Codex CLI, Cursor) | install via pipx | discovers DontPanic via global manifest, calls MCP tools | submits work via `dontpanic.intake` | OpenClaw skill template, MCP client examples |
| OpenClaw user | (not yet) | (not yet) | (not yet) | OpenClaw skill calls `dontpanic intake / dispatch / status / approve` |
| Remote operator | (not yet) | (not yet) | (not yet) | dispatches via existing surfaces (Claude, ChatGPT, Clawdbot, OpenClaw) — DontPanic ships no custom remote daemon |

By Phase D, the positioning in [`PRODUCT.md`](./PRODUCT.md) and
[`ECOSYSTEM.md`](./ECOSYSTEM.md) — "OpenClaw helps agents do things
across your digital life; DontPanic helps agents ship software safely" —
becomes deliverable end-to-end without building custom remote
infrastructure.
