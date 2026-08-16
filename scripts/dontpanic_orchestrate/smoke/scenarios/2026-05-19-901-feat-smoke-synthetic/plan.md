---
id: 2026-05-19-901-feat-smoke-synthetic
title: Smoke harness synthetic plan
type: infra
tier: trivial
status: active
date: "2026-05-19"
description: |
  Synthetic supervisor-plumbing exercise. Created by `dontpanic smoke
  --mode=mocked`. NOT a real plan — does not represent shipping work
  and is deleted on smoke exit (success or failure).
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 1
  hard_stop: true
privacy_tier: internal
goal_type: mechanical
links:
  features: ./features.json
---

# Smoke harness synthetic plan

Used by `dontpanic smoke --mode=mocked` only. Never dispatched against
real CLIs. Throwaway tmpdir, cleaned on exit.

## Target

```yaml
target_env: dev
target_project: none
```
