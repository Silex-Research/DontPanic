---
id: 2026-05-20-001-infra-external-integrations-bridge-v0
title: External integrations bridge v0 — PM-tool category contract + plan sync
description: |
  DontPanic owns a PM-tool category contract; each external service supplies
  a PP-generated adapter plus a small semantic mapping config. Plans can
  declare external_refs that sync DontPanic state out to the linked PM-tool
  issue on close-out. Dashboard renders linked-issue status alongside
  DontPanic plan state once both the dashboard adapter (Plan 004) and this
  bridge land. v0 deliberately narrow: no `dontpanic adapter add` CLI
  (deferred), no PM tool → plan dir scaffolding (pull deferred), one-way
  push only with durable evidence for every external write.
type: infra
tier: cross-cutting
status: draft
date: "2026-05-20"
goal_type: infra
surfaces:
  - infra
  - external-api-wrap
  - web
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  no_progress_threshold: 2
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-10-001-feat-printing-press-adapter-skill
  - 2026-05-09-004-feat-firebase-dashboard-adapter-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
---

# External integrations bridge v0

## Motivation

Two threads converged into this plan during the P10 F003 Linear-pick conversation:

1. **PM-tool-as-backlog crossover.** If Linear (or any of Aha / Jira / Monday / GitHub Projects) holds the operator's cross-platform plan/epic/feature inventory, then DontPanic plan status drifts from PM-tool issue status the moment a DontPanic plan closes. The two views diverge silently. The crossover with the dashboard is real: a DontPanic plan card should be able to show its linked PM-tool issue status alongside DontPanic's own execution state.

2. **Adapter setup config bloat risk.** If operators want to wire 5+ services (PM tool + incident tracker + observability + docs + ticketing), each one should not require a separate Python wrapper. The Printing Press adapter pattern (P10 F001/F002) already generates per-service MCP binaries; what's missing is the **category-level contract** that lets multiple PM tools share one mental model.

This plan ships the bridge surface. It does NOT pull the dashboard adapter (P9-004 F003-F005) into its own ownership — that work stays in P9-004. The bridge plan depends on P9-004 completion for F003 (dashboard linked-status chip), but does not close P9-004's features.

## Scoping principles (locked at draft)

- **Category contract, not per-service code.** DontPanic owns the PM-tool category contract (abstract Issue/Project/Status/Comment models + sync hooks). Each service supplies a PP-generated MCP adapter plus a small semantic mapping config that translates the service's concepts to the abstract model. No DontPanic core code is added per service unless the category contract itself expands.
- **Linear is reference, not lock-in.** The Linear adapter from P10 F003 becomes the canonical example wired to the category contract. Adding Aha/Jira/Monday/GitHub Projects requires (a) PP-generated MCP binary for that service AND (b) a service mapping config — no Python in DontPanic core.
- **External writes are auditable.** Every plan close that pushes status to a PM tool produces a durable `external_sync` evidence record (`pending|failed|skipped|pushed`). No silent "warning only" failures — unreachable target writes a `failed` evidence record, not just a log line.
- **Sequence the dashboard first, externally.** F003 of this plan depends on P9-004 being completed. Plan 004 close-out is operator-driven (its F003-F005 are credential-gated and live in axiom/, not DontPanic). This plan does NOT do that close-out work.
- **Defer the CLI.** `dontpanic adapter add <service>` is intentionally not in this plan. Prove one manually-configured Linear adapter works against the category contract + sync layer first. CLI ships in a follow-on plan after one real adapter validates the shape.

## Feature sketch (3 features, ordered)

- **F001 — PM-tool category contract + Linear reference mapping**: define abstract Issue/Project/Status/Comment models, mapping config schema, hook points for sync (status push). Wire the Linear adapter from P10 F003 as the reference implementation. Document the extension contract for additional PM tools.
- **F002 — Plan external_refs + one-way sync layer**: introduce `external_refs[]` array on plan.md frontmatter (`kind`, `uri`, `sync`). `dontpanic plan lock` validates each ref via the category adapter. `dontpanic plan close` pushes status flip to opt-in refs (`sync: push_status`). Every push produces a durable `external_sync` evidence record. Failures are surfaced loud, not silent.
- **F003 — Dashboard linked-status chip**: dashboard renders the linked PM-tool issue status on plan cards. Depends on P9-004 completion (out-of-band, this plan does not close P9-004's features) AND F001 + F002.

## Non-goals (v0)

- No `dontpanic adapter add` CLI — deferred to a follow-on plan after one real adapter validates the shape.
- No PM tool → plan dir scaffolding (Linear issue → `dontpanic plan new` from issue body) — pull deferred.
- No multi-tool sync within a single plan beyond what `external_refs[]` array already supports — multiple refs allowed by schema but in v0 only the first `sync: push_status` ref is honored on close-out. Multi-target push fan-out deferred.
- No mutating PM-tool endpoints beyond status flip — comment posting, label changes, etc. deferred.
- No category abstractions for non-PM-tool service categories (incident, observability, docs) — they ship as `--raw` adapters until a category abstraction is justified by ≥3 services in that category.
- No dashboard ownership — F003 of this plan adds the linked-status chip to a dashboard whose underlying delivery is Plan 004's job.

## Sequencing rationale

F001 first because the category contract is foundational — F002 + F003 both consume it. F002 next because the sync layer is the actual user-facing capability (linked plans actually push status). F003 last because it depends on both F001+F002 AND on P9-004 being completed (external dependency). If P9-004 stays carry-state, F001+F002 still ship and F003 waits.

Sequencing rationale also intentionally excludes the dashboard close-out from this plan. Dashboard work belongs in Plan 004. This plan's job is the *bridge*.

## External mutation safety

Per operator review: every external write (PM-tool status push on plan close) MUST produce a durable evidence record. Requirements:

- **Adapter opt-in**: `external_refs[N].sync` is explicit (`none|push_status`); default is `none`. Adapter must declare it supports writes before any push happens.
- **Dry-run preview**: `dontpanic plan close --dry-run` shows the intended external write payload without executing.
- **Durable evidence**: every push attempt writes `evidence/external_sync.json` with `{ref_uri, kind, attempted_at, status: pending|pushed|failed|skipped, response, error}`.
- **No silent failures**: PM-tool unreachable does NOT block plan close, but it MUST produce an evidence record with `status: failed`. Operator can rerun the push later via `dontpanic plan resync`.

## Status

`draft` — pending operator review. Lock writes `pre_impl` sufficiency-findings.json + flips to `active`.
