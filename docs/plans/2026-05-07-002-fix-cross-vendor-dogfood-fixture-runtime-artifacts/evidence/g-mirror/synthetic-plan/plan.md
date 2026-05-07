---
id: 2026-05-06-001-infra-runtime-evidence-harness-mirror
title: Plan G mirror — synthetic fixture for live cross-vendor goal-audit dogfood
type: infra
tier: cross-cutting
status: completed
date: "2026-05-06"
goal_type: new_feature
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
dependencies:
  - 2026-05-05-002-feat-goal-governance-nested-orchestration-config
  - 2026-05-05-003-feat-objective-contract-and-sufficiency-audit
links:
  objective_contract: ./objective_contract.json
description: |
  Synthetic mirror of Plan G's close-out state, scoped for the F2
  live cross-vendor goal-audit dogfood (parent plan
  `2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood`). Plan G's
  actual plan dir is read-only from the parent's perspective (parent
  D001); this mirror is self-contained and reproducible — artifacts
  copied (not symlinked) from Plan G's tree per parent D004.

  `goal_type=new_feature` (NOT infra) so the F2 completion gate
  engages on this mirror at close time. The outer wrapper plan is
  `goal_type=infra` and exempt; this inner mirror is the part that
  the live `dontpanic plan close` invocation will actually audit.

  This mirror is NOT Plan G itself. Editing Plan G is forbidden; this
  fixture is a snapshot used purely to drive the F002 cross-vendor
  dispatcher against a real contract shape with both vendors actually
  invoked.

motivation: |
  See parent plan
  `2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood/plan.md`
  for the full validation framing. In short: F2's production-path
  test (`test_production_path_invokes_resolved_executor` in
  `test_completion_dispatch.py`) stubs the executor; this mirror
  exercises the unstubbed path with both vendors actually invoked.
---

# Plan G mirror — synthetic fixture

Snapshot of Plan G's close-out state for the live cross-vendor
goal-audit dogfood. NOT to be dispatched against by the supervisor.
NOT to be edited as if it were a real plan. The fixture is consumed
by `dontpanic plan audit` and `dontpanic plan close` from the parent
plan's F001.

See parent plan `2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood/`
for the full validation framing. See `objective_contract.json` for
the operator-authored retrospective contract that anchors the audit.
