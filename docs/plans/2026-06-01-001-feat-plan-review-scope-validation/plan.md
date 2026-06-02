---
id: 2026-06-01-001-feat-plan-review-scope-validation
title: Plan-review — scope validation & design-review volley
description: |
  Prevent the plan-authoring defects (over-scope, exemplar/weak acceptance,
  silent prerequisites, and config-readiness friction) that repeatedly stalled
  onboarding-v0 implementation. Adds a deterministic scope lint, a design-review
  volley, pre-lock/pre-dispatch/scope-delta gates, cross-feature-edit detection,
  and actionable config readiness — catching the cheap-to-prevent class before
  any implementation round is spent.
type: feat
tier: cross-cutting
status: draft
date: "2026-06-01"
goal_type: new_feature
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  objective_contract: ./objective_contract.json
---

# Plan: plan-review — scope validation & design-review volley

## Why

Three onboarding-v0 features (F007, F012, F008) stalled mid-implementation, each
burning 3–7 paid volley rounds before the operator split or sharpened them by
hand. Every stall reduced to a **plan-authoring defect that was detectable
before any implementation round was spent**:

- **Over-scope** (F007, F012, F008): a feature spanning more than one surface
  (engine + CLI + dashboard, or ~16 providers + dashboard) exceeded a single
  600s implementer dispatch. Symptom: implementer times out, auditor keeps
  finding the next layer, verdict stays `needs_changes`, no-progress fires.
- **Exemplar / weak acceptance** (F008 "e.g. roles", F012 "validated" read as
  string-equality): an AC that gives an *example* instead of an *invariant*, so
  the implementer fixes the example and the auditor generalizes — whack-a-mole.
- **Silent prerequisite** (F012's stale `command_validation` allowlist): a
  feature that depends on a capability the plan never declared.

The implement→audit volley is working — it *catches* these — but discovering a
sizing/precision/coupling defect via **stall → operator splits → re-volley** is
the expensive path. This plan shifts that review **left**: catch the
cheap-to-prevent class at plan-author / lock / edit / dispatch time, before paid
work, and propose the fix automatically.

A fourth, related lesson (D039): when `quota_caps.json` was reset to `{}`, the
dispatch died with a raw schema exception mid-volley. DontPanic must surface
invalid config at pre-flight with actionable remediation, not crash.

## Shape — two layers + continuous enforcement

**Layer 1 — deterministic scope lint (free, always-on).** A pure module (F001)
that scores each feature for size, AC-precision, and coupling, emitting a typed
ScopeReport with risk flags + evidence. A split proposer (F002) turns a flagged
feature into a clean partition (conservation-checked). Surfaced via
`dontpanic plan-review` (F003).

**Layer 2 — design-review volley (paid, triggered).** The existing
`dispatch_volley` harness with a design-reviewer auditor role (F005) red-teams a
decomposition for sizing, coupling, testability, dependency order, and missing
prereqs — reserved for plans the lint can't fully judge.

**Enforcement hooks (override-able, never silent walls):**
- `pre_lock` design gate (F004): can't lock an over-scoped/exemplar plan without
  recorded rationale.
- mid-dev scope-delta (F006): re-lint the diff on every plan edit; classify
  sharpen/expand/split; enforce the scope-change protocol.
- `pre_dispatch` sizing gate (F007): block an over-budget feature before any
  paid round; show the split proposal as remediation.
- cross-feature edit detection (F008): flag a patch that touches another
  feature's owned files (the F008→F013 dashboard bleed).
- actionable config-readiness (F009): no raw schema hard-stops; emit a validated
  remediation command + dashboard pointer.

## Dependency order

```
F001 (lint core) ─┬─ F002 (split proposer) ─ F003 (plan-review CLI)
                  ├─ F004 (pre-lock gate) ─ F006 (mid-dev scope-delta)
                  ├─ F005 (design-review volley)
                  ├─ F007 (pre-dispatch sizing gate)
                  └─ F008 (cross-feature edit detection)
F009 (config readiness) — independent
```

## Calibration corpus

Thresholds (surface-count, AC-count) are seeded from the three real stalls
(F007/F012/F008) and refined by every future stall-or-clean-converge. The
completion test requires the plan-review plan to **pass its own lint** (dogfood).

## Non-goals

Not a replacement for the implement→audit volley (this reviews *structure*, not
code correctness). Not an eliminator of all stalls — defects only discoverable by
running stay the volley's job. No silent plan mutation; every gate is
override-able with recorded rationale.

## Provenance

Born from onboarding-v0 stalls F007/F012/F008 and decisions D034–D039. See
`docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/decisions.jsonl`.
