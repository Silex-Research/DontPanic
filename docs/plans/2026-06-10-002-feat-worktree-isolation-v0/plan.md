---
id: 2026-06-10-002-feat-worktree-isolation-v0
title: Worktree Isolation v0 — per-plan git worktrees with binding, refusal, visibility, and safe cleanup
type: feat
tier: cross-cutting
status: draft
date: "2026-06-10"
goal_type: new_feature
description: >
  Give every plan its own git worktree and make DontPanic worktree-aware: a
  create command that builds the worktree from the correct base and records the
  binding (worktree_path, base_ref, branch, owner_actor); lock/audit/close
  capture that binding as evidence; plan-mutating commands refuse to run from
  the wrong worktree unless explicitly overridden; the operator brief and
  dashboard show active worktrees with branch, dirty status, and actor; and
  cleanup is explicit, audited, and refuses dirty/untracked state. A platform
  primitive that removes shared-worktree friction before Plan D, 008, Plan B,
  and C+ overlap.
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

The recent operational pain is the justification: long-lived branches, plan
drafts on different bases, cleanup commits, stale stashes, untracked Finder
duplicates, merge/close rituals, and multiple agents/sessions touching the same
repo state. The very session that drafted this plan checked out a different
branch mid-flight and watched another plan's freshly-edited artifacts revert in
the shared working tree. Plan D will touch UI, generated state, architecture
model assumptions, and tests — exactly the work where shared-worktree friction
gets expensive. v0 is deliberately tight: isolation + honesty about who is
where, nothing clever.

## Design anchors (existing seams)

- Registry pattern: `projects_registry.py` (`~/.dontpanic/projects.json` via
  `global_config`, Pydantic v2 `extra='forbid'`, invalid file degrades to
  empty + WARN). The worktree registry mirrors it at
  `$DONTPANIC_HOME/worktrees.json`.
- Plan-mutating seam: `cli.py` `plan lock | audit | close | disposition`
  (the sufficiency/completion gates) — the refusal helper wraps these.
- Visibility: one model, many renderers (the operator-triage house pattern) —
  a single worktree-status model feeds `plan worktree list`, the operator
  brief, and the dashboard payload via `state_projection`.
- Actor identity: no first-class actor exists yet; v0 records
  `owner_actor` as `$DONTPANIC_ACTOR` if set, else `user@host`. Leases/claims
  are explicitly out of scope.

## Features

- **F001** — worktree registry + create command: `dontpanic plan worktree
  create <plan-id>` creates a git worktree for the plan from an explicit,
  recorded base (default: the repo's default branch tip) on a plan-derived
  branch, at a deterministic path outside the main working tree, and records
  the binding (plan_id, repo_root, worktree_path, branch, base_ref,
  owner_actor, created_at) in `$DONTPANIC_HOME/worktrees.json`. Refuses to
  double-bind a plan or reuse an occupied path.
- **F002** — gate-time binding capture: when a binding exists for the plan,
  `plan lock`, `plan audit`, and `plan close` record the binding snapshot
  (worktree_path, base_ref, branch, owner_actor) into the plan's audit
  evidence; when no binding exists, behavior is unchanged (additive).
- **F003** — wrong-worktree refusal: plan-mutating commands (`plan lock`,
  `plan close`, `plan disposition`) refuse when invoked from a working tree
  that is not the plan's bound worktree, naming both paths; an explicit
  override flag with a reason proceeds and the override is recorded. No
  binding → no refusal (backward compatible).
- **F004** — worktree visibility: one worktree-status model (per binding:
  plan_id, branch, dirty flag from `git status --porcelain`, untracked count,
  owner_actor, path) rendered in three places — `dontpanic plan worktree
  list`, the operator brief, and the dashboard state payload — passing the
  no-secret guard; missing/externally-deleted worktrees render as broken
  bindings, not silently dropped.
- **F005** — explicit, audited, safe cleanup: `dontpanic plan worktree
  remove <plan-id>` removes the worktree and binding ONLY when the tree is
  clean (no modified, staged, or untracked files) and records an audit entry
  (who, when, path, branch); a dirty tree refuses with the file list and no
  force path exists in v0; plan close NEVER auto-removes — it may only print
  the cleanup command.

## Non-goals (out of scope for v0)

- Automatic conflict resolution.
- Multi-machine coordination.
- Agent leases/claims (owner_actor is informational, not a lock).
- Background branch rebasing.
- Deleting dirty worktrees (no `--force` removal path at all in v0).
- Fully parallel orchestration.

## Decisions
See `decisions.jsonl`.
