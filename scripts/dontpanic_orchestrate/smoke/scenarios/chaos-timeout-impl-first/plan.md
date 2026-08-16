---
id: 2026-05-19-901-feat-smoke-synthetic
title: Chaos timeout on first implementer call
type: infra
tier: trivial
status: active
date: "2026-05-19"
description: |
  Chaos fixture. Encodes current supervisor behavior, not a requirement.
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

# Chaos timeout

## Target

```yaml
target_env: dev
target_project: none
```
