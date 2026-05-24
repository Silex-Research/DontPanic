---
id: 2026-05-24-002-feat-dashboard-architecture-explorer-v1
title: Dashboard architecture explorer v1
description: |
  Executable V1 child of the Dashboard Platform Roadmap. Adds a first-class
  Architecture tab to the local dashboard as an interactive graph/explorer over
  DontPanic's existing architecture.json substrate. The target experience is a
  Roundtable-style flow map: swimlane-based system areas, selectable user or
  operational flows, highlighted path edges, numbered steps, right-side
  flow/step inspector, freshness/provenance, and command-emitter regen.
type: feat
tier: cross-cutting
status: active
date: "2026-05-24"
goal_type: new_feature
surfaces:
  - ux
  - docs
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
  wall_clock_hours: 10
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-24-003-infra-dashboard-platform-roadmap-v1
  - 2026-05-19-004-feat-architecture-map-with-drift-v0
  - 2026-05-23-003-infra-visual-operating-console-roadmap-v0
  - 2026-05-23-005-feat-dashboard-project-selector-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  objective_contract: ./objective_contract.json
orchestration:
  parent_plan_id: 2026-05-24-003-infra-dashboard-platform-roadmap-v1
  spawn_reason: operator_manual
  depth_limit: 3
child_charter:
  kind: implementation
  parent_objective: Deliver a first-class interactive Architecture tab in the local dashboard.
  parent_acceptance_item: "V1 Architecture Explorer: swimlane flow map, selectable flows, highlighted paths, step inspector, search/filter, provenance, and regen command."
  allowed_paths:
    - "dashboard/**"
    - "scripts/dontpanic_orchestrate/**"
    - "docs/design/dashboard-architecture-explorer-v1/**"
    - "docs/plans/2026-05-24-002-feat-dashboard-architecture-explorer-v1/**"
    - "docs/architecture/**"
    - "CHANGELOG.md"
    - "README.md"
  forbidden_decisions:
    - Do not replace the static dashboard with a framework rewrite.
    - Do not add CDN runtime dependencies.
    - Do not auto-regenerate or write architecture artifacts on dashboard open.
    - Do not hardcode demo flows disconnected from local architecture state.
    - Do not hide technical identifiers from detail/provenance views.
    - F001 dispatch must not modify dashboard/** files. Dashboard shell, route, and CSS edits belong to F002-F005 and must wait for the IA shell cleanup from 2026-05-24-001 F002 to land first, unless the worker explicitly reconciles against the cleaned shell before merge.
  return_condition_summary: Architecture tab ships with view-state cache, swimlane flow map, selected-flow path highlighting, step inspector, project/fleet behavior, screenshots, tests, docs, and sanitization evidence.
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
---

# Dashboard Architecture Explorer v1

## Motivation

DontPanic already generates `docs/architecture/architecture.json` and
`docs/architecture/architecture.html`. The current dashboard can surface stale
architecture as an action item, but it does not give humans or agents a visual
architecture workspace.

The requested target is not just an iframe of the existing static HTML. It is
an interactive flow explorer similar in spirit to the provided Roundtable-style
screenshots: architecture areas are arranged into labeled swimlanes, a user or
operational flow is selected from a right-side list, the relevant nodes and
edges light up, numbered step markers trace the path, and a step inspector
explains what happens at each hop.

This plan builds the full local dashboard Architecture tab on top of the
existing architecture substrate. It owns the endstate for this surface, not a
placeholder: the operator should be able to open the tab, understand the system
shape, select real flows, watch paths light up, inspect step details, search,
filter, understand stale/missing states, and copy the regen command. It remains
read-only and command-emitter only.

## Endstate

When this plan is complete, `dontpanic dashboard serve` exposes an
Architecture tab that works like the reference video:

- the main canvas is a deterministic swimlane system map
- each lane represents a meaningful system area
- nodes are typed and visually keyed by a persistent legend
- the right rail lists real flows for the selected project
- selecting a flow highlights its path with bright edges and numbered markers
- unrelated nodes/edges dim but remain visible for context
- the step inspector explains each hop in plain language and technical detail
- clear selection returns to neutral map
- search, filters, hover labels, click detail, and zoom/pan work
- stale or missing maps render honest empty states and exact regen commands
- agents can consume the same architecture view-state JSON without scraping HTML

## Target

```yaml
target_env: dev
target_project: none
```

## Product Model

Primary user question:

```text
How is this system put together, what changed, and where should I look first?
```

Primary UI language:

- `Architecture`
- `System Map`
- `Flows`
- `Modules`
- `Relationships`
- `Steps`
- `Changed Areas`
- `High-Coupling Areas`
- `Plans Touching This`
- `Regenerate Map`

Technical details stay available:

- source path
- module import path
- plan_id
- capability_id
- edge type
- fingerprint
- generated_at
- architecture.json path

## Interaction Requirements

V1 Architecture tab must provide:

- swimlane architecture map from `architecture.json`
- selectable flow list sourced from derived or authored flow definitions
- highlighted active flow path across nodes and edges
- numbered step markers matching the selected flow
- right-side flow panel with a selectable flow list, clear-selection action,
  and a scrollable step inspector
- step rows with plain-language explanation, technical source, and related
  commands/evidence where available
- persistent legend for node/source categories
- non-selected nodes and edges dimmed, not hidden, when a flow is selected
- search by module, plan, file path, capability, or surface
- filters for modules, plans, capabilities, edges, and changed/stale areas
- hover detail for quick labels
- click-to-detail side panel with source/provenance and related plans
- zoom/pan or equivalent large-graph navigation
- freshness banner when architecture state is stale or missing
- exact `dontpanic architecture regen --with-html` command emission
- project selector awareness: selected project architecture if available;
  clear empty state when a project has no architecture artifact

## Boundaries

In scope:

- dashboard Architecture nav/page
- architecture view model derived from existing `architecture.json`
- flow-aware architecture view model with nodes, edges, lanes, flows, and steps
- interactive flow map/explorer in the existing static dashboard
- project-scoped architecture artifact resolution
- freshness and missing-data states
- command-emitter regen action
- tests and screenshots for graph, filters, details, empty state, and no-secret
  rendering

Out of scope:

- rewriting the architecture crawler
- adding hidden auto-regen on dashboard open
- writing architecture files into target repos by default
- Firebase realtime architecture sharing
- editing architecture from the graph
- dependency-risk scoring beyond simple derived insights
- a separate hosted architecture product
- waiting for the full dashboard value-language IA plan to close before
  building view-model substrate

## V1 Sequencing

This plan is designed to run without blocking the whole dashboard roadmap, but
not every feature is equally parallel-safe:

- F001 may run in parallel with
  `2026-05-24-001-feat-dashboard-value-language-ia-v0` because it owns
  architecture view-model, flow definition, cache, and validation substrate.
- F002-F005 should integrate after the IA plan's shell/nav cleanup lands, or
  the worker must explicitly reconcile route/nav/CSS changes against the
  cleaned V1 shell before merge.
- If F002-F005 dispatch before IA shell cleanup fully lands, the Architecture
  worker must adopt the value-language copy map from
  `2026-05-24-001-feat-dashboard-value-language-ia-v0` verbatim rather than
  inventing new primary labels. The IA plan's copy map is canonical.
- Do not let Architecture restore old labels such as `Capabilities` as primary
  nav copy or reintroduce Jarvis-era branding.

## Implementation Strategy

Use the existing static dashboard runtime. Do not introduce React as a runtime
dependency. A graph helper may be implemented with vanilla SVG/DOM, canvas, or a
small vendored/local library if the plan records why that dependency is worth
the extra surface. No CDN dependency.

The first implementation should prefer a deterministic swimlane layout over a
simulation that changes every render. Operators need repeatable maps for review
and screenshots, and flow selection should highlight the same path every time.

If `architecture.json` does not yet contain explicit flows, V1 may derive a
small set of flows from plans, capabilities, CLI surfaces, and imports. Authored
flow definitions can be added later, but the dashboard must not hardcode demo
flows that do not correspond to local architecture state.

## Capability Map

The desired endstate requires more than a visual tab. These capabilities must
ship together for the surface to be real:

| Capability | Current substrate | Gap to close in this plan |
|---|---|---|
| Architecture inventory | `docs/architecture/architecture.json` has modules, plans, schemas, fingerprint | Build dashboard view-state with lanes, node categories, edges, flows, steps, filters, and insights |
| Flow definitions | Not present in `architecture.json` | Add `docs/architecture/flows.json` or equivalent authored/derived flow input, validated and tied to architecture nodes/edges |
| Lane model | Not present | Derive deterministic lanes from module path/category and authored metadata |
| Node model | Partial modules/plans/schemas | Normalize modules, plans, schemas, capabilities, dashboard pages, CLI commands, and external services where data exists |
| Edge model | Partial imports only | Normalize imports, plan relationships, capability links, command-to-module links where derivable |
| Flow selection | Not present | Right-side flow list with selected state and clear-selection |
| Path highlighting | Not present | Highlight active flow nodes/edges; dim non-selected map content |
| Numbered steps | Not present | Steps reference stable node/edge IDs and render markers plus scrollable inspector |
| Detail inspector | Static HTML only | Click/hover detail panel with plain explanation, technical metadata, related plans, provenance |
| Freshness/missing state | `architecture status` and dashboard action item exist | Architecture tab stale/missing banner and exact regen command |
| Project/fleet behavior | Project selector cache exists | Per-project map; All Projects shows project-level architecture cards/status, not merged repo graph |
| Agent handoff | None for architecture tab | Stable architecture view-state JSON for agents and tests |
| Verification | Existing architecture HTML tests | View-model tests, dashboard interaction tests, Playwright screenshots, sanitization, responsive/accessibility evidence |

This table is the build contract. If a worker cannot implement one row from
existing substrate, they must either add the missing view-model input in this
plan or record a blocking D-entry before continuing.

## Flow Definition Contract

V1 introduces a small architecture-flow input so the dashboard can show real
flows instead of guessing from imports alone:

```json
{
  "schema_version": "1.0",
  "flows": [
    {
      "id": "dashboard-open",
      "title": "Open local dashboard",
      "summary": "Operator opens the dashboard and views current action state.",
      "category": "operator",
      "steps": [
        {
          "id": "run-dashboard-serve",
          "title": "Start dashboard",
          "node_ref": "command:dontpanic-dashboard-serve",
          "edge_ref": "calls:scripts/dontpanic_orchestrate/dashboard.py"
        }
      ]
    }
  ]
}
```

Rules:

- flows must reference stable node IDs or source paths present in the
  architecture view model
- missing references are validation warnings in V1, not silent omissions
- no demo flows are allowed
- derived flows are allowed only when every step references real local nodes or
  edges
- authored flow input may live at `docs/architecture/flows.json` and is
  consumed by dashboard build, not by the crawler

## Design Asset Intake

Claude Design assets for this plan belong under:

```text
docs/design/dashboard-architecture-explorer-v1/
```

Requested design assets:

- Architecture tab shell
- swimlane map canvas / SVG explorer
- node, edge, cluster, search, filter, and detail-panel components
- flow list, highlighted path, numbered step marker, and step inspector
  components
- dimmed-state, selected-state, active-step, and clear-selection states
- stale/missing architecture empty states
- command-emitter regen pattern
- project/fleet architecture treatment
- mobile/desktop responsive guidance
