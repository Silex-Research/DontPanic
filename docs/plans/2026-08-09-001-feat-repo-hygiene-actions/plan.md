---
id: 2026-08-09-001-feat-repo-hygiene-actions
title: Repo-hygiene ActionItems — surface between-dispatch git drift in `next`
type: feat
tier: cross-cutting
status: ready_for_audit
date: "2026-08-09"
description: >
  Wire read-only git observations (dirty tree outside a bound worktree, local
  branch ahead of remote, branch merged upstream but still local, plan whose
  features all pass while status stays non-terminal) into the ActionItem
  control-plane so `dontpanic next` and the dashboard report repo drift that
  accumulates BETWEEN dispatches. Today `git_state` is read only at
  audit/signoff time, so DontPanic is blind to a repo it is not actively
  dispatching against.
motivation: >
  A 2026-08-09 audit of the Glam repo found 763 lines of feature work sitting
  uncommitted in the working tree, a 58-commit branch never pushed, and two
  plans whose every feature had been flipped to passes:true while status stayed
  non-terminal. None of it was caused by DontPanic — the repo's last recorded
  DontPanic use was 2026-07-31 and the drift accrued 2026-08-08/09 — but none of
  it was VISIBLE to DontPanic either. The mechanisms that would have caught it
  (worktree isolation, the patch-completeness gate) only fire inside a dispatch.
  The gap is observational, not architectural: git_state.capture() already
  exists and is already strictly read-only; it is simply never called from the
  `next` / dashboard path. This plan closes that one gap and deliberately does
  not add a scheduler, a daemon, or any write path.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-06-02-001-feat-control-plane-action-spine
  - 2026-06-04-001-feat-ledger-reconciliation-operator-actions
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Repo-hygiene ActionItems

## Target

```yaml
target_env: dev
target_project: none
```

- **repo:** `DontPanic` (self-hosted; this plan modifies DontPanic itself)
- **env:** local only. No cloud project, no deploy, no network. `target_env: dev`
  is the lowest rung the enum offers; nothing in this plan contacts a service.
- **command:** `pytest` (module + integration tests), `dontpanic next`,
  `dontpanic dashboard build` for behavioral evidence.

## Problem / Motivation

`git_state.capture()` (`scripts/dontpanic_orchestrate/git_state.py`) is wired
into exactly four consumers: `audit_writer`, `patch_completeness`,
`supervisor`, and `worktree_guard`. Every one of them sits on the dispatch /
signoff path. The consequence:

- DontPanic can refuse `passes:true` on a dirty patch surface
  (`patch_completeness_gate.enforce()`, Mode 5 promotes `unstaged_dirty_state`
  from `info` to `block` for files outside the touched set) — but only if a
  dispatch reaches signoff.
- Between dispatches, and in a registered project DontPanic is not currently
  running against, it observes nothing about the working tree at all.
- It has no notion whatsoever of branch/remote relationships. Grepping every
  git verb in the orchestrator: no `git commit`, no `git push`, and `branch` is
  only ever create/delete under `BRANCH_PREFIX = "plan/"`.

`dontpanic next` is the read-only recommender operators and agents are told to
consult before mutating state. It already aggregates gate, capability,
reconcile, supervisor, architecture, integration, and upgrade sources. Repo
hygiene is the missing source.

## Proposed Approach

One new observation module, one new ActionItem provider, four new resolvability
predicates, and wiring. No new subsystem.

1. **`repo_hygiene.py`** — read-only git observations behind a single injected
   `GitRunner`. Reuses `git_state.capture()` for working-tree state; adds
   branch/remote reads via `for-each-ref` and `rev-list`. Read-only is enforced
   structurally, not by inspecting this module's source: the allowlist lives on
   the runner so transitive calls are covered (`resolve_default_base()` itself
   shells out to `git remote`), `GIT_OPTIONAL_LOCKS=0` blocks `git status`'s
   optional index refresh, and F006 proves it by hashing the whole `.git` tree
   before and after. Tree and branch observation degrade independently, so a
   detached HEAD never hides a dirty working tree.
2. **Finding classification** — a closed v0 vocabulary of seven kinds
   (see F002), with precedence and protected-branch exclusions so the tool
   cannot recommend publishing and deleting the same branch, or deleting the
   default / current / otherwise-checked-out branch. Pure function; no I/O.
