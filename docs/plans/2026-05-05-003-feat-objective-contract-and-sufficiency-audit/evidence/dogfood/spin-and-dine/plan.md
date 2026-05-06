---
id: 2026-05-05-999-feat-spin-and-dine-android-parity
title: Android parity for Spin & Dine v2 core flows
type: feat
tier: cross-cutting
status: draft
date: 2026-05-05
description: Bring Android v2 to functional parity with iOS v2 across the four core user journeys — onboarding, restaurant voting, saved lists, and subscription UX. Phase 1 of the multi-quarter Android catch-up effort.
goal_type: parity
links:
  objective_contract: ./objective_contract.json
---

# Android parity — Spin & Dine v2

Static dogfood fixture for Plan F1 (`docs/plans/2026-05-05-003-...`).
This plan dir is the *input shape* for `run_sufficiency_audit()`; it does not
need to be runnable. Authored under D013's project-agnostic invariant — the
fixture is a curated parity-goal example, NOT a coupling to any external
Spin & Dine repo.

The plan is intentionally decomposed with realistic-but-incomplete features
so a real sufficiency auditor has material to surface coverage / wiring /
parity gaps against the objective contract's user_journeys.
