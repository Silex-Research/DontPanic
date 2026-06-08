---
id: 2026-06-07-002-fix-plan-review-introduces-vocabulary
title: plan-review introduces-vocabulary — let a feature declare the symbols it defines so contract/greenfield plans don't self-deadlock
type: fix
tier: cross-cutting
status: active
date: "2026-06-07"
goal_type: new_feature
description: >
  Close a real plan-review gate gap. The pre-lock coupling lint flags any AC token
  it can't resolve as missing_prereq (block-severity), and the resolver only knows
  the EXISTING codebase vocabulary. A greenfield/schema/contract plan intentionally
  DEFINES new symbols, so its deliverable vocabulary cannot exist at lock time and
  the plan self-deadlocks (the "no self-deadlocking plans" pattern: a plan that
  introduces a signal blocked by the gate that consumes it). Concretely, plan
  2026-06-07-001 (architecture evidence contract) cannot lock because its enum
  names are flagged as unresolved.

  Add a principled escape hatch: an optional PER-FEATURE `introduces` list naming
  the symbols that feature defines. The lint treats an introduced symbol as locally
  defined — but only for the introducing feature and features that come AFTER it in
  plan order, so dependency reasoning is preserved (a feature cannot rely on a
  symbol a LATER feature introduces). Unknown/misspelled symbols still block. The
  report shows introduced symbols explicitly ("introduced here"), never silently.
  Plans without `introduces` behave exactly as today.

  Per-feature (not plan-level) is deliberate: plan-level declaration would let
  any feature lean on any symbol regardless of order, erasing the dependency signal.
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
---

## Target

```yaml
target_env: dev
target_project: none
```

## Shape

A feature record may carry an optional list of the symbols it introduces. Example
(plan-level form rejected; per-feature form is canonical):

```yaml
# per-feature (canonical — preserves dependency order)
features:
  - id: F001
    introduces: [source_kind, evidence_basis, confidence]
  - id: F004
    introduces: [as_built, diff_taxonomy]
```

Order rule: when linting feature at order *i*, the resolver is augmented with the
union of `introduces` from every feature at order ≤ *i*. So F001 may use a symbol
it introduces; F004 may use a symbol F001 introduced; F001 may NOT use a symbol
F004 introduces; and a never-introduced token still blocks.

## Features
- **F001 introduces field on feature records** — accept an optional per-feature
  list of identifier strings naming the symbols that feature defines; absent or
  empty means today's behavior exactly; malformed entries (non-list, non-string,
  non-identifier) are rejected with a clear error. Parsed into the per-feature
  scope report. No change to plans that omit it.
- **F002 order-aware resolution in the coupling lint** — a symbol resolves when it
  is in the existing codebase vocabulary OR is introduced by the same feature or an
  earlier feature in plan order. A symbol introduced only by a later feature still
  raises missing_prereq (dependency ordering preserved). A never-introduced /
  misspelled token still raises missing_prereq. Pure, deterministic, unit-tested.
- **F003 report surfaces introduced symbols** — the plan-review report (text + JSON)
  names each feature's introduced symbols, labelled introduced-here, rather than
  silently dropping them; a symbol resolved via introduces never appears as a
  missing_prereq. Reports for plans without the field are unchanged.

## Sequence
F001 (field + parse) → F002 (order-aware resolver in the lint) → F003 (report
surfacing). Single plan-review surface; pure logic + tests.

## Out of scope
- Cross-PLAN symbol resolution (introduces is scoped within one plan only).
- Auto-deriving introduced symbols from features.json shape or code (authors
  declare them explicitly — the gate stays honest about typos).
- Any change to the architecture evidence contract itself (plan 2026-06-07-001).
