---
id: 2026-06-10-002-feat-worktree-isolation-v0
title: Worktree Isolation v0 — per-plan git worktrees with binding, refusal, visibility, and safe cleanup
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
  Give every plan its own git worktree and make DontPanic worktree-aware —
  the SUBSTRATE slice (D012 split): a binding registry, a create command that
  builds the worktree from a recorded base SHA with rollback atomicity,
  gate-time binding snapshots as evidence, the canonical binding_health
  predicate + status model, and operator brief / dashboard visibility.
  Enforcement (wrong-worktree refusal + safe cleanup) ships immediately after
  in 2026-06-11-001-feat-worktree-guard-hardening. A platform primitive that
  removes shared-worktree friction before Plan D, 008, Plan B, and C+ overlap.
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

- **F001** — worktree binding registry: install-level storage at
  `$DONTPANIC_HOME/worktrees.json` (same home resolution as projects.json,
  Pydantic `extra='forbid'`, degrade-to-empty + WARN). Binding = plan_id,
  repo_root, worktree_path, branch, base_ref, owner_actor, created_at. Pure
  add/get/remove/list; refuses double-binds and path collisions.
- **F002** — gate-time binding capture: when a binding exists for the plan,
  `plan lock`, `plan audit`, `plan close`, AND the orchestrate dispatch
  (build) path record the binding snapshot (worktree_path, base_ref, branch,
  owner_actor) into the plan's audit evidence; when no binding exists,
  behavior is unchanged (additive).
- **F004** — canonical binding_health predicate + status model + list command:
  ONE exported predicate (exists ∧ is_git_worktree ∧ belongs_to_recorded_
  repo_root ∧ on_recorded_branch, probe errors = unhealthy, machine-readable
  failed-conjunct reason) consumed by the guard (F003), removal (F005), and
  the status model — never re-specified. Unhealthy bindings render with the
  reason and explicit null dirty/untracked fields; printed by
  `dontpanic plan worktree list`.
- **F006** — `dontpanic plan worktree create <plan-id>`: creates the per-plan
  worktree on a plan-derived branch at a deterministic path outside the main
  tree. The base is never the invoking checkout's HEAD implicitly: default =
  the repo's default branch resolved to a commit SHA; `--base <ref>` overrides
  explicitly; either way the resolved SHA is printed and recorded verbatim as
  base_ref. Unresolvable base refuses; failed git leaves no half-bind.
- **F007** — operator brief + dashboard visibility: the SAME worktree-status
  model rendered as an active-worktrees section in the operator brief and as
  a block in the dashboard state payload (no-secret guard), with a DOM-level
  test proving the dashboard UI actually renders branch / dirty / untracked /
  actor / broken — plus an honest empty state.

## Split (D012)

Enforcement — the wrong-worktree refusal (formerly F003) and safe cleanup
(formerly F005) — moved wholesale to plan
`2026-06-11-001-feat-worktree-guard-hardening` after eight sufficiency rounds
(100% clearance each) kept finding real adversarial holes in that threat model
one conjunct at a time. v0 ships the substrate: registry, gate-time snapshots,
the canonical binding_health predicate + status model, create, and
visibility. The hardening plan consumes binding_health and ships refusal +
removal immediately after, behind one holistic design pass.

## Non-goals (out of scope for v0)

- Automatic conflict resolution.
- Multi-machine coordination.
- Agent leases/claims (owner_actor is informational, not a lock).
- Background branch rebasing.
- Deleting dirty worktrees (no `--force` removal path at all in v0).
- Fully parallel orchestration.

## Decisions
See `decisions.jsonl`.
