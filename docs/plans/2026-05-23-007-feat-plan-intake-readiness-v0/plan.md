---
id: 2026-05-23-007-feat-plan-intake-readiness-v0
title: Plan intake and readiness v0
description: |
  Executable child of the Planning Intelligence roadmap. Adds the first
  read-only planning surfaces: roadmap-vs-plan guidance, a parallel-readiness
  recommender, and a release/documentation impact checklist so operators and
  agents can decide what to dispatch and what user-facing surfaces must be
  updated.
type: feat
tier: cross-cutting
status: active
date: "2026-05-23"
goal_type: new_feature
surfaces:
  - infra
  - ux
  - docs
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  no_progress_threshold: 2
  wall_clock_hours: 8
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-23-006-infra-planning-intelligence-roadmap-v0
  - 2026-05-23-005-feat-dashboard-project-selector-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  objective_contract: ./objective_contract.json
orchestration:
  parent_plan_id: 2026-05-23-006-infra-planning-intelligence-roadmap-v0
  spawn_reason: operator_manual
  depth_limit: 3
child_charter:
  kind: implementation
  parent_objective: Surface the first planning-intelligence primitives without adding mutating orchestration.
  parent_acceptance_item: "V0 of planning-intelligence roadmap: roadmap-vs-plan guidance, parallel readiness, and release impact."
  allowed_paths:
    - "docs/AUTHORING_PLANS.md"
    - "docs/**/*.md"
    - "CHANGELOG.md"
    - "scripts/dontpanic_orchestrate/**"
    - "scripts/dontpanic_doctor.py"
    - "claude/shared/**"
    - "docs/plans/2026-05-23-006-infra-planning-intelligence-roadmap-v0/**"
    - "docs/plans/2026-05-23-007-feat-plan-intake-readiness-v0/**"
  forbidden_decisions:
    - Do not auto-dispatch recommended work.
    - Do not add first-class roadmap schema fields in this slice.
    - Do not make release-impact warnings block plan lock.
    - Do not require a root CHANGELOG entry for private/internal-only changes.
  return_condition_summary: F001-F003 pass with docs, CLI JSON/text output, release-impact checklist, tests, and sanitization evidence.
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
---

# Plan Intake and Readiness v0

## Motivation

DontPanic already records dependencies, feature pass/fail state, plan
dependencies, capabilities, gates, active supervisors, and evidence. The
operator still has to manually infer what can run next, whether work can be
parallelized, whether an ask should be a roadmap or a child plan, and whether a
change requires public/documentation updates.

This plan ships the smallest useful planning-intelligence slice: make those
decisions visible and explainable without letting the system dispatch or mutate
state on the operator's behalf.

## Target

```yaml
target_env: dev
target_project: none
```

## Product Rules

- Recommendations are advisory and read-only.
- The command must show both "ready" and "not ready" reasons.
- JSON output is the agent handoff shape; text output is optimized for humans.
- Uncertain substrate overlap is a warning, not a hard block.
- Roadmap-vs-plan guidance must be simple enough for a new DontPanic user and
  precise enough for an agent authoring plans.
- Release-impact checks are advisory; they should catch obvious omissions
  without turning every internal change into public-release paperwork.
- Collision warnings target precision over recall in v0. The recommender should
  warn only when the signal is strong enough to be useful, and tolerate false
  negatives until real collisions provide better training examples.
- Fleet scope aggregates per-project recommendations. It does not coordinate
  cross-project dispatch or claim that projects share a scheduler.
- Known gate, breaker, or budget exhaustion state should be surfaced as a
  warning or not-ready reason when the substrate is available. If the substrate
  cannot be read, the recommender must say that instead of pretending the work
  is clear.
- Release-impact advice has two inputs: draft-time plan intent
  (`surfaces`, `allowed_paths`, and feature step path tokens) and lock-time git
  diff when available. Draft-time advice is broad; lock-time advice is more
  precise.

## Fleet Semantics

`dontpanic next --scope repo` analyzes one repo/plans root.

`dontpanic next --scope fleet` reads the project registry shipped by
`2026-05-23-005`, runs the same repo-scoped analyzer for each active registered
project, and returns an aggregated ranking. Fleet mode does not invent
cross-project dependency edges, does not normalize cross-version schemas beyond
best-effort loading, and does not imply that parallel work across projects is
coordinated by one process. In v0, "parallel" means "these recommendations do
not share known dependencies or strong overlap signals"; the operator still
chooses what to dispatch.

## Release Impact Rules

Primary surface: `dontpanic next` output. It is the planning-time place where an
operator or agent sees likely documentation/release obligations.

Secondary surface: plan-lock messaging may repeat the advisory when a git diff
is available. No sidecar is required in v0.

Root `CHANGELOG.md` is required or strongly suggested for public/product-facing
changes, including:

- README or public docs pages
- getting started, onboarding, `init`, or `doctor` behavior
- dashboard UX, dashboard state shapes, or visible operator console behavior
- CLI commands surfaced to operators
- capability manifests or setup guidance
- public metadata, repo description, social preview, or discoverability assets

`claude/shared/CHANGELOG.md` is sufficient for agent-conventions/schema changes
that do not alter DontPanic's public/product behavior. Internal runtime changes,
test fixtures, evidence files, and plan ledger updates usually do not require a
root changelog entry unless they change a public workflow.

## Out Of Scope

- Automatic dispatch or scheduling.
- Dashboard Decisions panel.
- UX design artifact schema.
- Visual regression or journey coverage analyzer.
- First-class `plan_kind` schema changes.
- Multi-stakeholder approval workflows.
- First-class schema enforcement for investigations or design/product specs;
  F001 documents those distinctions as guidance only.
