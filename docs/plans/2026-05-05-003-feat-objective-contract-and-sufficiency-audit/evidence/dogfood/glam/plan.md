---
id: 2026-05-05-998-feat-creator-hub-v1
title: Creator Hub v1 — unified creator surface
type: feat
tier: cross-cutting
status: draft
date: 2026-05-05
description: Ship Creator Hub v1 — a unified surface where creators compose, publish, and track posts. iOS + web, post-based (no live-streaming yet). Replaces the scattered profile-edit + post-compose + analytics-dashboard surfaces with one cohesive flow.
goal_type: new_feature
links:
  objective_contract: ./objective_contract.json
---

# Creator Hub v1

Static dogfood fixture for Plan F1 (`docs/plans/2026-05-05-003-...`).
This plan dir is the *input shape* for `run_sufficiency_audit()`; it does not
need to be runnable. Authored under D013's project-agnostic invariant — the
fixture is a curated integrated-product-surface example, NOT a coupling to any
external Glam repo.

The plan is intentionally decomposed into per-feature slices (composer,
publish-pipeline, analytics dashboard, profile editing) without explicit
integration features, so a real sufficiency auditor has material to surface
integration / wiring gaps against the contract's `completion_test` ("works
as a unified product surface, not a feature collection").
