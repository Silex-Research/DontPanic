---
id: 2026-05-20-001-infra-external-integrations-bridge-v0
title: External integrations bridge v0 — dashboard ship + generic adapter framework + PM-tool category preset
type: infra
tier: cross-cutting
status: draft
date: "2026-05-20"
goal_type: infra
surfaces:
  - infra
  - dashboard
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
  - 2026-05-09-004-feat-firebase-dashboard-adapter-v0
  - 2026-05-10-001-feat-printing-press-adapter-skill
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
---

# External integrations bridge v0

## Motivation

Three threads converged into one plan:

1. **Dashboard (P9-004) needs to ship.** F003 + F004 + F005 are credential-gated (Firebase deploy + Tailscale Funnel) and have been carry-state since 2026-05-09. The dashboard is the primary visible product surface for operator-level DontPanic state — it should ship before broader integration work.

2. **Linear (or any PM tool) as backlog source-of-truth.** If Linear holds the operator's cross-platform plan/epic/feature inventory, then DontPanic's local `docs/plans/` directories drift instantly from Linear's view. The crossover with the dashboard is real: a DontPanic plan card should show its linked PM-tool issue status alongside DontPanic's own execution state.

3. **Adapter setup is a 4-step manual flow.** Today operators have to edit `~/.dontpanic/adapters.json`, run `/printing-press <service>`, author a wrapper, and commit a redacted example. No `dontpanic adapter add <service>` exists. If operators want to wire 5+ services (PM tool, incident tracker, observability, docs, ticketing) each one costs the same friction. Setup bloat is a real concern.

## Scoping principles (locked at draft)

- **Don't pre-build per-service code.** PM-tool category abstraction defines the abstract interface (issue model, status mapping, project model) — Linear/Aha/Jira/Monday/GitHub Projects each plug in via a small mapping config (~50 lines), not a service-specific wrapper.
- **Linear is the reference implementation**, not the only supported PM tool. The Linear adapter dogfood from P10 F003 becomes the canonical example; other PM tools land config-only.
- **Dashboard ships first.** F001 of this plan is the dashboard close-out (P9-004 F003-F005). Subsequent features assume the dashboard exists.
- **One-command adapter add.** `dontpanic adapter add <service> [--category=pm-tool]` is the single operator entry point. Operators never edit `~/.dontpanic/adapters.json` by hand.
- **No config bloat in `dontpanic init`.** Init stays for prereqs only. Adapters are opt-in extensions surfaced via `dontpanic adapter add`.

## Feature sketch (4 features, ordered)

- **F001 — Dashboard ship (closes P9-004 F003+F004+F005)**: Cloud Functions for kanbanMove/approve, Firestore security rules, end-to-end smoke runbook. Operator provisions Firebase project + Tailscale Funnel as out-of-band sub-task; LLM does the code.
- **F002 — PM-tool category abstraction**: abstract interface (Issue, Project, Status, Comment models), mapping config schema, Linear reference adapter wired to the abstraction. New PM tool = config-only addition.
- **F003 — Plan ↔ PM-tool sync layer**: `linked_issue_id` field on plan.md frontmatter; `plan lock` validates link; `plan close` writes status back via category adapter. One-way push (DontPanic → PM tool) only — pull (PM tool → plan dir scaffolding) deferred.
- **F004 — `dontpanic adapter add` CLI**: wraps PP invocation + wrapper authoring + adapters.json registration into one command. `--category=pm-tool` runs the category presets; `--raw` skips for non-category services.

## Non-goals (v0)

- No PM tool → plan dir scaffolding (Linear issue → `dontpanic plan new` from issue body) — that's v1.
- No multi-tool sync in same plan (one `linked_issue_id` per plan, one PM tool per category) — v1.
- No adapter capability marketplace / discovery / auto-update UI — v1.
- No mutating endpoints (write to Linear) beyond status flip — v1.
- No category abstraction for non-PM-tool categories (incident, observability, docs) — they ship as `--raw` adapters until a category abstraction is justified by ≥3 services in that category.

## Sequencing rationale

Dashboard first because it's blocking visible-progress work and credential-gated (operator does the unblocking). Category abstraction second because Linear is the dogfood we want to dogfood-validate. Sync third because it requires both the dashboard (to render linked status) and the abstraction (to write through). CLI fourth because it's the polish layer that turns the prior three into a one-command operator UX.

## Status

`draft` — pending operator review. Lock writes `pre_impl` sufficiency-findings.json + flips to `active`.
