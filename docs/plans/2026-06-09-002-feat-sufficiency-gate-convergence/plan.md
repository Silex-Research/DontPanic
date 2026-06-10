---
id: 2026-06-09-002-feat-sufficiency-gate-convergence
title: Sufficiency-gate convergence — round tracking, policy, operator disposition
type: feat
tier: cross-cutting
status: active
date: "2026-06-09"
goal_type: new_feature
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  objective_contract: ./objective_contract.json
description: >
  Give the pre-impl sufficiency gate a stopping condition. Today the gate is an
  unbounded contract enumerator: on a contract-heavy plan there is always one
  more cross-product cell to pin (language x evidence type x tier x phase x
  fixture x status), so every paid round clears the prior findings completely
  and surfaces a fresh layer. This plan adds round tracking with stable finding
  ids and a closed finding-class taxonomy, a deterministic convergence policy
  (full-clearance + only medium/low pin-class findings -> operator disposition
  instead of another paid hard block; new high or conceptual plan_contract
  findings keep blocking), a durable per-finding disposition artifact, and a
  dogfood suite replaying the six committed C0 rounds as offline fixtures.
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

Plan C0 (`2026-06-09-001`) ran six sufficiency rounds (finding counts
3→2→4→3→4→5). Every round cleared 100% of the prior round's findings — the
tightening worked every time — and every round surfaced a new, narrower layer.
None of the findings were wrong; the LOOP is structurally unbounded. The
implementation volley loop already solved this exact problem (Design B
strictly-shrinking-count convergence breakers, plan `2026-05-30-002`); the
pre-impl sufficiency gate never got the analog. Operator directive 2026-06-09:
build the convergence rule first, then return to C0 under it.

## Features

- **F001** — sufficiency round tracking: every auditor run appends a durable
  round record (finding count, stable finding ids + fingerprints per F006,
  prior ids cleared vs persisted, new-finding severities, and a closed
  finding-class enum: plan_contract / implementation_detail / editorial /
  scope_guard / matrix_pin, conservative fallback to plan_contract) to an
  append-only rounds ledger in plan evidence.
- **F002** — convergence policy: a pure, deterministic function over the rounds
  ledger + recorded dispositions, exhaustive over severity × class. Full
  clearance + all new findings medium/low and classed in the eligible set
  {matrix_pin, implementation_detail, editorial, scope_guard} →
  operator_disposition_required (no further paid hard block). Any new
  high/critical → keep blocking. plan_contract → keep blocking; neutralizable
  only by an explicit waiver-with-reason disposition or a clearing plan edit.
- **F003** — disposition artifact: per-finding operator dispositions
  (accepted_into_plan / deferred_to_impl / waived_with_reason /
  split_to_followup_plan) recorded durably via a CLI surface, honored by the
  lock path, mirrored into decisions.jsonl, and invalidated if the finding
  recurs materially changed.
- **F004** — dogfood: replay the six committed C0 rounds as offline fixtures
  (explicit retrospective class annotations + a fallback companion test);
  assert ledger reconstruction, full-clearance detection, per-round policy
  verdicts, and that round 6's three medium eligible-class findings are
  disposition-eligible while its high finding keeps the block. Zero paid calls.
- **F005** — lock-path wiring: refusals name the policy branch that fired; the
  no-auditor resolution path (no-audit-kind dispositions cover the latest
  round + unchanged input fingerprint) proceeds with zero paid calls; a
  changed fingerprint falls back to the plain gate with a fresh audit;
  accepted_into_plan always routes through the plain gate.
- **F006** — two-level finding identity: semantic id from locator fields with
  deterministic same-cell ordinals + content fingerprint over severity, class,
  description, and recommendation; escalation is material change; fail-closed
  cell invalidation (any cell-set change re-surfaces its dispositions as
  blocking). Pure functions.

## Non-goals

- Post-impl (completion-gate) convergence — pre-impl only in v0.
- Auto-disposition — the operator stays in the loop; the policy only changes
  WHAT the gate demands (disposition vs another paid round), never decides it.
- Auditor model/prompt changes beyond emitting the finding class.
- Unlocking C0 itself — that is the follow-up step under the new policy
  (expected split per operator: block/tighten = tier-1 heuristic language set +
  evidence-type satisfaction rules; tighten/edit = F003 purity parity, F005
  empty-repo wording, no-new-parser-extractors scope guard).

## Decisions
See `decisions.jsonl`.
