---
id: 2026-05-23-004-feat-operator-console-v0
title: Operator console v0 — local what-now dashboard
description: |
  Executable V0 child of the Visual Operating Console Roadmap. Builds a
  local-first, operator-in-the-loop console that answers "what needs action
  now?" from gates, capability status, install reconcile drift, and active
  supervisor state. No Firebase, no architecture page, no drag/drop kanban.
type: feat
tier: cross-cutting
status: completed
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
  - 2026-05-09-003-feat-state-projection-v0
  - 2026-05-22-003-feat-capability-center-v1
  - 2026-05-23-002-feat-install-reconcile-foundation-v0
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

# Operator Console v0

## Motivation

DontPanic has a static dashboard, a capability center, architecture HTML, state
projection, install reconciliation, gate state, INBOX events, and active
supervisor records. A human operator still has to know where each artifact
lives. This plan makes the first cohesive visual operating console.

The V0 audience is intentionally narrow: the operator currently driving the
loop. The console must answer:

- Which gates need approval?
- Which capabilities are blocking or need setup?
- Has this install drifted since baseline?
- Are any supervisors active or stuck?
- What exact command should I run next?

## Target

```yaml
target_env: dev
target_project: none
```

## Boundaries

In scope:

- shared status taxonomy and action-provider model
- projection-to-view adapter repair for existing dashboard pages used in V0
- `dontpanic dashboard build|open|serve`
- local cache file for the same "what now" model agents can read
- localhost-only live server with watch/refresh
- "What Now" dashboard page/panel
- init/doctor messaging and readiness checks
- objective-contract evidence and screenshots/logs

Out of scope:

- architecture page or embedded architecture graph
- plans/features roster beyond what is needed to explain gates/actions
- read-only mission board
- drag/drop plan mutation
- Firebase realtime
- remote approve/dispatch
- hosted dashboard
