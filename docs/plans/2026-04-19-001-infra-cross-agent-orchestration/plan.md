---
id: 2026-04-19-001-infra-cross-agent-orchestration
title: Cross-Agent Autonomous Orchestration System
type: infra
tier: architectural
status: draft
date: "2026-04-19"
description: Multi-agent (Claude / Codex / Gemini / Grok / OSS) autonomous orchestration system with machine-checkable ground truth, tier-based cost control, parallel-and-reconcile audit, and pause-not-stop loop prevention.
motivation: Today, Claude implements a plan, I hand-audit or invoke Codex manually, and context evaporates between sessions. This plan builds an executable contract — plans as directories with features.json as inviolable ground truth — so implementation, audit, and signoff become autonomous across Claude CLI, Codex CLI, Gemini CLI, Grok API, and Ollama OSS, with human attention reserved for tier-appropriate gates only.
agents_required:
  - claude
  - codex
  - gemini
  - grok
  - oss-qwen
  - oss-gemma4
  - oss-nemotron
  - oss-llama-guard
  - oss-nomic-embed
human_gates:
  - pre_impl
  - pre_merge
  - on_escalation
  - tier_promotion
  - cost_trigger
quota_caps:
  claude: 5
  codex: 5
  gemini: 5
  grok_calls: 5
loop_caps:
  max_iterations: 1
  no_progress_threshold: 2
  wall_clock_hours: 72
  hard_stop: false
