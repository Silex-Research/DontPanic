---
id: 2026-06-11-001-feat-worktree-guard-hardening
title: Worktree guard hardening — wrong-worktree refusal + safe cleanup, split from isolation v0
type: feat
tier: cross-cutting
status: draft
date: "2026-06-11"
goal_type: new_feature
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  objective_contract: ./objective_contract.json
description: >
  The enforcement half of worktree isolation, split out of plan
  2026-06-10-002 at its D012 per operator direction after eight sufficiency
  rounds (100% clearance each) kept surfacing real adversarial holes in the
  guard/cleanup threat model one conjunct at a time. This plan owns the
  wrong-worktree refusal across every plan-mutating entry point and the
  health-gated, audit-first, no-force removal — both built on the canonical
  binding_health predicate that v0 ships. DESIGN PASS REQUIRED BEFORE LOCK:
  pin the complete threat model up front (see Design inputs) instead of
  re-entering one-hole-per-round refinement.
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

Eight v0 lock rounds proved two things: the gate works (every high was a real
hole — fail-open corrupt registry, fail-closed completeness for create/remove,
swapped-repo-at-same-path, create rollback, audit-first removal, cleanup
contract semantics), and the guard/cleanup surface needs a holistic
threat-model design pass, not incremental acceptance edits. v0 ships the
substrate (registry, create, snapshots, visibility, the binding_health
predicate); this plan ships enforcement on top of it.

## Design inputs (resolve in the pre-lock design pass — carried from v0 rounds)

- **Open operator decision (v0 round-8 HIGH, plan_contract,
  f-330122e8396e):** does the contract's "dirty/untracked files are never
  deleted automatically" include gitignored files? Options: (a) ignored files
  do not block removal and are deleted with the worktree (regenerable by
  declaration — requires amending the contract wording); (b) any ignored
  files also block removal (strictest, but makes removal nearly always refuse
  for built projects). Pick one explicitly before lock.
- **Evidence-write durability (v0 round-8 MED, f-6d97ffb6949f):** the
  override path must not perform guarded side effects unless the override
  record AND binding snapshot are durably written first (fail closed on
  evidence-write failure).
- The complete guard threat model to pin in one pass: corrupt registry
  (fail closed), unbound passthrough (valid registry only), canonical path
  comparison (realpath both sides), binding_health conjuncts (exists /
  is_git_worktree / belongs_to_recorded_repo_root / on_recorded_branch,
  indeterminate = unhealthy), override evidence durability, no merge command
  (CLI-surface owned), create rollback + audit-first removal ordering.

## Features

- **F001** — wrong-worktree refusal: one fail-closed guard precondition for
  lock / audit / close / disposition / orchestrate dispatch, calling v0's
  canonical binding_health predicate; corrupt registry fails closed; override
  requires a reason, durably records override + binding snapshot before any
  side effect; no-merge-command CLI-surface guard.
- **F002** — safe cleanup: removal eligibility = binding_health AND clean per
  the contract semantics decided in the design pass; audit-first ordering
  (unwritable log = no removal); no force path; close never auto-removes.

## Non-goals

- Everything out of scope for v0 remains out of scope (no leases, no
  multi-machine, no auto-conflict resolution, no background rebasing, no
  deleting dirty worktrees, no parallel orchestration).
- No changes to v0's registry/create/visibility surfaces beyond consuming
  their exports.

## Decisions
See `decisions.jsonl`.
