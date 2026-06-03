---
id: 2026-06-02-002-fix-orchestrator-convergence-and-close-friction
title: Fix orchestrator convergence-delta + close + patch-completeness friction
status: draft
description: |
  Three engine-fix follow-ups banked while dogfooding the plan-review plan
  (2026-06-01-001, D010/D012): make the no_progress breaker findings-delta
  aware so distinct per-round findings are not mistaken for "no progress";
  make operator-finish a first-class close path for signed-off-adjacent /
  staging-blocked / operator-verified terminals (not a stopped_no_progress
  pretence); and close the patch-completeness gap where an untracked
  implementation MODULE was not surfaced alongside an untracked test.
type: fix
tier: cross-cutting
date: "2026-06-02"
goal_type: refactor
surfaces:
  - infra
agents_required:
  - claude
  - codex
human_gates:
  - pre_merge
links:
  features: ./features.json
  decisions: ./decisions.jsonl
---

# Fix orchestrator convergence-delta + close + patch-completeness friction

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal orchestration-engine fix. No external service setup.

## Why

Dogfooding the plan-review plan (`2026-06-01-001`) dispatched four features
through the harness and surfaced three repeatable frictions in the
dispatch/close/patch-completeness machinery (D010, D012):

1. **Convergence breaker too blunt.** All four features hit
   `stopped_no_progress` after exactly two rounds even though each round
   produced a *distinct* small fix — the auditor verdict stayed
   `needs_changes` while the findings genuinely changed. The convergence-bugs-v2
   carve-out (Design B) only treats a strictly-shrinking blocking-finding
   *count* as progress; it does not treat *changing finding content* as
   progress. So real progress is mistaken for none.
2. **Operator-finish is not a first-class close.** `dontpanic close
   --operator-resolved` is scoped to `stopped_no_progress` and requires
   `breaker:no_progress` to be active. It does not cover F007's terminal — a
   clean `signed_off` blocked only by patch-completeness on untracked files —
   so that close was finalized by hand. The honest terminal classes
   (signed-off-adjacent, staging-blocked, operator-verified) need a close path
   that records what actually happened instead of pretending no-progress.
3. **Patch-completeness missed an untracked module.** In F007 the gate flagged
   the untracked *test* file but not the untracked implementation *module*
   (`sizing_gate.py`) it added — a fresh clone would import-fail. The gate must
   surface both, without drowning the operator in unrelated generated/runtime
   files (the standing onboarding-v0 noise).

These are cheap-to-prevent, high-leverage: fixing #1 first makes every later
dispatch converge honestly.

## Execution model (explicit — this is a self-hosting engine fix)

- **Build operator-style with local TDD** (red test reproducing each friction →
  minimal fix → green → refactor). Each feature starts from a failing test.
- **Do NOT run the full implement→audit dispatch volley for the build.** These
  fixes repair the convergence/close/patch-completeness machinery; running them
  *through* that machinery can invalidate the result (a buggy `no_progress`
  breaker cannot be trusted to converge its own fix).
- **Run ONE batched codex audit at close** for cross-vendor assurance — a single
  paid review of the finished diff, not a multi-round self-hosted dispatch.
- **Do not touch the unrelated plan-review features** (F004/F005/F006/F008/F009
  of `2026-06-01-001`) or any other in-flight work.

## Sequencing

F001 first (it improves every subsequent dispatch's convergence), then F002,
then F003. F002 and F003 are independent of each other.

## Provenance

Banked from the plan-review dogfood: `docs/plans/2026-06-01-001-feat-plan-review-scope-validation/decisions.jsonl`
D010 (convergence-breaker + operator-finish-close follow-ups) and D012 (F007
clean-signoff blocked on patch-completeness; untracked-module gap). Related:
`docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/` (the Design B
strictly-shrinking-count carve-out this extends).
