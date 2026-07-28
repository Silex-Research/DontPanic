---
id: 2026-07-27-001-feat-buzz-integration-agent-taxonomy
title: Buzz integration + agent taxonomy honesty (operators vs workers)
type: feat
tier: cross-cutting
status: active
date: "2026-07-27"
goal_type: new_feature
description: >
  Make the worker-vs-operator agent model impossible to misread (README and
  shipped executor claims currently contradict AGENT_REGISTRY), support the
  low-cost multi-agent topology (OpenCode operator → DontPanic governance →
  Claude implement / Codex audit / Gemini goal-experience audit → human
  merge), integrate Buzz.xyz as the strongly recommended coordination surface
  (signup + private community setup), and evolve the agent registry into a
  Buzz-like split: harness adapters (stable code) + model catalog (high
  churn) + worker profiles (operator UX for harness+model+allowed_roles) so
  future models (Grok 4.5, OpenRouter, local Ollama) do not require new
  registry keys. Public communities are discovery/support; private communities
  are default work surfaces.
motivation: >
  A new user assembled a deliberate cost topology (OpenCode + Claude + Codex
  + Gemini) and discovered that Gemini/Grok are runtime-classified as
  operator-only while README still claims them as shipped executors. That
  mismatch blocks trust and blocks their intended goal/experience auditor
  role. Buzz makes harness+model selection trivial (agent card → harness
  dropdown → model dropdown); DontPanic collapses harness and model into one
  registry string. Separately, Buzz is a high-fit coordination surface —
  strongly recommended at setup. Maintainer has a Silex community; private
  operator communities remain the default for real work. Integration must
  follow ECOSYSTEM.md non-goals: no chat hub rewrite.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 4
  no_progress_threshold: 2
  wall_clock_hours: 12
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-01-002-feat-discord-notification-sink
  - 2026-05-03-003-feat-agent-access-manifest-thin-mcp
  - 2026-06-14-001-feat-agent-channel-interop-v0
links:
  features: ./features.json
  objective_contract: ./objective_contract.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Buzz integration + agent taxonomy honesty

## Problem / Motivation

### A. New-user diagnostic (blocking honesty)

A new operator documented this intended stack:

```text
You
  ↓
OpenCode — operator and planning interface
  ↓
DontPanic — orchestration, plan lock, governance
  ├── Claude  — implementation          (worker)
  ├── Codex   — implementation audit    (worker)
  └── Gemini  — goal / experience audit (intended worker)
  ↓
Human — approval, merge, deployment
```

They correctly discovered the load-bearing distinction:

| Class | Meaning | Source of truth today |
|---|---|---|
| **Worker / executor** | DontPanic can *dispatch* it (`implementer` / `auditor` / `goal_auditor`) | `executors.AGENT_REGISTRY` — **only `claude`, `codex`** |
| **Operator-only** | Can *run* DontPanic CLI/MCP; cannot be registered as a worker | `agent_surface.KNOWN_OPERATOR_AGENTS` — **`gemini`, `grok`** (+ any unregistered name) |

Runtime is consistent (`agent status`, `register-worker` refusal rc 3, doctor, tests). Marketing/checklist is not:

| Claim | Location | Reality |
|---|---|---|
| "Claude Code, Codex, Gemini, Grok, local models" as multi-vendor design | README intro | Design intent OK; dispatch support overstated |
| "Single-agent and volley dispatch (Claude, Codex, Gemini, Grok, Ollama executors)" **[x] shipped** | README setup checklist | **False** — no gemini/grok/ollama in `AGENT_REGISTRY`; no `gemini_cli.py` / `ollama` modules registered |
| Worker must be registered executor; operator-only cannot be implementer/auditor | README § onboarding | **True** — matches code |

Until docs match registry, new users will keep planning illegal topologies (e.g. `roles.goal_auditor=gemini`) and hit opaque refusals.

### B. Cost topology is product-valid

The OpenCode → DontPanic → Claude/Codex/Gemini → human gate pattern is exactly what DontPanic should enable for cost control:

