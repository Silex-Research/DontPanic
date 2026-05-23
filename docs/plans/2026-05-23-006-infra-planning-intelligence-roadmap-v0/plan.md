---
id: 2026-05-23-006-infra-planning-intelligence-roadmap-v0
title: Planning intelligence roadmap v0
description: |
  Tracking parent for moving DontPanic from operator-manual planning
  discipline toward machine-assisted planning intelligence. The roadmap
  covers ask classification, roadmap-vs-plan guidance, parallel-readiness
  analysis, operator decision surfacing, release/documentation impact checks,
  and later UX-aware design and journey verification.
type: infra
tier: architectural
status: draft
date: "2026-05-23"
goal_type: infra
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
  - 2026-05-23-003-infra-visual-operating-console-roadmap-v0
  - 2026-05-23-005-feat-dashboard-project-selector-v0
links:
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
---

# Planning Intelligence Roadmap v0

## Strategic Outcome

DontPanic should help an operator or agent answer four planning questions before
expensive implementation starts:

1. **What kind of ask is this?** Is it a one-plan implementation slice, a
   tracking roadmap with child plans, an investigation, a design/product
   specification, or an operator setup task?
2. **What can run now?** Which features or child plans are dependency-clear and
   safe to dispatch in parallel?
3. **What decisions need a human?** Which gates, scope changes, blockers, or
   design choices are waiting, and what context does the operator need to
   approve or reject them?
4. **What user-facing surfaces must change?** Does the work require README,
   onboarding, architecture map, dashboard, CHANGELOG, design artifacts, or
   user-journey evidence updates?

Today, most of that reasoning lives in the operator's head. The data exists in
plans, features, dependencies, gates, capability declarations, active
supervisors, and evidence refs. The missing layer is a small set of read-only
planning projections that make the next safe action obvious.

## Roadmap vs Plan Guidance

DontPanic should teach this distinction directly in authoring and intake
surfaces:

Use a **plan** when:

- the work has one concrete outcome;
- acceptance can be checked in one bounded feature set;
- dependencies are known and mostly sequential;
- a single implementation/audit loop can reasonably close it;
- future work is non-essential or can be a follow-up.

Use a **roadmap** when:

- the ask describes a strategic outcome across multiple releases;
- some milestones are trigger-gated or demand-gated;
- multiple child plans can ship independently;
- the work spans different audiences or surfaces;
- locking all features today would overfit an uncertain future.

Roadmaps are tracking parents. Child plans are dispatchable work. Roadmaps must
name the future state, the child-plan sequence, trigger conditions, and explicit
non-goals. They should not pretend future milestones are ready to dispatch just
because they are named.

## Milestones

### V0 — Plan Intake, Parallel Readiness, and Release Impact

Executable child: `2026-05-23-007-feat-plan-intake-readiness-v0`

Scope:

- Add user-facing roadmap-vs-plan guidance to authoring docs and intake
  templates.
- Add a read-only `dontpanic next` recommender that identifies dependency-clear
  features/child plans and explains why they are or are not parallel-ready.
- Add a release/documentation impact checklist so schema, CLI, onboarding,
  dashboard, architecture, README, and changelog updates are not left to memory.
- Produce JSON output for agents and text output for humans.

Status: lockable after operator review.

### V1 — Operator Decision Queue

Future child.

Scope:

- `dontpanic decisions pending|archive` aggregates pending gates, breaker
  pauses, scope-change requests, and operator setup decisions across active
  plans/projects.
- The operator console renders the same queue with evidence links and exact
  approve/reject commands.
- Approvals can require a short reason that is appended to the relevant
  `decisions.jsonl`.

Trigger:

- V0 `dontpanic next` is in use and at least two operator decisions are missed,
  duplicated, or hard to reconstruct from existing INBOX/gate surfaces.

### V2 — UX-Aware Planning and Journey Coverage

Future child.

Scope:

- Add typed `design_artifacts[]` and per-feature design evidence conventions.
- Treat design-version changes as scope-change events.
- Add advisory journey-coverage analysis mapping
  `objective_contract.user_journeys[].acceptance_signals[]` to tests and
  screenshots.
- Add optional visual/a11y/e2e evidence slots without requiring every project
  to use the same frontend stack.

Trigger:

- DontPanic is used against at least one non-DontPanic product repo with
  meaningful UI work, and visual/design acceptance is ambiguous during audit.

### V3 — First-Class Meta-Planning Schema

Future child.

Scope:

- Add first-class schema support for `plan_kind: implementation|roadmap`,
  milestone features, trigger conditions, and dispatch refusal for future
  milestones.
- Add `dontpanic plan new --kind roadmap` once the convention has proven
  useful across multiple roadmaps.

Trigger:

- At least three roadmap-style tracking parents are active or recently closed
  and the lack of schema-level roadmap semantics causes a real dispatch or
  review failure.

## Architecture Rules

1. Planning intelligence is read-only by default. It recommends; it does not
   auto-dispatch.
2. Parallel-readiness must explain both positive and negative recommendations.
3. Substrate collision checks start heuristic and conservative; unclear overlap
   is advisory, not a hard block.
4. Roadmaps remain tracking parents until meta-planning is first-class in the
   schema.
5. UX/design enforcement starts advisory. Hard blocking waits for repeated
   evidence that advisory warnings are ignored.
6. Changelog/release impact is broader than `claude/shared/CHANGELOG.md`;
   public product changes may require root release notes, README, onboarding,
   dashboard, architecture, and social/discoverability updates.

## Out Of Scope For V0

- Automatic dispatch.
- Full graph optimizer or scheduler.
- Git merge conflict prediction.
- Inline dashboard mutation of decisions.
- New plan schema fields for roadmap milestones.
- Visual regression or image-diff enforcement.
- Multi-stakeholder approval workflows.
