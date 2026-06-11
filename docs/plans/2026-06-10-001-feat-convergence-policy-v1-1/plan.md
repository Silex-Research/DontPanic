---
id: 2026-06-10-001-feat-convergence-policy-v1-1
title: Convergence policy v1.1 — high matrix_pin disposition eligibility after repeated full clearance
type: feat
tier: cross-cutting
status: active
date: "2026-06-10"
goal_type: new_feature
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  objective_contract: ./objective_contract.json
description: >
  Close the residual gap the C0 return measured (C0 D017): high-severity
  findings that the auditor itself classifies matrix_pin are un-dispositionable
  under v1 (severity trumps class), so detector-table enumeration continues one
  paid round at a time even at 100% clearance. v1.1: after N consecutive
  full-clearance rounds (default N=2), a HIGH matrix_pin becomes
  disposition-eligible — but ONLY via a new high-rigor disposition kind that
  requires explicit operator confirmation text; critical severity is never
  eligible and plan_contract stays under the unchanged v1 waiver-only rule. Dogfood against C0 ledger rounds
  1-3 (real auditor-emitted classes) plus the original nine fixture rounds.
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

C0 rounds 8-10 under the live v1 policy: branches fired correctly, clearance
was 100% every round, and the AUDITOR ITSELF classed the blocking highs as
matrix_pin — yet branch (b) kept the hard block each time. The override valve
worked (C0 D017 -> recorded override), but the policy should handle this case
first-class instead of routing mature matrix-tails through the blunt
whole-plan override.

## Features

- **F001** — policy amendment: a pure `clearance_streak` helper + the v1.1
  rule in convergence_verdict — a HIGH (never critical) finding classed
  matrix_pin by the auditor becomes suppressible by a valid
  waived_matrix_pin_high disposition IFF the ledger shows >= N consecutive
  full-clearance audit rounds ending at the current round (configurable,
  default 2). Critical severity and conservative-fallback classifications
  are never eligible; plan_contract stays under the UNCHANGED v1 rule
  (block unless explicitly waived_with_reason or cleared by a plan edit —
  the streak rule never applies to it, at any severity); medium/low
  handling and the legacy override are byte-for-byte unchanged. verdict_for + exhaustive matrix
  updated for the streak-conditional cell.
- **F002** — disposition kind + wiring: record_disposition accepts
  waived_matrix_pin_high only for streak-eligible high matrix_pins, requires
  explicit operator confirmation text (>= 20 chars, no default anywhere),
  records/mirrors/invalidates like existing kinds; CLI passthrough; the lock
  refusal names the finding id + exact disposition command when streak
  eligibility is unlocked.
- **F003** — dual real-corpus dogfood: C0 live rounds 1-4 AND
  worktree-isolation-v0 rounds 1-3 (both auditor-classed) copied verbatim as
  fixtures. Positive case: C0 r3 matrix_pin high eligible at streak=2.
  Discrimination cases: C0 r4 still blocks on its plan_contract high even
  with its matrix_pin high dispositioned; worktree r3 (streak=2) still blocks
  on its plan_contract high — v1.1 must NOT unlock it. Prior nine fixture
  rounds verdict-stable. Zero live auditor calls.

## Non-goals

- No change to medium/low handling, accepted_into_plan, the legacy override,
  or the auditor prompt.
- No auto-disposition — operator confirmation text is mandatory.
- No streak credit across override events; no relaxation for plan_contract
  highs regardless of streak length (the worktree-v0 ledger is the standing
  counterexample fixture).

## Decisions
See `decisions.jsonl`.