3. **`provide_repo_hygiene_actions()`** in `operator_console.py`, mirroring
   `provide_architecture_actions()`: new `SOURCE_REPO_HYGIENE` registered in
   `_VALID_SOURCES` / `_SOURCE_PRIORITY`, items carry `project_name` /
   `scope` so the fleet view groups them, and `clears_when` predicates so
   `suppress_resolved` retires them once the operator acts.
4. **Plan-status drift** (F004) is a separate finding sourced from
   `plan_loader`, not from git: every feature `passes:true` while `status` is
   not terminal. This is the "no event to hang off" case — nothing fires
   between "last feature flipped" and "operator remembers to close the plan".
   Only `active` plans get the `dontpanic plan close` command, because
   `completion_gate.close_plan()` raises for every other status; the remaining
   non-terminal states get explanation-only items naming their real next step.
5. **Wiring** into `next` (repo and fleet scope) and `dashboard build`.

## Scope (in)

- New module `scripts/dontpanic_orchestrate/repo_hygiene.py`.
- New provider + source constant in `operator_console.py`.
- New predicates in `action_resolvability.py`.
- `next` and `dashboard build` wiring; fleet iteration over
  `~/.dontpanic/projects.json`.
- Tests: unit (pure classification), fixture (temp git repos), read-only
  invariant, no-secret-shape, and a fleet-scope integration test.

## Scope (out)

- **Any git write.** No commit, push, branch delete, stash, or clean — not
  behind a flag, not with `--confirm`. The module's allowlist makes this
  structurally impossible, and F006 proves it.
- **Scheduling.** No cron, daemon, watcher, or background poll. Findings are
  computed when `next` / `dashboard build` runs. A scheduled wrapper is the
  operator's choice and is out of scope here.
- **Remote API calls.** Merged-upstream detection uses local refs
  (`refs/remotes/*`) only; it never contacts GitHub. A stale `origin/main`
  yields a stale finding, and F002 requires the detail line to say so.
- **Auto-remediation of plan status.** F004 reports the drift; flipping status
  stays `dontpanic plan close`.
- Changing `patch_completeness_gate` or any existing dispatch-path behavior.
- Repairing the operator-copy register across the 27 existing INBOX event kinds.
  That is plan `2026-08-09-002-feat-decision-brief-at-gates`. This plan carries
  only D010 — its own five items are authored impact-first so they do not add to
  the debt that plan repays.

## Acceptance

1. `dontpanic next` in a repo with a dirty tree, an unpushed branch, and a
   merged-but-undeleted local branch emits exactly one ActionItem per finding,
   correctly banded, with no false positives on a clean repo.
2. Read-only is proven at the filesystem level: the `.git` tree is byte-identical
   before and after observation across every fixture including a stale-index
   repo, and every git subcommand issued by the injected runner — including
   transitive ones — is in the allowlist.
3. Every one of the seven emitted kinds declares a registered `clears_when`
   predicate, and `suppress_resolved` retires it once the condition is fixed.
4. No branch is recommended for both publishing and deletion, and the default,
   current, and other-worktree-checked-out branches never receive a cleanup
   finding.
5. Every rendered command is not merely token-valid but operationally valid:
   the plan-status `dontpanic plan close` is accepted by `close_plan` in
   dry-run for the plan it names.
6. `dashboard build --project <name>` renders hygiene items scoped to that
   project; fleet scope groups them by project without cross-project bleed.
7. No emitted field matches a secret shape (`_assert_no_secret_shapes` over the
   rendered payload, including branch names).
8. A repo with no remote, a detached HEAD, or no commits still reports its
   dirty working tree; only branch findings are absent. Nothing raises.

## Risks

- **Noise.** A repo with 28 branches (the Glam case) could emit 28 items and
  drown the real signal. Mitigated by D004: branch-derived findings collapse
  into one aggregate item above a threshold, with the per-branch list in
  `detail`.
- **False "merged" claims.** Local `refs/remotes` can lag the remote, and local
  git does not reliably record *when* a fetch last happened — tip-commit age is
  authorship time, not fetch time, and the reflog is prunable. D005 therefore
  anchors the claim to the only knowable fact: "merged into origin/main at
  `<sha>`; fetch freshness unknown". Never bare "merged", and never "as of the
  last fetch".
- **`exact_command` cannot express the fix.** `validate_command_tokens()`
  only accepts `dontpanic` invocations, so `git push` is unrenderable. D002
  resolves this — items emit `exact_command=None` with explanation-only copy
  per the D008 honest-commands rule.
- **Cost on large repos.** `for-each-ref` + one `rev-list` per branch is
  O(branches). D006 caps the branch walk and marks the result partial when the
  cap trips rather than silently truncating.
