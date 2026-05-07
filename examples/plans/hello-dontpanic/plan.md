---
id: 2026-05-07-001-infra-hello-dontpanic
title: Hello DontPanic Sample
type: infra
tier: trivial
status: draft
date: "2026-05-07"
description: |
  Safe private-alpha sample plan for validating, locking, and closing a
  DontPanic plan without dispatching agents or calling paid model APIs.
agents_required:
  - claude
human_gates: []
loop_caps:
  max_iterations: 1
  no_progress_threshold: 1
  wall_clock_hours: 1
  hard_stop: false
privacy_tier: internal
links:
  features: features.json
  decisions: decisions.jsonl
  audit: audit/
  evidence: evidence/
---

## Target

```yaml
target_env: local
target_project: none
```

## Scope

Exercise the plan lifecycle only:

- validate the plan directory;
- lock the plan from `draft` to `active`;
- close the plan from `active` to `completed`.

## Out Of Scope

- Agent dispatch.
- Cloud resources.
- Runtime evidence collection.
- Source code changes.
