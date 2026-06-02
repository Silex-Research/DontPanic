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

Across onboarding-v0, **~6 features over-scoped** (F007, F012, F008, F009, and the
F011→F016 chain) — each burning 3–7 paid volley rounds (or a hard 600s implementer
timeout) before the operator split or sharpened them by hand. The cleanest signal
arrived late: **F016 timed out at 600s on BOTH rounds even though it was already a
split of F011** (only 5 ACs, but spanning CLI + dashboard + doctor — three
surfaces). The cheapest signal also arrived: **F011's 14-AC over-scope was caught
PRE-dispatch via a 3-way split** — this plan's whole thesis, already demonstrated
working once by hand. Every over-scope reduced to a **plan-authoring defect
detectable before any implementation round was spent**:

- **Over-scope** (F007, F012, F008, F009, F016): a feature spanning more than one
  surface (engine + CLI + dashboard, or ~16 providers, or CLI + dashboard +
  doctor) exceeded a single 600s implementer dispatch. **Surface-count, not just
  AC-count, is the signal**: F016 timed out at 5 ACs across 3 surfaces, while
  F015 (4 ACs, one module) converged clean. Symptom: implementer times out,
  auditor keeps finding the next layer, verdict stays `needs_changes`,
  no-progress fires.
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

A related lesson, now with **two** real instances, motivates config-readiness
(F009): (D039) when `quota_caps.json` was reset to `{}`, the dispatch died with a
raw schema exception mid-volley; and (D065) the live `~/.dontpanic/config.json`
still held invalid role strings (`Grok-Builder`/`Codex-Auditor`) that blocked the
goal-completion audit at *plan-close* — and `doctor` never proactively flagged it.
DontPanic must surface invalid config (quota **and** roles) at pre-flight with
actionable remediation, and `doctor` should warn on bad role config before it
blocks a paid action — not crash, not block silently.

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

Thresholds (surface-count weighted above AC-count) are seeded from the real
onboarding-v0 labels and refined by every future stall-or-clean-converge:
- **Over-scope (timed out / stalled):** F007, F012, F008, F009 (600s timeout),
  F016 (5 ACs × 3 surfaces — CLI+dashboard+doctor — timed out both rounds),
  F011 (14 ACs, caught pre-dispatch by split).
- **Clean-converge:** F015 (4 ACs, one module + tests), F011-core (engine only),
  F014 (3 ACs, single surface), F013 (dashboard live-path only).
The discriminating feature is **surface-count**: ≥3 surfaces over-scoped even at
low AC-count (F016); single-surface stayed safe up to ~4 ACs (F015/F014). The
completion test requires the plan-review plan to **pass its own lint** (dogfood).

## Non-goals

Not a replacement for the implement→audit volley (this reviews *structure*, not
code correctness). Not an eliminator of all stalls — defects only discoverable by
running stay the volley's job. No silent plan mutation; every gate is
override-able with recorded rationale.

## Provenance

Born from onboarding-v0 over-scope events F007/F012/F008/F009/F011→F016 and
decisions D034–D039 (original three) plus D055/D056 (F009 timeout→split),
D060 (F011 3-way pre-dispatch split — the working counter-example), D063 (F016
timeout-of-a-split), and D065 (the second config-readiness instance: invalid
`~/.dontpanic` roles blocking goal-close + the doctor gap). See
`docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/decisions.jsonl`.
