---
id: 2026-06-11-001-feat-worktree-guard-hardening
title: Worktree guard hardening — wrong-worktree refusal + safe cleanup, split from isolation v0
type: feat
tier: cross-cutting
status: completed
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
  binding_health predicate that v0 ships. Design pass COMPLETE (D003):
  the threat model and the three policy calls are pinned up front.
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

## Decided policies (D003 — the pre-lock design pass, operator 2026-06-11)

- **Cleanup / gitignored files:** PRESERVED by default — they are still local
  state. Removal is explicit, audited, and REFUSES unless the worktree is
  clean under the applied policy: any gitignored content present blocks
  removal with the ignored paths reported explicitly. Deleting ignored
  content is a future explicit audited cleanup command, out of this plan.
- **Operator-local config (the D011 environments_json friction):** default is
  DECLARE missing/divergent config explicitly — never silent divergence.
  Opt-in copy of a small declared-safe allowlist at create time. NO live
  symlinks in v1 (a file would have to be explicitly marked safe and
  non-secret, and none are).
- **Evidence durability:** an override proceeds only after the override
  record AND the binding snapshot are durably written; either write failing
  refuses the guarded command (never proceed un-evidenced).
- **The complete guard threat model, pinned:** corrupt registry fails closed;
  unbound passthrough only under a valid registry; canonical (realpath)
  path comparison both sides; the v0 binding_health conjuncts called, never
  re-specified (exists / is_git_worktree / belongs_to_recorded_repo_root /
  on_recorded_branch, indeterminate = unhealthy); override evidence
  durability as above; no merge command (CLI-surface owned by F001);
  audit-first removal ordering (unwritable audit log = no removal).

## Features

- **F001** — wrong-worktree refusal: one fail-closed guard precondition for
  lock / audit / close / disposition / orchestrate dispatch, calling v0's
  canonical binding_health predicate; corrupt registry fails closed; override
  requires a reason, durably records override + binding snapshot before any
  side effect; no-merge-command CLI-surface guard.
- **F002** — safe cleanup: removal eligibility = binding_health AND clean
  AND no gitignored content present (preserved by default per D003, ignored
  paths reported); audit-first ordering (unwritable log = no removal); no
  force path; close never auto-removes.
- **F003** — operator-local config policy: declare-missing/divergent
  explicitly at create (default), opt-in allowlist copy, no symlinks in v1.

## Non-goals

- Everything out of scope for v0 remains out of scope (no leases, no
  multi-machine, no auto-conflict resolution, no background rebasing, no
  deleting dirty worktrees, no parallel orchestration).
- No changes to v0's registry/create/visibility surfaces beyond consuming
  their exports.

## Decisions
See `decisions.jsonl`.