privacy_tier: internal
protected_paths:
  - agent-conventions/schemas/**
  - Jarvis/scripts/jarvis_orchestrate/**
  - Jarvis/.secrets/**
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
storage:
  backend: firebase-storage
  bucket: jarvis-main.appspot.com
  prefix: plans/2026-04-19-001/
---

# Cross-Agent Autonomous Orchestration System

## Thesis

The plan is an executable contract. Any agent (Claude, Codex, Gemini, Grok, OSS) can read it, verify it, or sign off against it. The supervisor is a thin dispatcher; all coordination state lives in versioned artifacts in the repo. No terminal scraping, no agent-to-agent chat — just schema-validated JSON handoffs.

## Core principles

1. **Bootstrapping.** Each phase's deliverable becomes the verification harness for the next. The system tests itself on itself. If Phase N's tooling can't verify Phase N+1, the tooling is the bug.
2. **Machine-checkable ground truth.** `features.json` is inviolable — agents only flip `passes: false → true` with `evidence_refs`.
3. **Adversarial independence.** Different model families (Anthropic, OpenAI, Google, xAI, Meta/Alibaba/Nvidia) prevent single-vendor self-approval.
4. **Feedback loops start immediately.** The verification panel runs manually via CLIs until the supervisor exists in Phase 2. Discipline precedes automation.
5. **Progressive disclosure.** Short entry points (CLAUDE.md <120 lines; AGENTS.md as map) point to deeper `docs/architecture/` — context window is a scarce resource.
6. **Pause-not-stop.** Limits interrupt for human approval rather than terminate, except the global circuit breaker (see Loop Prevention).

## Agent panel

| Agent | Primary role | Invocation |
|---|---|---|
| Claude Opus 4.7 (1M) | Design, planning, implementation | `claude -p` CLI |
| Codex (GPT-5) | Plan validation, correctness audit, security veto | `codex exec --json` CLI |
| Gemini 2.5 Pro (2M) | SRE/backend review, multimodal UI verification, evidence generation | `gemini -p` CLI + google-genai SDK for multimodal |
| Grok 4 | Unbiased third opinion, currency check (is this still the right pattern in Q2 2026?) | xAI API via Python httpx |
| Qwen3.5-Coder-32B | Code reasoning, deterministic verification | Ollama local |
| Llama-Guard-3 | Safety/redaction, secret/PII gate before egress | Ollama local |
| Nomic-embed-text | Embeddings for memory/RAG/doc-freshness | Ollama local |
| Gemma4 | Cheap multimodal pre-check | Ollama local |
| Nemotron | Heavy reasoning fallback | Ollama local |

Signoff math is tier-dependent (see Tier System). Reconciliation is parallel-and-deterministic: agents audit independently, supervisor aggregates findings by (file, severity, category), detects agreements/disagreements, applies signoff math, persists `audit/disagreement.jsonl` for conflicts, escalates unresolvable cases via `INBOX.md`.

## Artifact contract

Every plan is a directory:

```
docs/plans/YYYY-MM-DD-NNN-<type>-<name>/
  plan.md                  # human narrative (this file), frontmatter validated by plan.schema.json
  features.json            # machine-checkable ground truth, validated by features.schema.json
  decisions.jsonl          # append-only decision log
  schemas/ (inception only; promoted to agent-conventions/schemas/v1.0/ after Phase 0)
  audit/                   # per-agent audit JSONs + disagreement.jsonl + signoff.json
  evidence/                # small artifacts in-repo; large artifacts in Firebase Storage via signed URLs
```

Evidence > 100KB lives in Firebase Storage (`jarvis-main` project, `evidence/plans/<id>/` prefix). URIs embedded in `features.json` as `evidence_refs`.

## Tier system

Tier drives everything — agent panel size, loop caps, quota budgets, human gates. Declared in plan frontmatter; defaults cascade.

| Tier | Agent panel | Loop cap | Per-model weekly quota | Human gates |
|---|---|---|---|---|
| trivial | OSS-only | 0 (single-shot) | ≤ 0.1% | None — auto-merge if CI+OSS green |
| local | Claude + Codex (2-of-2) | 1 | ≤ 0.5% | PR review only |
| cross-cutting | Claude + Codex + Gemini (2-of-3) | 2 | ≤ 2% | pre_impl + pre_merge |
| architectural | Full 4 + Codex security veto + Grok currency mandatory | 1 (escalates fast) | ≤ 5% | pre_impl + pre_merge + audit_review |
| p0 | Full panel, synchronous | Uncapped, pages each iter | Uncapped + alert at 10% | Synchronous — supervisor pings immediately |

Auto-promotion: `local → cross-cutting` if touches `packages/shared`, >200 LOC, >5 files, modifies `*.schema.json`, Firestore rules, or `wrangler.jsonc`. `cross-cutting → architectural` if new ADR, public API change, security boundary, or schema breaking change.

## Phases

Concrete deliverables live in `features.json` (F001-F021). Phase-to-feature mapping:

| Phase | Theme | Key features |
|---|---|---|
| 0 | Schemas + Firebase project | F001, F002 |
| 1 | plan-artifacts skill update + dogfood | F003, F021 |
| 2 | Supervisor + quota + INBOX | F004, F005, F006, F007, F008, F020 |
| 3 | Application legibility MCPs + init.sh | F009, F010, F011, F012 |
| 4 | Architecture docs per project | F013 |
| 5 | axiom-lints mechanical invariants | F014 |
| 6 | Hooks (Stop, SessionStart) | F015, F016 |
| 7 | Agent teams wiring | F017 |
| 8 | Scheduled hygiene | F018 |
| 9 | wterm live dashboard | F019 |

Each phase's verification panel:
- **Phase 0 uses manual CLI invocation** (supervisor doesn't exist yet); Claude drafts, human runs Codex/Gemini/Grok, pastes findings, Claude iterates.
- **Phase 1+ uses the Phase 2 supervisor once it exists** — dogfooding the system on itself.

## Loop prevention (7 termination triggers)

Stacked defense; first to trip wins:

1. Hard iteration cap (per tier)
2. Budget ceiling (% weekly quota per plan)
3. Wall-clock timeout (per tier)
4. No-progress detection (features.json `passes` count unchanged across 2 iters)
5. Diminishing-returns detection (findings list near-identical across 2 iters via embedding distance)
6. Convergence collapse (signoff vote split worsening)
7. Global circuit breaker (3 consecutive cap-hits in 24h across plans)

**All six trigger a pause-for-approval via INBOX.md with diagnostic context** (why hit, what's the diminishing-returns signal, proposed continuation). Human responds by editing INBOX.md; supervisor resumes with counters reset.

**Exception: global circuit breaker is hard-stop.** 3 consecutive cap-hits across plans signals a systemic issue (model regression, schema drift, infra problem) that warrants investigation, not rubber-stamping.

## Human decision points (5 canonical gates)

Only places automation pauses; everything between is autonomous.

1. **pre_impl** — `cross-cutting+`: approve plan + features.json before code is written (brainstorm-gate)
2. **pre_merge** — `cross-cutting+`: review supervisor signoff summary before merge
3. **tier_promotion** — automatic prompt when scope grows mid-execution
4. **on_escalation** — automatic on any loop-prevention trigger or reconciliation failure
5. **cost_trigger** — at 80% weekly quota per model: block until approval

For `trivial`/`local`, you see nothing in real-time. Daily digest in `Jarvis/docs/digests/YYYY-MM-DD.md` surfaces everything that ran autonomously, shown at next SessionStart.

## Quota policy

Per-model % weekly tracking (no dollar tracking — Max plans). Reservation splits:

- 20% interactive (autonomous cannot touch — protects your work)
- 10% P0 reserve
- 50% autonomous budget (cumulative cap across running plans)
- 20% headroom

Quota-aware scheduling:
- Defer Claude-heavy plans if Claude weekly > 70%
- Interactive backoff: don't launch Claude-heavy autonomous work within 30 min of human's last Claude request
- Reset-aware queuing: plans that would breach quota auto-queue for next reset window

Ollama OSS is unmetered — preferred for pre-checks, redaction, embeddings, anything `trivial`.

See Task #698 for model consumption tracking implementation.

## Privacy tiers

- **public**: all agents can see; no redaction required
- **internal**: frontier APIs OK; no customer PII or production secrets
- **secret**: OSS-only (Ollama local); Llama-Guard-3 must run redactor gate before any inter-agent handoff

OSS redactor (Llama-Guard-3) runs as Phase 0 pre-gate for any plan flagged `internal` or `secret`. Nothing leaves the local machine without passing.

## Bootstrapping dependency chain

```
Phase 0 (schemas + Firebase) —bootstraps→ Phase 1 (skill update)
Phase 1 (directory plans)    —bootstraps→ Phase 2 (supervisor test corpus)
Phase 2 (supervisor)         —bootstraps→ Phase 3 (MCP integration tests)
Phase 3 (MCPs)               —bootstraps→ Phase 4 (architecture docs verified against runtime)
Phase 4 (architecture)       —bootstraps→ Phase 5 (lints enforce docs as spec)
Phase 5 (lints)              —bootstraps→ Phase 6 (hooks fire lints)
Phase 6 (hooks)              —bootstraps→ Phase 7 (teams dispatch via hooks)
Phase 7 (teams)              —bootstraps→ Phase 8 (hygiene via teams)
Phase 8 (hygiene)            —bootstraps→ Phase 0 v2 (compounding improvement)
Phase 9 (wterm dashboard)    —independent viewer, added after v1 contract solid
```

## Risks

- **Schema gap.** If v1.0 schemas can't express a real plan's needs, Phase 1 dogfood fails and we iterate. Mitigation: inception plan is itself complex enough to stress-test; if it validates, simpler plans will.
- **Model quota exhaustion.** Aggressive autonomous orchestration could burn weekly quota mid-week. Mitigation: 20% interactive reservation + per-tier quota caps + defer thresholds.
- **Supervisor bugs causing stuck plans.** Global circuit breaker hard-stops after 3 cap-hits. Weekly cost-of-failure bounded.
- **Agent CLI regressions.** Claude/Codex/Gemini CLIs may change output formats. Mitigation: pluggable executors; version-pinned parsing; integration test per executor.
- **Codex/Gemini disagreement on non-obvious issues.** Reconciliation persists disagreements rather than voting them away; patterns visible over time via `audit/disagreement.jsonl` aggregation.
- **Firebase Storage cost if evidence grows.** Expected <1GB/year; reassess if we approach 10GB.

## Non-goals

- Replacing `brainstorm-gate` for design decisions — that stays human-driven for cross-cutting+.
- Automated merge for anything above `trivial` without human approval.
- Direct agent-to-agent conversation (artifacts only).
- Eliminating Grok subscription/API cost (accepted as separate line item).
- Real-time streaming telemetry in v1 (Phase 9 wterm dashboard adds this later).

## Open decisions

See `decisions.jsonl` for the full log. Currently one open item:

- **D015: Weekly quota reset boundary (Claude Max)** — owner action via Task #698. Cron + digest cadence sync once known.

## Acceptance (this plan)

This plan is `signoff: true` when:
- All 21 features in `features.json` have `passes: true` with evidence
- The supervisor can run this very plan through itself and produce `signoff.json` with `signoff: true`
- D015 resolved
- `audit/disagreement.jsonl` either empty or all entries have `resolution` set
- Phase 0 dogfood (F021) validates this plan's artifacts against promoted schemas with zero errors

## Provenance

This plan emerged from a multi-turn design conversation on 2026-04-18 / 2026-04-19 covering:
- Cross-CLI orchestration (Claude ↔ Codex handoff contracts)
- Critical assessment of the "harness is everything" blog (OpenAI Codex, SWE-agent, Awesome Agent Harness taxonomy)
- Per-phase verification panels with bootstrapping
- Plan tier system, loop prevention, human gates, % quota budgeting
- Role specialization per model (Claude design, Codex audit, Gemini SRE+multimodal, Grok currency, OSS sovereignty)
- wterm as Phase 9 viewer layer

The design chose hand-written JSON-first inception (this document + siblings) over using the existing Markdown-only `plan-artifacts` skill, to avoid inheriting stale patterns into the new system. The skill update (F003) follows the proven format.

## Target

```yaml
target_env: dev
target_project: <firebase-project-id>
```
