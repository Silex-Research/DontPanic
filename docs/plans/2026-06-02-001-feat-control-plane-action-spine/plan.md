---
id: 2026-06-02-001-feat-control-plane-action-spine
title: Control-plane action spine — one ActionItem contract, honest agent roles, renderer parity
type: feat
tier: cross-cutting
status: active
date: "2026-06-02"
goal_type: new_feature
description: >
  Establish the shared control-plane spine: make ActionItem the single canonical
  action contract that ActionChoice and RenderedEvent project into, add the
  human-facing control-plane fields (audience, dedupe_key, reversible,
  plain_consequence, dashboard_url), classify harnesses honestly as
  operator/worker/orchestrator, and prove dashboard, CLI/JSON, and agent-brief
  all render the same action. Rebases on 2026-05-30-001; deliberately excludes
  orchestration-tree governance (Plan B) and the plan-quality recast.
motivation: >
  Verification against HEAD c814cc9 confirmed ActionItem (operator_console.py:174),
  RenderedEvent (event_copy.py:78), and ActionChoice (operations_guidance.py:154)
  already triangulate into one contract via tested projections
  (Guidance.to_action_items, _rendered_to_action_item_dict, merge_with_event_sidecar).
  This plan formalizes that convergence and adds the control-plane fields a
  non-technical human and an interactive agent both need — WITHOUT building the
  speculative orchestration-tree machinery, which is demand-gated to Plan B.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-30-001-feat-universal-agent-repo-onboarding-v0
links:
  features: ./features.json
  objective_contract: ./objective_contract.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Control-plane action spine

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal orchestration-engine plan. No external service setup is required.

## Problem / Motivation

DontPanic surfaces operational actions across three audiences — humans (dashboard),
interactive agents (CLI/JSON/MCP), and onboarding agents (agent-brief / AGENTS.md) —
but the action data is produced by three types that grew independently:

- `ActionItem` (`operator_console.py:174`) — the durable, provider-emitted,
  dashboard/agent-facing contract; dedupe is string-equality on `id`.
- `RenderedEvent` (`event_copy.py:78`) — the event-messaging projection that
  already maps into ActionItem via `_rendered_to_action_item_dict`
  (`operator_console.py:702`) and merges provider-wins in `merge_with_event_sidecar`.
- `ActionChoice` (`operations_guidance.py:154`) — the recommendation-with-alternatives
  shape that already down-projects via `Guidance.to_action_items`
  (`operations_guidance.py:244`).

They **align**, but two seams are inconsistent: both `operations:` (ActionChoice)
and `supervisor:` (RenderedEvent) items carry `source=supervisor`, so the id-prefix
is not a reliable dedup/identity key; and command validation
(`command_validation.validate_command_tokens`) runs producer-side, not at the
ActionItem boundary. The human-facing fields a control room needs
(`reversible`, `plain_consequence`, an explicit `dedupe_key`) do not exist yet.

## Proposed Approach

Formalize `ActionItem` as the one canonical control-plane action contract, add the
missing fields, make `dedupe_key` first-class, reconcile the supervisor id/source
seam, enforce command validation at the boundary, classify harnesses honestly
(operator / worker / orchestrator as three independent capabilities), and prove
renderer parity across the three surfaces with one test.

This is **consolidation + a thin additive layer**, not a rebuild — and explicitly
NOT the orchestration-tree budget/breaker/undo machinery, which is deferred to a
demand-gated Plan B.

## Scope (in)

- F001 ActionItem control-plane spine (fields + dedupe_key + validation boundary + id/source reconciliation).
- F002 Operator / Worker / Orchestrator honest classification (detection + reporting only).
- F003 Renderer parity from the one model (dashboard + CLI/JSON + agent-brief).

## Scope (out)

- **Plan B** — orchestration-tree governance: tree-aware budget/breaker rollup,
  multi-writer checkpoint/undo, multi-writer drift. Demand-gated on a real
  fan-out-harness dispatch existing. (See decisions CP-D004.)
- **Plan-quality recast** — stays with the `2026-06-01-001` plan-review work.
- The native **app-wrapper** (desktop shell).
- Editing the locked flat-model `objective_contract.json` of `2026-05-30-001` in place.

## Acceptance

All three features pass per `features.json`. Spine adds the five fields with no
`safe_command`; `dedupe_key` is producer-set and is the dedup authority; command
validation is enforced at the ActionItem boundary; the trichotomy reports three
independent capability booleans; one parity test proves the same action (matched by
`dedupe_key`) renders consistently across dashboard, CLI/JSON, and agent-brief. Full
orchestrate test sweep stays green.

## Risks

- **F011/SkillAction race.** F001 folds in `ActionChoice`; F011 (`SkillAction`) is
  the heaviest unfinished feature in `2026-05-30-001`. Hard dependency: do not start
  F001 until `2026-05-30-001` locks (F014 → F011 → F010 done), or F001 churns.
- **Hidden third id scheme.** Verification covered the two known supervisor prefixes;
  F001's first step re-confirms no other producer mints a divergent scheme before the
  `dedupe_key` migration.
- **Scope creep toward Plan B.** The trichotomy (F002) makes orchestration *visible*;
  the temptation is to start governing it. F002 is detection/reporting ONLY.

## Sequencing

Starts only after `2026-05-30-001` locks. Order: F001 → F002 → F003 (parity asserts
end-to-end, so it comes last). Rebase-not-expand per CP-D003. The
`objective_contract.json` for this plan is authored at lock time.
