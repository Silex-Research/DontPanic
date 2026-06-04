---
id: 2026-06-04-001-feat-ledger-reconciliation-operator-actions
title: ActionItem resolvability contract (clears_when + round-trip guarantee)
type: feat
tier: cross-cutting
status: draft
date: "2026-06-04"
goal_type: new_feature
description: >
  Make every operator action DontPanic surfaces provably trustworthy: each
  ActionItem must declare what condition it clears (clears_when), be recomputed
  from live state so it disappears once that condition is gone, name the next
  step when one action surfaces another, and — when only a human/credential can
  resolve it — be explicitly marked operator_attested (clears on evidence, not a
  command). The dashboard must never say "Needs Action" unless taking the action
  will move the system forward, or it clearly states why human evidence is
  required.
motivation: >
  Today DontPanic emits operator actions without proving they are still relevant,
  sufficient, recomputed after action, or cleared when the condition is gone.
  Live evidence: 54 of 57 gate-approve cards target completed/abandoned plans
  (phantom guidance — the bulk of the dashboard's "192 NEEDS ACTION"); the
  reconcile card offered one command for a two-step fix and could not round-trip
  because its recompute was gated behind a per-project capabilities/ dir; the
  ActionItem model carries reversible/plain_consequence but no machine-checkable
  resolution predicate. This is a structural trust gap in the action model, not a
  collection of bad cards. Fix the contract, and the symptoms collapse.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
privacy_tier: internal

links:
  features: ./features.json
  decisions: ./decisions.jsonl
---

# ActionItem resolvability contract

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal orchestration-engine plan. No external service setup required.

## Problem / Motivation

A control-plane action is only honest if `condition → action/evidence → recompute
→ item clears` round-trips. DontPanic does not currently guarantee that. ActionItems
are emitted from many producers (gates, breakers, reconcile, capabilities, plan
drift, operations guidance) with no shared contract describing **what condition the
action resolves** or **how the system verifies it resolved**. The result:

- **Not relevant:** 54/57 gate-approve cards point at completed/abandoned plans.
- **Not sufficient:** the reconcile card gave one command for a two-step fix
  (`baseline` cleared `missing_snapshot` but surfaced `stale_status_cache`).
- **Not recomputed:** even after the correct action, the card persisted — its
  recompute was gated behind a per-project `capabilities/` dir that doesn't exist,
  and the static dashboard re-emitted the stale status.
- **Not cleared:** no `clears_when` predicate exists, so nothing can prove (or
  test) that doing the action removes the item.

## Proposed Approach

Establish an **ActionItem resolvability contract** as the spine, then prove it on
the two highest-impact failures, then lock it in with a generic invariant so no
future emitter can ship non-resolving guidance.

1. **`clears_when` + resolution class** on the ActionItem model — every item
   declares the machine-checkable condition it resolves and how it resolves:
   `command_resolvable` / `chained` / `operator_attested` / `blocked_external`.
2. **Round-trip recompute guarantee** — producing state re-evaluates `clears_when`
   against live reality; an emitter MUST NOT emit an item whose `clears_when` is
   already satisfied; global conditions are evaluated at global scope, never gated
   behind per-project preconditions.
3. **Proof case A — phantom suppression:** gate/approve (and sibling) items for
   completed/abandoned/superseded plans vanish via the recompute.
4. **Proof case B — reconcile/global readiness round-trip:** global readiness is
   computed once at fleet scope; the offered action(s) are chained when one step
   surfaces another; the card clears on rebuild after the action.
5. **Generic invariant** — a property test over every emitter: emitted condition →
   apply suggested command/evidence → recompute → item clears, OR the item is
   explicitly `operator_attested`/`blocked_external` (and then clears on evidence).

## Scope (in)

- F001 `clears_when` + resolution-class contract on the ActionItem model.
- F002 Round-trip recompute guarantee (suppress-if-already-clear; global scope).
- F003 Proof A: phantom-card suppression for completed/abandoned/superseded plans.
- F004 Proof B: global reconcile/readiness round-trip + action chaining +
  operator-attested handling for credential/deploy steps.
- F005 Generic round-trip invariant test across all ActionItem emitters.

## Scope (out)

- Building NEW operator actions (Firebase/Linear/Discord) — those are the
  integration-actions plan `2026-06-04-003`; this plan only guarantees that
  whatever is emitted is resolvable.
- The Local Harness Adapter (`2026-06-04-002`).
- A new close primitive (reuse `close --operator-resolved`).
- Auto-resolving anything without operator confirmation where a human is required.

## Acceptance

The ActionItem model carries `clears_when` + resolution class; state production
never emits an item whose `clears_when` is already satisfied; phantom gate cards
for closed/abandoned plans disappear (dashboard NEEDS-ACTION count drops to
live-relevant only); the reconcile/global readiness card round-trips (run the
offered/chained action → rebuild → card clears); and a generic invariant test
proves, for every emitter, that condition → action/evidence → recompute → clear
holds or the item is explicitly `operator_attested`/`blocked_external`. Full
orchestrate sweep stays green.
