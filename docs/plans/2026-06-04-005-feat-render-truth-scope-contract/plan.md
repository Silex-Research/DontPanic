---
id: 2026-06-04-005-feat-render-truth-scope-contract
title: Dashboard render-truth scope contract (fail-closed; scope every card, demote stale to uncertainty)
type: feat
tier: cross-cutting
status: active
date: "2026-06-04"
goal_type: new_feature
description: >
  Harden the dashboard into a single contract: a Needs Action card may render only
  if its producer can prove the issue exists for the currently selected scope. That
  means a unified render gate with three outcomes (render / suppress-resolved /
  demote-uncertain), an explicit producer-asserted scope on every card, per-source
  freshness so one stale producer demotes only its own cards, generalizing the
  architecture stale-to-uncertainty demotion to every producer, and a global/project
  separation where global state is computed once and projected by scope with a GLOBAL
  badge — never a stale per-project cache pretending to be live project truth.
  Stale evidence may explain uncertainty; it may not create a Needs Action card.
motivation: >
  001 gave us clears_when + resolution classes + suppress-at-source (action truth);
  004 gave provenance + lifecycle/activity axes + freshness + the architecture
  stale-to-uncertainty demotion (render truth). But the render default is still
  render-unless-proven-resolved: clears_when=None items always render, scope is
  inferred at render by a heuristic relevance ladder rather than asserted by the
  producer, only the architecture producer demotes on staleness (reconcile /
  capabilities / gates keep last-known cards as live Needs Action when their source
  is stale or recompute fails), and a global reconcile/install issue can render in a
  project view with no GLOBAL badge — a global issue disguised as project-specific.
  The QuantRE case (a stale/global health card shown as project-scoped) is the
  concrete failure this contract closes.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
privacy_tier: internal
dependencies:
  - 2026-06-04-001-feat-ledger-reconciliation-operator-actions
  - 2026-06-04-004-feat-dashboard-state-fidelity

links:
  features: ./features.json
  decisions: ./decisions.jsonl
---

# Dashboard render-truth scope contract

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal dashboard / state-projection plan. No external service setup required.

## Problem / Motivation

The render path proves issues *negatively* and *partially*:

- **Render-unless-proven-resolved.** `suppress_resolved` only drops items whose
  `clears_when` evaluates true; items with `clears_when=None` (architecture,
  supervisor, capability-not-installed) always render. There is no single gate that
  refuses to render a Needs Action card that cannot prove it is live.
- **Scope is inferred, not asserted.** `ActionItem` carries `project_name` but no
  explicit `scope`. `dashboard_relevance.is_item_relevant_to_project` infers
  global-vs-project via a heuristic precedence ladder (doctor/install blockers
  universally relevant; capability cards checked against declarations;
  architecture/supervisor/gate unscoped → relevant). Relevance is a boolean, so a
  global card renders inside a project view with no GLOBAL badge.
- **Stale survives as live (except architecture).** Only `render_architecture_status`
  demotes a failed/stale source to a "could not refresh" view. Reconcile,
  capabilities, and gates keep their last-known card as Needs Action when their
  source is stale or a recompute fails — the operator sees old data as if live.
- **Freshness is snapshot-wide.** `freshness_status` stamps the whole page with one
  `generated_at`; there is no per-source/per-card freshness, so one stale producer
  cannot demote only its own cards.

## Proposed Approach

Make the render path *fail closed* around a single gate. For the currently selected
scope S, every visible Needs Action card must satisfy, and prove:

```
card.scope applies to S            (scope lattice: global ⊇ every project view, etc.)
card.source was refreshed          (per-source freshness, not snapshot-wide)
card.clears_when unresolved         (predicate evaluates issue still present)
card.resolution_class is set        (says how it can resolve)
```

A card that cannot prove all four does not appear as Needs Action. At most it
appears under a lower-priority "Status could not be refreshed" section as an
uncertainty/freshness card — never as live setup drift.

The gate is one deterministic function with a **normative order** (the only place a
demote decision is made; F004 only *builds* the demotion card):

