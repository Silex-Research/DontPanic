---
id: 2026-06-04-004-feat-dashboard-state-fidelity
title: Dashboard state fidelity (render truth — provenance, lifecycle vs activity, freshness, attribution)
type: feat
tier: cross-cutting
status: draft
date: "2026-06-04"
goal_type: new_feature
description: >
  Guarantee that what the dashboard SAYS about itself is true: every section names
  the real source it renders from; plan lifecycle and live agent activity are
  separate axes (no label implies live execution unless sourced from supervisor
  state); every page shows its data age and has a refresh trigger; when supervisors
  are live the board shows which agent is working which plan/kind, and says "none"
  when none are. Sibling to 2026-06-04-001: 001 is ACTION truth ("if the dashboard
  says do this, will doing it resolve the condition?"), 004 is STATE/RENDER truth
  ("if the dashboard says this is running/active/live/stale, is that actually
  true?"). Different invariants, tested differently.
motivation: >
  The Work board updates from the canonical projection (state-snapshot.json) but is
  semantically misleading: "Running 2" means "plans with status=active," not two
  live agents (dontpanic ps reports none); the Work footer still cites legacy
  tasks.json/agents.json/activity.json though the board is adapted from
  state-snapshot.json; there is no per-page data-age/refresh trigger; and there is
  no agent attribution when multiple supervisors run. The board is trustworthy as a
  plan-ledger view but not yet as "what is actually happening right now."
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
privacy_tier: internal
dependencies:
  - 2026-06-04-001-feat-ledger-reconciliation-operator-actions

links:
  features: ./features.json
  decisions: ./decisions.jsonl
---

# Dashboard state fidelity

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal dashboard/state-projection plan. No external service setup required.

## Problem / Motivation

The dashboard renders real generated state but describes it dishonestly in ways that
make "what is happening right now" untrustworthy:

- **Provenance is wrong.** The Work footer cites `tasks.json` / `agents.json` /
  `activity.json` (stale legacy/demo inputs) while the board is actually adapted
  from `state-snapshot.json`.
- **Lifecycle is conflated with activity.** "Running 2" = plans with `status:active`,
  not live agents; `dontpanic ps` reports no active supervisors and the sidebar
  correctly says 0 agents — so the same screen contradicts itself.
- **No freshness contract.** Pages don't consistently show `generated_at` / data age
  or a clear refresh trigger, so a stale view is indistinguishable from a fresh one.
- **No agent attribution.** With multiple supervisors deployed there is no view of
  which agent is working which plan / feature / kind of work.

## Proposed Approach

Make render truth a contract: each section declares its real source + freshness;
plan-lifecycle and agent-activity are distinct axes sourced from distinct files;
agent attribution comes from the supervisor registry; and an invariant test proves
every rendered count/label equals the source it claims.

## Scope (in)

- F001 Real provenance: every section declares its actual source; legacy files
  cannot be cited (or override) when the canonical projection is active.
- F002 Lifecycle vs activity: Active Plans (status==active) and Live Now (active
  supervisors) are separate, distinctly sourced; no label implies live execution
  unless sourced from supervisor state.
- F003 Freshness + refresh: each major page shows generated_at / data age and offers
  a refresh action or command.
- F004 Agent attribution: when supervisors are live, show which agent works which
  plan/feature/kind; when none are live, say none.
- F005 Truthfulness invariant tests: rendered labels/counts match their claimed
  source.

## Scope (out)

- ActionItem resolvability / phantom suppression — that is `2026-06-04-001`.
- Building NEW integrations or operator actions — that is `2026-06-04-003`.
- Realtime/multi-operator dashboard transport (Firebase) — demand-gated elsewhere.
- Changing the supervisor registry itself (consume it; don't redesign it).

## Acceptance

Every dashboard section names the real source it renders from and shows nothing from
legacy `tasks.json`/`agents.json`/`activity.json` when the canonical projection is
active; "Active Plans" counts `status==active` and a separate "Live Now" counts
active supervisors from `dontpanic ps`/supervisors.json (no label implies live
execution otherwise); each major page shows `generated_at`/data-age and a refresh
trigger; agent attribution shows which agent works which plan/kind when supervisors
are live and "none" when not; and invariant tests assert each rendered count/label
equals the source it claims (Live Now == supervisors.length, Active Plans == plans
where status==active, Work provenance == the active projection source, and stale
legacy files cannot override the canonical projection). Full orchestrate sweep stays
green.
