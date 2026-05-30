---
id: 2026-05-30-002-fix-orchestrator-convergence-bugs
title: Fix orchestrator convergence + audit-envelope bugs
status: draft
tier: cross-cutting
goal_type: refactor
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
---

# DontPanic — Fix orchestrator convergence + audit-envelope bugs

title: 2026-05-30-002-fix-orchestrator-convergence-bugs

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

## Bugs (from 2026-05-30-001 D029 + D028)

1. **no_progress trips on verdict-string, not finding-set.**
   `circuit_breakers.check_no_progress` (circuit_breakers.py:~938-945) trips when
   `prior_status == current_status` (both `needs_changes`), regardless of whether
   the *findings* changed. `supervisor.py:~2493` calls it with only verdict
   strings. The sibling `check_diminishing_returns` already does the right thing
   (compares `compute_audit_finding_signature` sets, D001/D002). Net effect: every
   volley caps at 2 rounds even when the implementer is demonstrably making
   progress (findings shrinking/changing round over round). `--max-iterations N`
   is never reached because no_progress fires first in the loop.

2. **Audit-envelope filename reuse picks a stale verdict as "latest".**
   Re-dispatching a feature reuses the `*-auditor-FNNN-iN.json` filename per
   iteration. A later run with fewer iterations leaves a higher-index stale
   envelope on disk. The finalizer / close path / closeout-memo auto-lift select
   "latest" by iteration **index**, not mtime — so a stale `i1 needs_changes` can
   outrank a fresh `i0 signed_off`, mislabeling `latest_audit_status` and refusing
   a valid finalize. Worked around twice by hand during 2026-05-30-001.

## Features

- **F001** — no_progress compares finding signatures, not verdict strings.
  `check_no_progress` takes both auditor envelopes (or their findings), computes
  `compute_audit_finding_signature` sets, and trips only when the SAME signatures
  persist across the threshold rounds (mirroring `check_diminishing_returns`).
  Different findings each round = progress = no trip. Wire the supervisor call
  site to pass the envelopes. Preserve the timeout-with-work carve-out.

- **F002** — audit "latest envelope" selection is mtime/supersession aware.
  The finalizer, closeout, and memo-lift resolve the latest auditor envelope by
  modification time (or an explicit supersession marker), not by iteration index
  alone — so a re-dispatch that produces a lower-index fresher verdict is read
  correctly. Optionally: re-dispatch purges/【supersedes stale higher-index
  envelopes for the feature.

- **F003** — regression suite + full orchestrate sweep.
  Red/green tests for both fixes: (a) no_progress does NOT trip when findings
  change across rounds but verdict stays `needs_changes`; DOES trip when findings
  are identical; (b) finalizer picks the fresher-by-mtime signed_off envelope over
  a stale higher-index needs_changes. Full existing orchestrate test sweep stays
  green.

## Acceptance / Return Condition

All three features `passes: true` with codex (cross-model) signoff evidence, the
full orchestrate test sweep green under raw pytest, and a demonstration that a
3+-round volley on a synthetic plan now converges to `signed_off` instead of
false-tripping `stopped_no_progress` at round 2.
