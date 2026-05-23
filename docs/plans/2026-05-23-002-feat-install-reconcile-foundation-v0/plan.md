---
id: 2026-05-23-002-feat-install-reconcile-foundation-v0
title: Install reconcile foundation v0 — install snapshot and capability drift check
description: |
  Executable child of the install lifecycle reconciliation roadmap. Builds the
  local install snapshot anchor and the first reconciliation consumer:
  capability manifest/setup-step drift. No dashboard, no security audit, no
  automatic package upgrade.
type: feat
tier: cross-cutting
status: active
date: "2026-05-23"
goal_type: infra
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
  wall_clock_hours: 6
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-23-001-infra-install-lifecycle-reconciliation-roadmap-v0
  - 2026-05-22-002-feat-capability-status-v0
  - 2026-05-22-003-feat-capability-center-v1
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
orchestration:
  parent_plan_id: 2026-05-23-001-infra-install-lifecycle-reconciliation-roadmap-v0
  spawn_reason: operator_manual
  depth_limit: 3
---

# Install Reconcile Foundation v0

## Motivation

`dontpanic init` bootstraps a workstation. `dontpanic doctor` checks the
current environment. `dontpanic capabilities status` explains current
external integration readiness. None of them answers whether an already
onboarded install has drifted from what the current DontPanic version expects.

This plan adds that missing anchor and the first useful comparison.

## Target

```yaml
target_env: dev
target_project: none
```

## Boundaries

In scope:

- operator-local `~/.dontpanic/install-snapshot.json`
- snapshot creation from `dontpanic init` and `dontpanic reconcile baseline`
- `dontpanic reconcile check --area=capabilities`
- text and JSON output for humans and agents
- stale/missing `~/.dontpanic/capabilities-status.json` detection
- tests and sanitization

Out of scope:

- dashboard rendering of reconcile output
- long-running dashboard server
- package manager upgrades
- Firebase setup or Firebase realtime adapter work
- security audit mode
- automatic mutation without explicit confirmation