```
1. scope applies to selected scope?      else SUPPRESS  (not relevant to this view)
2. source fresh AND evaluable?           else DEMOTE
3. clears_when present AND evaluable?     else DEMOTE
4. resolution_class set?                  else DEMOTE
5. predicate resolved?                    -> SUPPRESS
6. else (unresolved)                      -> RENDER
```

Three total, mutually-exclusive outcomes:
- **render** — all four proofs pass and predicate unresolved → Needs Action.
- **suppress** — scope doesn't apply (step 1) or predicate resolved (step 5) → drop.
- **demote** — cannot prove (stale/failed source, no/uncheckable predicate, missing
  resolution_class, unresolvable plan→project) → one uncertainty card
  (`band=info`, `resolution_class=blocked_external`, `section=status_uncertain`) in
  the low-priority section, never Needs Action.

Global state is computed once and projected by scope: a global producer emits one
`scope=global` card; a project view shows it with a GLOBAL badge iff it still applies
(predicate unresolved) and is fresh, and hides it when global state is clean. A
now-clean global card must never be resurrected from a per-project output cache.

This generalizes the architecture stale-to-uncertainty demotion (004 F007) to every
producer and inverts `suppress_resolved` (001) from "render unless resolved" to
"suppress unless proven live", reusing the existing closed predicate registry.

## Scope (in)

- F001 Unified render gate: one chokepoint every card passes through, returning
  render / suppress / demote; default is suppress-unless-proven-live.
- F002 Explicit scope: `scope ∈ {global|fleet|project|plan|feature}` (+ plan_id /
  feature_id) asserted by producers; **no silent constructor default that infers
  scope from project_name**. A scope-applicability lattice drives render; plan/feature
  scope applies only if its plan_id resolves to the selected project (else demote).
  Scope-unset legacy items go through an explicit `legacy_adapter` path that logs and
  is demotion-eligible — never silently treated as project work.
- F003 Per-source freshness: each card carries the source it was computed from and
  when that source last evaluated successfully; freshness moves from snapshot-wide
  to per-source.
- F004 Stale/failed → uncertainty demotion for ALL producers: a stale or
  failed-to-recompute source's cards collapse to a single "could not refresh
  <source>" card (`band=info`, `resolution_class=blocked_external`,
  `section=status_uncertain`; last-checked + reason), never Needs Action. F001 owns
  the demote decision; F004 only builds the card.
- F005 Global/project separation + render-truth invariant: global computed once,
  projected by scope with a GLOBAL badge when it applies and is fresh, hidden when
  clean, never resurrected from a per-project cache; an invariant test asserts every
  visible Needs Action card satisfies scope ∧ fresh ∧ unresolved ∧ resolution_class.

## Scope (out)

- New predicates beyond what producers need to assert liveness (reuse 001's closed
  registry; add a predicate only when a producer cannot otherwise prove liveness,
  recorded as a decision).
- Redesigning the supervisor registry, reconcile, or capabilities engines (consume
  their outputs; do not change how they compute).
- Realtime/multi-operator transport (Firebase) — demand-gated elsewhere.
- New integrations or operator actions — that is `2026-06-04-003`.

## Acceptance

For the currently selected scope S, every visible Needs Action card provably
satisfies all four: its asserted `scope` applies to S (via the scope lattice, not the
heuristic ladder), its source was refreshed within the freshness threshold (per-source,
not snapshot-wide), its `clears_when` currently evaluates unresolved, and its
`resolution_class` is set. A card failing any of the four never renders as Needs
Action; a stale or failed-to-recompute source produces exactly one "Status could not
be refreshed: <source>, last checked <t>, reason <r>" card in a lower-priority
section instead of its old cards. The render gate is a single function with three
outcomes (render / suppress / demote) that every card passes through. A global
producer emits one `scope=global` card shown in a project view with a GLOBAL badge
iff its predicate is unresolved and its source fresh, hidden when the global predicate
is clean, and never resurrected from a per-project output cache. Invariant tests
assert the four-part guarantee and the global/project rule; the architecture
demotion pattern is exercised through the same generalized path. Full orchestrate
sweep stays green.
