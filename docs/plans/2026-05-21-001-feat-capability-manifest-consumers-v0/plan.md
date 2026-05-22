---
id: 2026-05-21-001-feat-capability-manifest-consumers-v0
title: Capability manifest consumers v0 — make doctor, adapters, and plan refs read the manifest convention
description: |
  ADR-001 establishes `capabilities/*.json` as the source-of-truth
  declaration for optional/external integrations. This plan gives that
  convention teeth without adding a new product surface: load and
  validate manifests, bind existing doctor/adapter/external_refs surfaces
  to capability IDs, and emit advisory required-capabilities evidence at
  plan lock. No `dontpanic capabilities` CLI in v0.
type: feat
tier: cross-cutting
status: completed
date: "2026-05-21"
goal_type: infra
surfaces:
  - infra
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
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-20-001-infra-external-integrations-bridge-v0
  - 2026-05-09-004-feat-firebase-dashboard-adapter-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
---

# Capability Manifest Consumers v0

## Motivation

ADR-001 and `capabilities/*.json` name the external capability model:
verification, local registration, category abstraction, usage references,
owner boundaries, and mutation boundaries all point at one manifest.

The first commit deliberately shipped that as documentation plus schema.
That is useful but not enforceable. This plan connects the existing
platform surfaces to the manifest convention without creating a new
registry product or CLI.

## Scope

In scope:

- manifest loader and schema validation for `capabilities/*.json`
- doctor/prereq probes carrying optional manifest IDs
- adapter registry records carrying optional `capability_id`
- `external_refs[]` validation binding PM-tool refs to capability IDs
- plan-lock advisory sidecar `evidence/required-capabilities.json`

Out of scope:

- `dontpanic capabilities list/show`
- automatic adapter installation
- plugin marketplace
- per-service setup wizards
- moving Firebase/Discord/Linear implementation code
- making missing optional capabilities block plan lock

## Sequencing Note

Active integration plans may cite capability manifests before this plan
ships. Those citations are documentation-only until F001 lands. After
F001, amendments can reference this plan as the enforcement path for
manifest validation and advisory lock-time evidence.

## Target

```yaml
target_env: dev
target_project: none
```

This is DontPanic-internal platform plumbing. It does not require
Firebase, Linear, Discord, or agent-provider credentials.
