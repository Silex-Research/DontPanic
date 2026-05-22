---
id: 2026-05-22-003-feat-capability-center-v1
title: Capability Center v1 — static dashboard review surface and read-only MCP projection
description: |
  V1 child of the External Capability Operations Roadmap
  (2026-05-22-001). Builds on V0a/V0b capability manifests and
  `dontpanic capabilities status` by adding the first visual human
  review surface in the bundled static dashboard plus a read-only MCP
  projection for agents. No Firebase dependency. No mutating setup
  runner. The operator has explicitly promoted this from future trigger
  to active roadmap work.
type: feat
tier: cross-cutting
status: active
date: "2026-05-22"
goal_type: new_feature
surfaces:
  - infra
  - ux
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  no_progress_threshold: 2
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-22-001-infra-external-capability-operations-roadmap-v0
  - 2026-05-21-001-feat-capability-manifest-consumers-v0
  - 2026-05-22-002-feat-capability-status-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  objective_contract: ./objective_contract.json
orchestration:
  parent_plan_id: 2026-05-22-001-infra-external-capability-operations-roadmap-v0
  spawn_reason: operator_manual
  depth_limit: 3
---

# Capability Center v1

## Motivation

V0b gives humans and agents `dontpanic capabilities status` at the
terminal. The operator now wants the roadmap completed through the
orchestrator: capability status must also be visually reviewable in the
bundled dashboard and readable by agents through MCP without shelling
out.

This plan deliberately keeps the scope narrow:

- static dashboard view only; no Firebase requirement
- read-only MCP projection only; no setup mutation
- consumes the V0b JSON status/cache shape rather than inventing a new
  capability model

## Target

```yaml
target_env: dev
target_project: none
```

## Boundaries

In scope:

- dashboard Capability Center page registered in the existing static
  dashboard router
- static state file support for `capabilities-status.json`
- dashboard rendering of status, owner boundaries, missing/configured
  lists, and automatable versus human-required next actions
- read-only MCP tool returning the same status envelope as the CLI
- tests for rendering/data transformation and MCP projection

Out of scope:

- Firebase realtime dashboard deployment
- mutating setup actions
- secret storage or display
- new capability schema fields
- changing V0b status semantics