- OpenCode (or Buzz, Cursor, Claude Desktop) = **operator surface**
- Claude = implementer (expensive, tool-use strong)
- Codex = cross-vendor implementation auditor
- Gemini = cheaper goal/experience auditor *if* (and only if) it becomes dispatchable *or* an explicit operator-driven audit path records its evidence

Today Gemini can operate DontPanic but **cannot** hold `goal_auditor` via `register-worker` / `roles set`.

### C. Buzz is a natural next operator/notify surface

[Buzz](https://buzz.xyz) / [block/buzz](https://github.com/block/buzz): Nostr relay workspace, agent keypairs, channels, YAML workflows, `buzz-cli` (JSON I/O), ACP harness (Goose/Codex/Claude Code), early git (NIP-34). Complements DontPanic the same way OpenClaw does: **room vs delivery contract**.

```text
Buzz / OpenCode  =  where humans + agents sit and approve
DontPanic        =  plan lock, volley, evidence, signoff
```

Non-goals (locked): DontPanic does not become a Buzz client, multi-tenant chat hub, or Nostr relay.

### Buzz setup posture — strongly recommended (not optional filler)

Buzz signup and setup are **strongly recommended** for every DontPanic operator
who runs multi-agent work. Framing in docs, setup checklist, and doctor:

| Level | Meaning |
|---|---|
| **Hard dependency** | No — DontPanic must still run without Buzz (local-first, offline-capable) |
| **Strongly recommended** | Yes — setup/README/doctor treat missing Buzz as an **advisory WARN** with a one-page fix path, not a silent skip |
| **Default path** | Create or join a **private community** for plan status, gates, and agent membership |

Best-use model is still evolving (D007). Until proven otherwise, document this
**community split**:

| Community type | Who creates it | Use for | Do not use for |
|---|---|---|---|
| **Private operator community** (default) | Each user/team | Notify sink, gate requests, builder≠auditor agents, plan status | Public links with secrets |
| **Silex community** (exists) | Maintainer / Silex-Research | Org coordination, internal multi-agent work if appropriate | Forcing every public user into it |
| **DontPanic public community** (optional later) | Product maintainers | Announcements, support, recipes, non-sensitive Q&A | Production gates, private plan evidence, API keys |
| **Self-hosted relay** | Operator | High-sensitivity / air-gapped / compliance | Required for day-one tryout |

**Product rule:** DontPanic never requires users to post into a maintainer-owned
community. `~/.dontpanic/buzz.json` always points at **their** community (URL +
channel + reporter key). Public communities are discovery/support only.

Recommended first-hour path (document in GETTING_STARTED / setup):

1. Install Buzz desktop (or self-host relay later).
2. Create a **private** community (or use an existing private one).
3. Create channels e.g. `#dontpanic-status`, `#dontpanic-gates` (names suggestive, not prescribed).
4. Create a reporter agent key (or use `buzz-cli` with `BUZZ_PRIVATE_KEY`) used only for DontPanic notifications.
5. Run `dontpanic setup` / doctor until Buzz shows **configured** (or explicit skip with WARN).
6. Optionally join public Silex/DontPanic communities for help — separate from the private work community.

## Proposed Approach

Four tracks. **Track A first** (honesty). Track D can start in parallel with B after A; **do not start Buzz code (C) until Track A lands**. Track D is the durable fix for “any model / OpenRouter / local / Grok 4.5” without stuffing model versions into `AGENT_REGISTRY`.

### Track A — Taxonomy honesty (P0, docs + single source of truth)

1. Fix README and any other "shipped executors include Gemini/Grok/Ollama" claims.
2. Publish one **Agent capability matrix** generated from runtime truth (`AGENT_REGISTRY` ∪ `KNOWN_OPERATOR_AGENTS` ∪ known operator surfaces including `opencode`).
3. Doctor / `agent status` already correct — add a doc-drift guard test that fails if README checklist lists non-registry executors as shipped.
4. Docs introduce the **three-layer vocabulary** early (harness / model / profile) so Track D is not a surprise rewrite of language.

### Track B — Cost topology enablement (P0/P1, product decision)

Pick **one** of two paths (D001); under Track D, B2 becomes “`gemini_cli` harness + worker profile with `allowed_roles: [goal_auditor]`” rather than a one-off registry special case:

| Path | What ships | Fits user stack? |
|---|---|---|
| **B1 — Honest operator-driven Gemini audit** | Document + CLI helper to attach a Gemini-produced goal/experience audit as *external evidence* without registering Gemini as worker | Yes, but Gemini is not dispatched |
| **B2 — Gemini harness + goal_auditor profile** | `gemini_cli` harness adapter; worker profile allowed for `goal_auditor` only until tool-use maturity proven | Yes, fully automated volley |

**Recommendation:** ship **B1 immediately** (unblocks truth), then **B2** as the first non-claude/codex harness under Track D when Gemini CLI smoke is proven. Do not treat Grok/Ollama **model names** as registry keys; they become harnesses only when sandboxed tool-use is real (D002 / D010).

Also document **OpenCode as first-class operator surface** (already in `operator_channels` / invocation runtimes; missing from README ECOSYSTEM caller table).

### Track C — Buzz integration (P1, strongly recommended setup + phased glue)

| Phase | Deliverable | DontPanic owns | Buzz owns |
|---|---|---|---|
| **C0** | Strongly recommended setup path + community model + ECOSYSTEM non-goals | docs, setup checklist, doctor WARN | — |
| **C1** | `notify_buzz` sink via `buzz-cli` + reporter key → **private** community default | NotifyEvent fan-out | channel posts |
| **C2** | Thin caller skill: validate → preview → explicit confirm → status poll | MCP/CLI | agent + workflow |
| **C3** | Gate mapping: allowlisted human reaction / workflow approval → `approve_gate` | gate actor + audit trail | UX + keys |
| **C4** | Dual agent identities in room (builder key ≠ auditor key) as *legible policy* | still dispatches via profiles | membership |
| **C5** | Capture learnings on “best uses of Buzz” after dogfood (Silex private work + optional public community) | `docs/solutions/` or plan evidence | product usage |
| **C6** | Optional: map Buzz agent id → local worker profile (harness+model+roles) | profile binding config | agent cards (Fizz/Honey/Bumble) |

System of record stays local plan dirs. Buzz posts **projections** (summaries, hashes, gate links), not secrets or full transcripts.

**Doctor / setup language (F009):** missing Buzz config → severity **warn** (not fail), remediation points at the private-community checklist. Explicit `DONTPANIC_SKIP_BUZZ=1` or doctor flag silences the WARN for headless CI only.

### Track D — Harness / model / worker-profile registry (P1, future-proof models)

Buzz UX shows the product gap: users pick **harness** and **model** independently; DontPanic today collapses both into `AGENT_REGISTRY` keys (`claude`, `codex`). Fix by **shrinking** the registry, not growing it with `grok-4.5`.

```text
1. HARNESS REGISTRY  (code, stable, few)     ← today's AGENT_REGISTRY, renamed in docs
   claude_cli | codex_cli | gemini_cli | openrouter | ollama | …
   = how to invoke (argv, auth, sandbox, parse)

2. MODEL CATALOG     (data + discovery)      ← high churn; never registry keys
   vendor ids | openrouter/… | ollama tags | aliases (grok-latest → grok-4.5)

3. WORKER PROFILES   (operator config)       ← Buzz-like agent cards
   display_name + harness + model + allowed_roles + capability overrides
   roles.implementer → profile id (legacy "claude" string still means default profile)
```

| Phase | Deliverable |
|---|---|
| **D0** | Spec + docs: harness ≠ model ≠ profile; capability gates roles (implementer requires file_edit+tool_use+non_interactive) |
| **D1** | `DispatchTask.model` (optional) + harness passes model flag; optional `roles.*.model` override without full profiles |
| **D2** | Worker profiles schema + `dontpanic workers` CLI + roles → profile id; evidence records harness+model+profile |
| **D3** | New harness adapters when proven: `openrouter`, `ollama` (goal/read-only first); `gemini_cli` for B2 |
| **D4** | Model discovery (`models list --harness …`), aliases, doctor probes; freeform model strings allowed with warn-if-unknown |
| **D5** | Buzz agent ↔ profile binding (pairs with C6) |

**Invariant:** dispatchability is earned by **harness capabilities**, not by marketing model name. New model versions (Grok 4.5, next Claude, OpenRouter OSS) never require a new Python registry key.

## Scope (in)

- README / ECOSYSTEM / USE_CASES honesty for worker vs operator
- Capability matrix + doc-drift test
- OpenCode operator-surface documentation
- Decision + implementation for Gemini goal-audit path (B1 and/or B2)
- **Strongly recommended Buzz signup + private community setup** in GETTING_STARTED, setup checklist, and doctor advisory
- Community model docs: private default vs public Silex / optional DontPanic support community
- Buzz notify sink + config (`~/.dontpanic/buzz.json`)
- Buzz-as-caller recipe (docs + optional example skill)
- Evidence redaction rules for channel posts
- Dogfood notes from maintainer Silex community (and any DontPanic public community if created)
- **Harness / model / worker-profile split** (Track D): model pass-through, profiles CLI, discovery, capability-gated roles
- OpenRouter + Ollama harness adapters when capability smoke is green
- Backward-compatible legacy `roles.implementer: "claude"` strings

## Scope (out)

- Building a Nostr client or relay inside DontPanic
- Replacing Jarvis dashboard / Firebase with Buzz
- Auto-merge from Buzz reactions without DontPanic gates
- Making Grok/Ollama **models** dispatchable without a real sandboxed **harness**
- Putting model version strings into `AGENT_REGISTRY` keys
- Multi-tenant RBAC / team billing (still single-operator product)
- Buzz-hosted secrets or full audit JSON on public relays
- **Forcing users into maintainer-owned communities** (Silex or DontPanic public)
- Hard-fail install if Buzz is absent
- Full GUI clone of Buzz agent cards (CLI + config first; dashboard later if needed)

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance (plan-level)

1. A new user reading README can answer "who can be dispatched today?" without contradiction: **claude + codex harnesses only** until more harnesses land; model lists are not conflated with harness lists.
2. The cost topology is either **executable** (B2 via gemini harness + profile) or **explicitly documented as operator-driven Gemini audit** (B1) with a working attach-evidence path — not a silent refusal.
3. First-run docs and setup checklist **strongly recommend** Buzz signup + **private community** setup; doctor emits an advisory WARN (not hard fail) when Buzz is unconfigured.
4. Docs state: private community = default work surface; public Silex/DontPanic communities = optional discovery/support only; never required for notify sink.
5. Buzz notify sink posts gate_paused / signoff / breaker events fail-soft when unconfigured (Discord pattern).
6. ECOSYSTEM.md states Buzz is a caller/notify surface, not a DontPanic subsystem.
7. Worker configuration supports **harness + model** without new registry keys per model version; evidence records harness, model, and profile id when profiles exist.
8. Schema-validated plan + features; codex audit on registry/docs honesty and profile features.

## Risks

| Risk | Mitigation |
|---|---|
| Gemini CLI not non-interactive enough for B2 | Prefer B1; gate B2 on smoke harness |
| Buzz workflow approval gates still immature | C1/C2 first; C3 on reactions/webhooks |
| Doc drift returns | README-vs-registry guard test |
| Leaking plan secrets into Buzz | Redact; post hashes + plan_id only; private community default; self-host for sensitive work |
| Scope creep into chat platform | Explicit non-goals; reuse NotifyEvent only |
| Users join public community and overshare | Explicit “private by default” copy; never default notify URL to a public community |
| Buzz best practices unknown | D007 open; dogfood on Silex; capture solutions doc (C5) |
| Track D scope explosion (every OpenRouter model) | Models are data; only harness adapters are code; freeform + discovery |
| Capability under-declared → unsafe implementer | Role gates on capability flags; doctor refuses weak harness for implementer |
| Breaking existing roles strings | Legacy `"claude"` / `"codex"` remain valid profile aliases |

## Open questions

See `decisions.jsonl` — especially **D001** (Gemini path), **D007** (Buzz community / best-use model), and **D010** (harness/model/profile split — resolved direction, phased delivery).
