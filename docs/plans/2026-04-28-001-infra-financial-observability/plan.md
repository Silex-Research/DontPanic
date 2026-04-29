---
id: 2026-04-28-001-infra-financial-observability
title: Financial observability — cost-model, cost-guard, revenue-check
type: infra
tier: cross-cutting
status: draft
date: "2026-04-28"
description: |
  Three sibling skills under Jarvis/claude/skills/ that turn the existing cost surface (LLM tokens via quota_check.py, GCP $ via refresh-costs.sh) plus a new revenue.json surface into a unified financial-observability layer for app-level (not orchestration-agent-level) decisions. cost-model projects spend, cost-guard enforces app-level budgets, revenue-check pulls product revenue and reports cash-flow position per app.
motivation: |
  Phase 1 (#691) made cross-agent visibility coherent — refresh-costs.sh moved under scripts/maintainer/ and the sync-harness was updated. The cost surface is observable but inert. quota_state.json gates orchestration dispatches via F006 budget_ceiling, and costs.json renders on the cloud-costs dashboard, but neither answers "is Glam profitable today" or "is SpinDine on track for its monthly burn target." This plan layers three on-demand skills that close that loop without modifying the inviolable inputs.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
quota_caps:
  claude: 2
  codex: 1
loop_caps:
  max_iterations: 1
  no_progress_threshold: 2
  wall_clock_hours: 8
  hard_stop: false
privacy_tier: internal
protected_paths:
  - scripts/quota_check.py
  - scripts/maintainer/refresh-costs.sh
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
dependencies:
  - 2026-04-19-001-infra-cross-agent-orchestration
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Financial observability — cost-model, cost-guard, revenue-check

## Thesis

Three skills, no new infra. Each reads existing JSON state, none mutates it. cost-model is the projection layer; cost-guard is the alarm layer; revenue-check is the income side. Together they let an operator (or a future orchestrator) ask three first-class questions about each app: *what will it cost?*, *did we breach budget?*, *is it cash-flow positive?*

This plan is **app-level financial observability**, not orchestration-agent observability. F006 budget_ceiling already guards autonomous dispatch quotas — that is a different lane and stays untouched.

## Existing cost surface (recon, 2026-04-28)

| Source | Writer | Output | Frequency |
|---|---|---|---|
| LLM tokens (Claude/Codex/Gemini/Grok/Ollama) | `scripts/quota_check.py` (F020) | `~/.jarvis/quota_state.json` | On-demand + supervisor pre-dispatch |
| GCP $ per app | `scripts/maintainer/refresh-costs.sh` (#691 moved) | `dashboard/state/costs.json` | Manual / cron |
| Stock-market financials | `dashboard/pages/financial/financial.js` | client-side Yahoo Finance | Per-page-load (NOT product revenue) |

`token-budget-tracker` SKILL.md exists but is a Feb-2026 prose stub with stale prices and no runtime — it predates F020. Out of scope to delete this turn (separate cleanup); cost-model takes its functional slot.

## What's missing

1. **No projection.** quota_state.json reports week-to-date; costs.json reports month-to-date. Neither answers "what will the rest of the month cost at current trajectory?"
2. **No app-level guard.** F006 budget_ceiling reads quota_state.json for **agent quotas in autonomous dispatches**. There is no equivalent for "Glam GCP burn is 3× plan this week" or "SpinDine LLM bill is up 5× since last Monday."
3. **No revenue side.** Glam Commerce + Creator Hub (Phase J0-J7) emit subscription/affiliate events to Firestore, but Jarvis has no way to pull that aggregate and compare against cost. revenue.json doesn't exist.

## Three skills

### F001 — cost-model
Read costs.json + quota_state.json + (optional) revenue.json. Project current month-end and next-month spend per app and per LLM provider. Output a structured report (markdown + JSON) into `evidence/<run-id>/`. No mutations.

### F002 — cost-guard
Read costs.json + quota_state.json + per-app budget config (`config/cost_budgets.json`, new). Compare observed run-rate to budget. Emit findings to `INBOX.md` (existing F008 surface) when an app breaches `warn_threshold` (default 80%) or `breach_threshold` (default 100%). On-demand and idempotent — re-runs do not duplicate INBOX entries within the same calendar week.

### F003 — revenue-check
Read app-specific revenue sources (Glam Firestore `creatorEngagementEvents` + commerce subscription docs; SpinDine — TBD by recon during impl, see D001 below). Aggregate to monthly revenue per app, write `dashboard/state/revenue.json` (NEW file — outside the protected list), and produce a cash-flow report alongside cost-model output.

## Public-boundary anchors

This plan ships skills that other agents and humans will run from a fresh clone. Per the F022 review-cycles lesson, every "passes:true" claim must be reproducible after `git clone Jarvis && bash scripts/bootstrap.sh` with no operator-side state. Concretely:

- All three SKILL.md files validate against `claude/shared/skill-standard/CONFORMANCE.md`.
- Each skill ships a `tests/` directory whose tests pass with **no credentials** (fixtures only).
- `scripts/sanitization_check.py` stays green (no secrets/PII bleed in skill bodies, configs, or tests).
- `scripts/jarvis_doctor.py` stays green (no new required env vars without a doctor check).
- `claude/RESOLVER.md` gets three new rows; the resolver validator (`claude/shared/resolver/validate.py`) stays green.
- Expect 2–3 review rounds anchored to a fresh-clone fixture, not to my workstation state.

## Out of scope

- Deleting / rewriting `token-budget-tracker` (separate task; cost-model can co-exist for one cycle).
- Modifying `quota_check.py`, `refresh-costs.sh`, or any of the three known-dirty files (`claude/PORTABILITY.md`, `claude/scripts/sync-harness.sh`, `dashboard/state/costs.json`).
- New BigQuery queries (refresh-costs.sh stays as the sole BQ caller; revenue-check pulls from Firestore only).
- Real-time alerting (cost-guard writes INBOX entries; ops watches INBOX — no new notification channel).
- Per-user / per-tenant cost attribution inside Glam (the surface is per-app, not per-tenant).
- Replacing or duplicating F006 budget_ceiling for orchestration-agent quotas.

## Risks

- **Revenue source ambiguity for SpinDine.** Glam has Phase J commerce; SpinDine's revenue model is unverified by me. D001 below — recon during F003 impl, may downscope to "Glam-only revenue.json with SpinDine TODO marker."
- **Budget config bootstrap.** `config/cost_budgets.json` requires operator-supplied numbers. We ship a template with sentinel zeros; cost-guard short-circuits with a clear "no budgets configured" finding rather than alerting on `budget=0`.
- **Stale state.** quota_state.json staleness is not monitored. cost-guard treats data >24h old as "stale" and emits a `data_stale` INBOX entry instead of a false-positive breach.

## Acceptance (this plan)

`signoff: true` only when:

- F001/F002/F003 each `passes: true` with fresh-clone-anchored evidence.
- `scripts/sanitization_check.py` exits 0 against the staged tree.
- `scripts/jarvis_doctor.py` exits 0 with the new files present.
- `claude/shared/resolver/validate.py` exits 0 (skill-conformance + resolver registration).
- The three known-dirty files are unmodified (verified by `git status` showing only those three pre-existing entries).
- D001 resolved.

## Open decisions

See `decisions.jsonl`.

- **D001:** SpinDine revenue source. Likely Stripe events mirrored to Firestore; needs confirmation during F003 recon. Default fallback: ship Glam-only with a documented stub.

## Target

```yaml
target_env: dev
target_project: <firebase-project-id>
```

## Provenance

Picked up 2026-04-28 from the Phase 2 task slot (#692) under the cross-agent visibility plan whose Phase 1 (#691, repo rename + sync-harness update) just landed. Recon sources: `Jarvis/scripts/quota_check.py`, `Jarvis/scripts/maintainer/refresh-costs.sh`, `Jarvis/dashboard/state/costs.json`, `Jarvis/dashboard/pages/financial/financial.js`, `Jarvis/claude/skills/token-budget-tracker/SKILL.md`, parent plan `2026-04-19-001-infra-cross-agent-orchestration` features F006/F008/F020.
