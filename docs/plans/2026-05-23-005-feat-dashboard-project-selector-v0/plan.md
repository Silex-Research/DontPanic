---
id: 2026-05-23-005-feat-dashboard-project-selector-v0
title: Dashboard project selector v0 — multi-repo operating console
description: |
  Executable follow-on to the Visual Operating Console roadmap. Adds the
  substrate and first UI for using one local DontPanic dashboard across many
  registered repos, apps, or platforms without making Firebase or remote
  mutation part of the default experience.
type: feat
tier: cross-cutting
status: draft
date: "2026-05-23"
goal_type: new_feature
surfaces:
  - ux
  - infra
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
  - 2026-05-23-004-feat-operator-console-v0
  - 2026-05-23-002-feat-install-reconcile-foundation-v0
  - 2026-05-22-002-feat-capability-status-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  objective_contract: ./objective_contract.json
orchestration:
  parent_plan_id: 2026-05-23-003-infra-visual-operating-console-roadmap-v0
  spawn_reason: operator_manual
  depth_limit: 3
---

# Dashboard Project Selector v0

## Motivation

DontPanic is meant to operate the systems a user builds, not only the
DontPanic repository itself. A real operator may use one DontPanic install for
multiple repos, apps, and platforms: a mobile app, a backend, a schema repo, a
dashboard repo, and DontPanic itself.

The current local dashboard can answer "what needs action now?" for the current
repository, but it does not model project selection. Without that model, the
dashboard cannot cleanly distinguish:

- global DontPanic configuration and installed capabilities
- project-specific plans, gates, architecture, evidence, and warnings
- fleet-level summaries across all registered projects

This plan makes multi-repo operation explicit while preserving the V0 operator
console invariant: the dashboard is a local projection of governed state and a
command emitter, not a separate app database and not a mutation surface.

## Target

```yaml
target_env: dev
target_project: none
```

## Product Model

V0 adds one selector:

```text
Project: [ All Projects v ]
```

The selector can show:

- `All Projects` for fleet-level summaries
- individual registered projects by stable ID and display name
- an `Add project` affordance that emits the exact `dontpanic projects add`
  command instead of mutating state from the dashboard

Every visible surface must declare its scope:

- `Scope: Global` for DontPanic install configuration and capability install
  state
- `Scope: Project` for plan, gate, architecture, evidence, and repo warnings
- `Scope: Fleet` for cross-project summaries and grouped action lists

## Boundaries

In scope:

- registered project discovery and stable project IDs
- per-project dashboard state cache under the operator's DontPanic home
- fleet summary state for `All Projects`
- `dontpanic dashboard build|serve --project <id>|all`
- project selector UI and scope labels
- What Now and Status behavior for Fleet vs Project selection
- build warning persistence so skipped/malformed project state is visible in
  the dashboard, not only terminal stderr
- documentation and tests for external repo operation

Out of scope:

- Firebase realtime
- remote approve, dispatch, or mutation
- inline configuration editing
- architecture tab implementation
- Plans, Agents, Evidence, or Configuration tab productization
- drag/drop project or plan state transitions
- hosted control plane
- packaging a separate dashboard app per repo

## Data Shape

V0 uses one global registry and one global dashboard cache:

```text
~/.dontpanic/projects.json
~/.dontpanic/dashboard/
  fleet-summary.json
  projects/
    <project-id>/
      state-snapshot.json
      what-now.json
      capabilities-required.json
      architecture-status.json
      build-warnings.json
```

Project IDs are stable slugs. Paths are mutable implementation detail. Target
repos are not required to receive generated dashboard files.

## Command Shape

```bash
dontpanic projects add /path/to/app --id spindine
dontpanic projects list
dontpanic dashboard build --project all
dontpanic dashboard build --project spindine
dontpanic dashboard serve
dontpanic dashboard serve --project spindine
```

`serve` defaults to `all` when more than one project is registered, and to the
current project when exactly one project or an unregistered current repo is in
use.

## Non-Goals

This plan does not decide whether future V1/V2 dashboard tabs should exist. It
only gives those tabs a clean substrate: a selected project context and a
fleet/global/project scope model. Future tabs must still justify their own
audience and acceptance criteria before implementation.
