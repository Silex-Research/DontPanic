---
id: 2026-04-26-006-infra-f023-ec5-evidence
title: F023 behavioral EC5 evidence — real volley against jarvis-a6ee1
type: infra
tier: trivial
status: abandoned
date: "2026-04-26"
description: Trivial real-volley dogfood whose only purpose is to produce audit JSONs whose target_context.env==dev so F023 acceptance criterion can flip.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

> **⊘ ABANDONED 2026-05-05** — superseded by `2026-05-04-004-fix-ec5-classifier-purity` (Plan D), which sealed EC5 classifier purity end-to-end on 2026-05-04. The behavioral evidence dogfood this sub-plan was scoped to provide is no longer the canonical proof point; Plan D's own dogfood + the patched ec5_classifier already cover it. Closed as housekeeping per `docs/GOAL_GOVERNANCE_V1.md` §10. Original plan content preserved below for historical reference.

# F023 behavioral EC5 evidence

A trivial single-iteration volley against `jarvis-a6ee1`. The implementer produces a one-line summary; the auditor signs off (or returns needs_changes — either is acceptable evidence for EC5). The point is the audit JSON's `target_context.env == "dev"`.

## Target

```yaml
target_env: dev
target_project: jarvis-a6ee1
```

## Notes

- No real cloud writes happen; this is a content-only dispatch.
- Both agents will run with cwd set to the Jarvis repo root (EC11) and the F023 ExecutionEnvironment overlay applied.
