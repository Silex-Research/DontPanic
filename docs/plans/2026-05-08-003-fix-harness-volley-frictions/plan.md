---
id: 2026-05-08-003-fix-harness-volley-frictions
title: Harness volley frictions — fail-loud gates, auto-clear pre-impl, and verdict taxonomy
type: fix
tier: local
status: draft
date: "2026-05-08"
goal_type: parity
surfaces:
  - infra
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  no_progress_threshold: 1
  wall_clock_hours: 3
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-04-002-fix-supervisor-lifecycle-staged-gates
  - 2026-05-07-001-fix-completion-dispatch-codex-stream-parser
  - 2026-05-07-002-fix-cross-vendor-dogfood-fixture-runtime-artifacts
protected_paths:
  - claude/shared/
  - docs/plans/2026-05-08-002-feat-skill-applicability-v0/
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
description: |
  Three narrowly-scoped fixes for harness frictions surfaced by recent
  dogfood and close-out runs:

  F001 makes gate-state reconciliation fail loud when persisted gate state
  conflicts with declared plan gates.

  F002 removes the dispatch chicken-and-egg for ordinary dev/test plans by
  auto-clearing `pre_impl` only when the operator is already invoking the
  dispatch command directly, while preserving explicit INBOX evidence.

  F003 hardens auditor terminal classification so environmental harness
  failures and genuine implementation defects do not collapse into the same
  `stopped_no_progress` / `needs_changes` operator burden.
motivation: |
  Recent DontPanic work exposed the same broad pattern from three angles:
  the harness has enough evidence to make a sharper state transition, but
  the operator still has to read raw artifacts and manually recover.

  The skill-applicability v0 ID is already taken by
  `2026-05-08-002-feat-skill-applicability-v0`, so this follow-up uses
  `2026-05-08-003-fix-harness-volley-frictions`.

  Adjacent memory also records a separate conftest/global-config isolation
  issue: tests can be polluted by operator-level `~/.jarvis/config.json` or
  `~/.dontpanic/global_config.json`, producing phantom auditor failures.
  That is not in this plan's write scope, but it is part of the same
  harness-friction neighborhood and should be referenced by any later sweep.
---

# Harness Volley Frictions

## Thesis

The platform should not ask the operator to resolve harness state that the
supervisor can classify deterministically. When state is contradictory, it
should fail loud. When the operator has already initiated an interactive
dispatch, `pre_impl` should not require a second redundant clearance. When an
auditor cannot reproduce due to sandbox/environment limits, that should be
classified distinctly from a real implementation defect.

This plan is intentionally manual/direct. It does not use nested orchestration
or a live volley to fix the volley path itself.

## Feature Roadmap

| Feature | Phase | Surface |
|---|---:|---|
| F001 | 1 | Fail-loud gate-state reconciliation |
| F002 | 2 | Dispatch-time `pre_impl` auto-clear with INBOX evidence |
| F003 | 3 | Auditor verdict taxonomy for environmental vs defect findings |

## Boundaries

- No agent-conventions schema changes.
- No edits to skill-applicability v0 plan artifacts.
- No implementation of phase-mode dispatch, auto-commit, or plan-level
  closeout aggregation from `feedback_dontpanic_phase_level_feature_recursion_gap.md`.
- No conftest/global-config isolation fix; that gets its own small
  platform-integrity plan.
- No live nested orchestration in this plan's own implementation path.

## Acceptance Summary

- F001 adds deterministic tests showing contradictory gate-state/declaration
  combinations raise a clear reconciliation error and leave artifacts
  unmutated.
- F002 adds a dispatch-only `pre_impl` auto-clear path for dev/test plans,
  records an INBOX event, and preserves manual gate discipline for non-dispatch
  approval/resume paths and protected targets.
- F003 introduces a conservative classifier for auditor terminal findings:
  environmental/sandbox reproduction failures are surfaced as a distinct
  harness classification, while real implementation defects remain blocking.
- Objective-contract evidence artifacts are named in stable filenames so the
  F2 close gate can match them without override.

## Target

```yaml
target_env: dev
target_project: none
```

