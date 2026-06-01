---
id: 2026-05-30-002-fix-orchestrator-convergence-bugs
title: Fix orchestrator convergence + audit-envelope bugs
status: completed
description: |
  Fix the orchestration-engine convergence and audit-envelope selection bugs
  surfaced while dogfooding the universal onboarding plan. The corrected scope
  includes no_progress verdict-string false trips, diminishing_returns false
  positives, minimum breaker precedence needed for progress-making rounds, and
  stale latest-auditor-envelope selection.
type: fix
tier: cross-cutting
date: "2026-05-30"
goal_type: refactor
surfaces:
  - infra
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  objective_contract: ./objective_contract.json
---

# DontPanic — Fix orchestrator convergence + audit-envelope bugs

title: 2026-05-30-002-fix-orchestrator-convergence-bugs

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal orchestration-engine fix. No external service setup.

## Why

Dogfooding the onboarding-v0 plan (`2026-05-30-001`) surfaced two real correctness
bugs in the orchestration engine itself (D029 + D028 of that plan). Both make the
implementer↔auditor volley unreliable for any feature that needs more than two
rounds to converge — which is most non-trivial features. The engine is the trust
substrate every other plan depends on, so these warrant a tracked plan with
cross-model audit rather than an inline hotfix.

**Bootstrapping caveat (load-bearing):** this plan fixes the very loop that would
normally drive it. Therefore each feature here is landed via **single-agent
codex audit-only** (`dontpanic <plan> --feature FNNN --role auditor`) plus the
no-paid finalizer — NOT a multi-round volley. Using the broken convergence loop
to fix the convergence loop is a self-deadlock (cf. no-self-deadlocking-plans).

## Bugs (from 2026-05-30-001 D029 + D028, amended after failed implementation)

1. **convergence breakers false-trip before real progress can finish.**
   `circuit_breakers.check_no_progress` (circuit_breakers.py:~938-945) trips when
   `prior_status == current_status` (both `needs_changes`), regardless of whether
   the *findings* changed. `supervisor.py:~2493` calls it with only verdict
   strings.

   The original draft assumed the sibling `check_diminishing_returns` already did
   the right thing because it compares `compute_audit_finding_signature` sets. That
   assumption was false. The failed implementation showed the real convergence bug
   also involves diminishing-returns semantics and/or breaker precedence: a
   shrinking/changing finding set can still be terminated before `max_iterations`
   because the wrong breaker class fires too early. This plan must therefore cover
   the no_progress verdict-string bug, diminishing_returns false positives, and
   breaker ordering/precedence for progress-making rounds.

2. **Audit-envelope filename reuse picks a stale verdict as "latest".**
   Re-dispatching a feature reuses the `*-auditor-FNNN-iN.json` filename per
   iteration. A later run with fewer iterations leaves a higher-index stale
   envelope on disk. The finalizer / close path / closeout-memo auto-lift select
   "latest" by iteration **index**, not mtime — so a stale `i1 needs_changes` can
   outrank a fresh `i0 signed_off`, mislabeling `latest_audit_status` and refusing
   a valid finalize. Worked around twice by hand during 2026-05-30-001.

## Features

- **F001** — convergence breakers share progress-aware finding semantics.
  `check_no_progress` takes both auditor envelopes (or their findings), computes
  `compute_audit_finding_signature` sets, and trips only when the SAME blocking
  signatures persist across the threshold rounds. `check_diminishing_returns` is
  audited and corrected so shrinking/changing finding sets are treated as progress,
  not as diminishing returns. Supervisor breaker ordering/precedence is updated so
  progress-making rounds can reach `max_iterations` or signoff instead of
  terminating at round 2. Preserve the timeout-with-work carve-out.

- **F002** — audit "latest envelope" selection is mtime/supersession aware.
  The finalizer, closeout, and memo-lift resolve the latest auditor envelope by
  modification time (or an explicit supersession marker), not by iteration index
  alone — so a re-dispatch that produces a lower-index fresher verdict is read
  correctly. Optionally: re-dispatch purges/【supersedes stale higher-index
  envelopes for the feature.

- **F003** — regression suite + full orchestrate sweep.
  Red/green tests for both fixes: (a) neither no_progress nor diminishing_returns
  trips when blocking findings shrink/change across rounds while verdict stays
  `needs_changes`; (b) the correct breaker trips when the exact same blocking
  findings persist; (c) breaker precedence does not mask progress; (d) finalizer
  picks the fresher-by-mtime signed_off envelope over a stale higher-index
  needs_changes. Full existing orchestrate test sweep stays green.

## Acceptance / Return Condition

All three features `passes: true` with codex (cross-model) signoff evidence, the
full orchestrate test sweep green under raw pytest, and a demonstration that a
3+-round volley on a synthetic plan now converges to `signed_off` instead of
false-tripping `stopped_no_progress` or `stopped_cap` at round 2 while findings
are demonstrably improving.
