---
id: 2026-06-14-002-feat-experience-readiness-gate-v0
title: Experience Readiness — close-time enforcement v0 (2b)
type: feat
tier: cross-cutting
status: draft
date: "2026-06-14"
goal_type: new_feature
description: >
  The close-time ENFORCEMENT half of the Experience Readiness Gate (split from
  the original combined plan by operator decision D025; sibling typing plan =
  2026-06-15-001 / 2a). Owns the deterministic consumer_outcome_gate in
  completion_gate.close_plan, the activation rule (opt_in OR consumer-journey OR
  product-class/metadata), the block/advisory/noop posture matrix,
  consumer-cardinality enforcement (human/agent/both), and structured deferral/
  disposition. It CONSUMES 2a's stable vocabulary (closed surface_class/
  evidence_class enums, consumer families, structured EvidenceRef fields, the
  typing rule + degraded checker) and MUST NOT lock until 2a is merged. A
  declared consumer outcome on a product-class or consumer-journey-bearing plan
  cannot close unproven; enforcement is deterministic at close (not LLM-triage
  dependent); product claims cannot dodge by omitting a flag or a journey.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
privacy_tier: internal
links:
  features: ./features.json
  objective_contract: ./objective_contract.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  audits_dir: ./audit/
---

## Target

```yaml
target_env: dev
target_project: none
```

## Frame

This is the enforcement layer of the Experience Readiness Gate. The original
combined plan (`2026-06-14-002`) converged its typing layer over two paid
sufficiency rounds, but the **enforcement matrix** — activation × posture ×
deferral × consumer-cardinality × no-journey — kept surfacing new high/critical
conceptual contradictions each round (round-3 returned 1 critical + 1 high on
this layer, including a self-inflicted activation/posture contradiction). Per
operator decision (D025) the gate is split; this plan is **2b**, and it is held
**draft** until **2a (`2026-06-15-001`) is merged** so enforcement consumes a
stable, locked vocabulary rather than co-evolving one.

**Dependency:** 2b consumes 2a's `surface_class`/`evidence_class`/`consumer`/
`data_source`/`availability` schema + the typing rule + the degraded checker.
Do not lock 2b until 2a is merged to main.

## Feature

- **F001 — Close-time enforcement + disposition** (was F005 in the combined
  plan). A pure activation predicate + posture function, and a DETERMINISTIC
  pre-flip `consumer_outcome_gate` in `completion_gate.close_plan` that blocks
  the `active → completed` flip on an unproven declared consumer outcome,
  INDEPENDENT of the codex F0 cluster triage (whose only blocking triage is
  `child_plan`). Activation: opt_in (`experience_readiness_opt_in`) OR any
  journey declaring `consumer` OR product-class `goal_type`/metadata. Posture:
  consumer-journey-bearing plans block only on an unproven, undeferred,
  undispositioned outcome; pending is a per-journey advisory outcome;
  satisfied/deferred/dispositioned outcomes allow close; product-class plans
  with no journeys and substrate plans opted-in with no journeys are advisory;
  otherwise no-op. `consumer=both` applies the D035 not-yet-typed human pending
  carve-out rather than a binary both-families-proven rule.
  Deferral (structured non_goal naming {journey, consumer}) and disposition
  (`consumer_outcome_dispositions[]`) are structured, not prose. **Round-3
  resolutions:** D030 (consumer-journey-bearing always blocks regardless of
  flag; warn only for opt-in-no-journey substrate) and D031 (product-class with
  no declared journey emits `no_consumer_journey_declared`, not a silent pass).

## Open enforcement questions to resolve before lock

These are the genuinely hard, architecture-coupled decisions this focused plan
exists to settle (they are why the split happened):

1. The exact `consumer_outcome_gate` signature + where in `close_plan` it sits
   relative to `_decide_blocking` and the override path.
2. Posture matrix edge cases (incident/migration goal_types; opt-out).
3. Whether `no_consumer_journey_declared` is advisory-only or blocking for
   product-class plans.
4. Disposition record storage + input-bound invalidation (mirror the
   `override.json` pattern).

## Non-goals

- The TYPING/EVIDENCE layer (schema, typing rule, agent harness, degraded
  checker) — sibling plan **2a** (`2026-06-15-001`); 2b consumes it.
- QuantRE Product Readiness plan; re-building human capture; a11y/visual depth.

## Surfaces touched

engine only (`scripts/dontpanic_orchestrate/completion_gate.py`,
`completion_auditor.py` — the deterministic gate + `consumer_outcome_unproven`
finding + posture/activation). No schema or harness changes (that's 2a).

## Decisions

See `decisions.jsonl` — the enforcement subset carried from the combined plan
(D002 posture, D013 both-families, D015 real-vs-degraded close, D016 structured
deferral/disposition, D021 deterministic gate, D022 activation, D025 the split)
plus the round-3 enforcement resolutions **D030** (activation/posture
contradiction resolved) and **D031** (product-class no-journey advisory).
