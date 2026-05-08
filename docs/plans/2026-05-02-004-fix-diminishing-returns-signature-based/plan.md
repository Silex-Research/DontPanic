---
id: 2026-05-02-004-fix-diminishing-returns-signature-based
title: Diminishing-returns breaker — signature-based, not count-based
type: fix
tier: local
status: completed
date: "2026-05-02"
description: |
  Replace the count-only diminishing-returns heuristic with a signature-based
  check. The current `check_diminishing_returns` (circuit_breakers.py:857)
  trips when auditor finding COUNT is non-decreasing across two consecutive
  needs_changes rounds. That conflates "auditor found 3 different problems
  twice" with "auditor flagged the SAME 3 problems twice." Operator workflows
  legitimately volley 5–10x to improve a feature; under count-only the breaker
  fires on round 2 every time the count stays flat even when findings have
  shifted entirely. New contract: trip when the SAME finding signatures
  persist across the last N auditor rounds — i.e., the auditor really is
  stuck on the same issues. Falls back to the legacy count behavior when
  signatures can't be derived (missing issue text, etc.) and names the
  fallback in the breaker reason so operators see why count fired instead
  of identity. Reuses the F001 `compute_finding_signature` primitive so
  nested-orchestration's repeated-finding guard and this breaker share a
  single notion of finding identity.
motivation: |
  Concrete real-world signal: SpinDine plan 2026-05-01-001-feat-android-
  sprint1-parity-fixes terminated `stopped_diminishing_returns` at
  iteration 1 with `auditor finding counts [3, 3]` — even though the i0
  and i1 findings were genuinely different problems (the implementer had
  fixed the originals; the auditor had surfaced new ones of similar cardinality).
  This pattern is exactly what feedback_volley_failure_taxonomy.md memory
  flagged at the operator level: "raw count is a misleading stop signal."
  This plan fixes that gap at the platform level. The wrong heuristic
  forces operators to manually triage findings AND repeatedly re-dispatch
  to clear an over-firing breaker; the right heuristic does the triage
  in code by comparing signature sets.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  no_progress_threshold: 2
  wall_clock_hours: 2
  hard_stop: false
privacy_tier: internal
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/maintainer/refresh-costs.sh
dependencies:
  - 2026-05-02-003-feat-nested-orchestration-v1
links:
  features: ./features.json
  decisions: ./decisions.jsonl
---

# Diminishing-returns breaker — signature-based, not count-based

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Single-feature platform fix to `circuit_breakers.check_diminishing_returns`.
Adds a thin `compute_audit_finding_signature` helper to
`nested_orchestration.py` (sibling of F001's existing
`compute_finding_signature`). Replaces the breaker body to compare signature
sets across rounds; falls back to count when signatures can't be derived.

## Out of scope

- Operator config knob for `DIMINISHING_RETURNS_MIN_ROUNDS` (D003 — keeping
  it a constant; signature-based behavior should be sufficient without
  per-project tuning).
- Severity inclusion in the signature (D002 — a high→medium downgrade is
  the same finding, not a different one).
- Migrating other count-based heuristics. `check_no_progress` (which
  compares verdict equality, not finding count) is unaffected.
- Backfilling old audit envelopes. The fallback path handles legacy data.

## Acceptance

See features.json F001.
