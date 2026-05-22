---
id: 2026-05-22-004-feat-capability-guided-setup-v2
title: Capability Guided Setup v2 — execute safe setup steps and hand off human-required work
description: |
  V2 child of the External Capability Operations Roadmap
  (2026-05-22-001). Builds on V0b setup_steps[] and V1 visual/MCP
  status surfaces by adding a governed setup runner that can print,
  execute, verify, and record automatable setup steps while clearly
  handing human-required work back to the operator. Draft until V1
  lands.
type: feat
tier: cross-cutting
status: active
date: "2026-05-22"
goal_type: new_feature
surfaces:
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
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-22-001-infra-external-capability-operations-roadmap-v0
  - 2026-05-22-002-feat-capability-status-v0
  - 2026-05-22-003-feat-capability-center-v1
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

# Capability Guided Setup v2

## Motivation

After V0b can tell an operator what is missing and V1 can show it in a
dashboard/MCP projection, the next step is guided execution: run only
the setup steps that are safe and automatable, ask the operator for the
human-required pieces, and leave evidence of what happened.

This plan is intentionally drafted now so the roadmap has an executable
future child, but it should not lock until V1 is accepted.

## Target

```yaml
target_env: dev
target_project: none
```

## Boundaries

In scope:

- `dontpanic capabilities setup <id> --print-steps`
- dry-run planning from setup_steps[]
- guarded `--automate-safe` execution for automatable steps only
- evidence record of attempted steps and remaining human-required work
- probe re-check after each attempted automatable step

Out of scope:

- storing secret values
- executing human-required steps
- unconfirmed cloud deployment mutations
- plugin marketplace or auto-installing arbitrary adapters
