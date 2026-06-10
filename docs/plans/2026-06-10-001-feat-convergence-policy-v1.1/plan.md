---
id: 2026-06-10-001-feat-convergence-policy-v1.1
title: Convergence policy v1.1 — high matrix_pin disposition eligibility after repeated full clearance
type: feat
tier: cross-cutting
status: draft
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
  requires explicit operator confirmation text; critical severity and
  plan_contract class remain absolute blocks. Dogfood against C0 ledger rounds
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

- **F001** — policy amendment: in convergence_verdict, a HIGH (never critical)
  finding classed matrix_pin by the auditor becomes disposition-eligible IFF
  the ledger shows >= N consecutive full-clearance audit rounds (configurable,
  default 2) AND the operator dispositions it with the new
  waived_matrix_pin_high kind requiring explicit confirmation text; the
  refusal message names the unlocked eligibility. plan_contract and critical
  remain absolute. Exhaustive-matrix test updated; C0 ledger rounds 1-3
  replayed as fixtures proving round 3's high would have been eligible while
  rounds 1-2 (no streak yet) block.

## Non-goals

- No change to medium/low handling, accepted_into_plan, the legacy override,
  or the auditor prompt.
- No auto-disposition — operator confirmation text is mandatory.

## Decisions
See `decisions.jsonl`.
