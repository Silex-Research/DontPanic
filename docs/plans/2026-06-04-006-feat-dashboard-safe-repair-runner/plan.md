---
id: 2026-06-04-006-feat-dashboard-safe-repair-runner
title: Dashboard safe-repair runner (ordered, safety-classified repair plan an agentic operator can execute)
type: feat
tier: cross-cutting
status: draft
date: "2026-06-04"
goal_type: new_feature
description: >
  Turn the dashboard from passive (twenty cards with raw commands) into an
  autopilot layer: from the truthful render-gate output, build a dependency-ordered
  repair plan whose every action carries a producer-asserted safety class
  (auto_safe | human_required | blocked_external | info). DontPanic emits that plan
  as a machine-readable bundle an external agentic operator can execute
  (emit-only, the default, no mutation); an opt-in `--apply` runs ONLY the
  auto_safe derived-state-regeneration batch locally, recomputing and verifying
  after each step. Human stops occur only where credentials, spend, destructive
  changes, source-of-truth writes, or external approval are genuinely required.
motivation: >
  For a human driving Codex/Claude/Grok as the operator, the dashboard should say
  "Agent: run these 7 safe repairs; Human: answer these 2 decisions" — not surface
  twenty cards and hope someone runs the snippets. The pieces exist: 001 gives
  action resolvability (resolution_class + clears_when round-trip), 004 gives
  state/freshness truth, 005 gives scope/render truth. What is missing is the
  orchestration layer on top: a dependency-ordered, safety-classified repair plan
  with round-trip verification and an agent-handoff bundle.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
privacy_tier: internal
dependencies:
  - 2026-06-04-005-feat-render-truth-scope-contract

links:
  features: ./features.json
  decisions: ./decisions.jsonl
---

# Dashboard safe-repair runner

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal dashboard / repair-orchestration plan. No external service setup
required.

## Problem / Motivation

The dashboard is too passive. After 005 it tells the truth about what is wrong, but
the operator still gets independent cards with raw commands. For an agentic operator
that is the wrong interface: it should receive an ordered, safe, executable plan and
stop the human only where a human is genuinely required.

The primitives already exist and must be reused, not re-invented:

- `resolution_class` (001) already classifies HOW a card resolves
  (command_resolvable / chained / operator_attested / blocked_external).
- `clears_when` (001) already provides round-trip verification (run → recompute →
  did the predicate clear?).
- The 005 render gate already says what is genuinely unresolved (render) vs stale
  (demote) vs resolved (suppress).

What is missing is the autopilot: ordering, a safety taxonomy distinct from
resolvability, a fixpoint re-plan loop, an agent-handoff bundle, and the verification
wiring.

## Proposed Approach

Add a repair-orchestration layer over the 005 render-gate output:

1. **Safety taxonomy (producer-asserted).** Every action carries
   `safety_class ∈ {auto_safe, human_required, blocked_external, info}`, asserted by
   the emitter and validated against a safety policy. `auto_safe` requires ALL of:
   local, reversible-or-read-only, bounded, no credentials, no paid agent dispatch,
   no deploy, no destructive file changes, and **no write to source-of-truth** (it
   may only regenerate derived/cached projection state). The runner NEVER infers
   safety; an unclassified action defaults to `human_required` (fail closed, the same
   discipline as 005's scope).

2. **Dependency-ordered planner (fixpoint).** Build an ordered plan from the visible
   unresolved cards; apply the `auto_safe` batch; recompute state; re-plan; repeat
   until only `human_required` / `blocked_external` / `info` remain or no progress is
   made. A state-changing step recomputes the next needed step rather than trusting a
   static list. Terminates and logs whatever it deferred.

3. **Emit-only by default.** `dontpanic repair plan --scope … --format=json` produces
   the agent-handoff bundle — ordered actions with command, safety_class, clears_when,
   plain consequence, and scope — with **no mutation**. Any agentic operator runs it.

4. **Tiered opt-in local apply.** Execution is gated in escalating tiers so the
   default never crosses the mutation boundary silently:
   - `repair plan` (default) — emit only, no execution.
   - `repair apply --safe-derived-state` — executes ONLY derived/projection/cache
     actions (apply_tier=`derived_state`): rebuild dashboard state, recompute
     what-now, refresh capability status, refresh reconcile *check* (not baseline
     write), regenerate architecture map if bounded, clear *replaceable* generated
     dashboard caches, re-export state, suppress resolved cards.
   - `repair apply --safe --confirm` — additionally executes an explicit allowlist of
     local safe mutations (apply_tier=`confirmed_local`); requires the stronger flag.
   No tier executes deploys, credential setup, paid dispatches, role changes, plan
   state mutation, project-registry changes, destructive file cleanup, or
   reconcile-baseline writes (those stay human_required unless explicitly approved).
   Every executing tier requires per-command `safety_class` + `clears_when` +
   round-trip verification.

5. **Round-trip verification.** After each applied action, recompute and verify the
   targeted card cleared, chained, or became human_required; a card that does not
   change is flagged defective/incomplete (reusing 001's clears_when invariant at
   runtime).

6. **Dashboard surfaces.** "Repair automatically" (runs the apply batch via the
   runner) and "Copy agent repair plan" (emits the bundle), both scope-aware via 005.

## Scope (in)

- F001 Producer-asserted safety taxonomy + policy (auto_safe/human_required/
  blocked_external/info; fail-closed default human_required).
- F002 Dependency-ordered fixpoint repair planner over the 005 render-gate output.
- F003 `dontpanic repair plan --format=json` emit-only agent-handoff bundle (no
  mutation).
- F004 `dontpanic repair apply --safe` opt-in local apply of the auto_safe
  derived-state batch only; refuses source-of-truth writes / creds / spend / deploy.
- F005 Round-trip verification: each applied action must clear/chain/become
  human_required, else flagged defective.
- F006 Dashboard "Repair automatically" + "Copy agent repair plan", scope-aware.

## Scope (out)

- No paid agent dispatch, deploy, destructive file changes, or credential entry under
  `--safe`.
- No mutation of plan/registry source-of-truth under `--safe` (derived/cached
  projection regeneration only; reconcile-baseline writes stay human cards).
- No remote / multi-operator execution; no hosted control plane.
- No new resolution predicates beyond what 005/001 provide (reuse the closed
  registry).
- Redesigning the render gate, scope lattice, or freshness — that is 005.

## Acceptance

`dontpanic repair plan --scope <s> --format=json` emits a dependency-ordered,
safety-classified bundle (command + safety_class + clears_when + plain consequence +
scope) with zero mutation. `dontpanic repair apply --safe` runs ONLY the auto_safe
derived-state-regeneration batch, refuses any source-of-truth write / credential /
spend / deploy / destructive action (those remain human cards), recomputes after each
step, verifies each targeted card cleared/chained/became human_required (flagging any
that did not as defective), and re-plans to a fixpoint leaving exactly the
human_required / blocked_external / info cards. Safety is producer-asserted and
validated against the policy; an unclassified action defaults to human_required and
never auto-runs. The dashboard exposes "Repair automatically" and "Copy agent repair
plan", scope-aware via 005. Full orchestrate sweep stays green.
