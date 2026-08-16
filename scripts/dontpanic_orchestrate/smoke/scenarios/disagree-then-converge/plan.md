---
id: 2026-05-19-901-feat-smoke-synthetic
title: Disagree then converge
type: infra
tier: trivial
status: active
date: "2026-05-19"
description: |
  Scripted disagreement then signoff. Machinery-proving scenario only.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 2
  hard_stop: true
privacy_tier: internal
goal_type: mechanical
links:
  features: ./features.json
---

# Disagree then converge

## Target

```yaml
target_env: dev
target_project: none
```
