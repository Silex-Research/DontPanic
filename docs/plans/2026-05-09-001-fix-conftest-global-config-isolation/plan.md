---
id: 2026-05-09-001-fix-conftest-global-config-isolation
title: Conftest test isolation — redirect DONTPANIC_HOME / JARVIS_HOME so operator global config does not leak into orchestrate tests
type: fix
tier: trivial
status: completed
date: "2026-05-09"
surfaces:
  - infra
agents_required:
  - claude
human_gates: []
loop_caps:
  max_iterations: 1
  no_progress_threshold: 1
  wall_clock_hours: 1
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-08-003-fix-harness-volley-frictions
protected_paths:
  - claude/shared/
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
description: |
  The orchestrate test suite's autouse `_isolate_jarvis_state` fixture
  redirects four operator state files (breaker_history, active_supervisors,
  interactive_state, quota_state, plus quota_caps) but does NOT redirect
  the operator's `DONTPANIC_HOME` / `JARVIS_HOME` env vars. As a result,
  `~/.jarvis/config.json` (legacy) and `~/.dontpanic/global_config.json`
  (modern) leak operator-specific role assignments into the test runner
  and produce ~50 phantom failures across `test_completion_dispatch.py`,
  `test_sufficiency_auditor.py`, and `test_completion_gate.py`.

  Concrete repro from the preserved feedback memo
  (`feedback_orchestrate_test_isolation_global_config.md`): operator's
  `~/.jarvis/config.json` had `roles: {implementer: codex, auditor: claude,
  goal_auditor: claude}`. The resolver at
  `sufficiency_auditor._resolve_goal_auditor_agent` reads
  `_resolvers.resolve_role(plan_dir, "goal_auditor")` which falls through
  to global config, returns "claude", clashes with implementer="claude" →
  `SameVendorRefused`. Setting `JARVIS_HOME=/tmp/x DONTPANIC_HOME=/tmp/y`
  to empty tmp dirs makes all 41 `test_completion_dispatch.py` tests pass.

  This plan extends the autouse fixture by two env vars so the gap closes
  structurally — no operator hygiene needed.
motivation: |
  The harness-frictions plan (`2026-05-08-003`) closed yesterday with the
  full orchestrate sweep at 1524 passed only AFTER manually setting
  `JARVIS_HOME=/tmp/dp_baseline DONTPANIC_HOME=/tmp/dp_baseline_dp` for
  every run. D007 of that plan explicitly memo'd the gap as separate scope
  ("conftest/global-config isolation is adjacent motivation, separate
  scope") — this plan is that follow-up.
---

# Conftest global-config isolation

## Thesis

The conftest autouse fixture already isolates four operator-state files;
extending it to also redirect `DONTPANIC_HOME` and `JARVIS_HOME` is the
minimal, mechanical change that closes the operator-config leak without
any risk to production code paths. The fix touches only test infrastructure.

## Boundaries

- No production code changes.
- No agent-conventions schema changes.
- No new test fixtures or plumbing beyond the autouse env-var redirect
  and one regression-pinning test that proves the leak is closed.
- No changes to `sufficiency_auditor._resolve_goal_auditor_agent` or any
  other resolver — the gap is purely test isolation, not resolver logic.

## Acceptance Summary

- F001 extends `tests/conftest.py` to redirect `DONTPANIC_HOME` and
  `JARVIS_HOME` to per-test `tmp_path` subdirectories.
- A regression test proves the autouse fixture renders an operator-shaped
  `roles.goal_auditor` config inert: writing such a config under the
  redirected `JARVIS_HOME` does NOT influence resolver output during the
  test (because the redirect points at an empty tmp dir; the test
  populates it on demand to demonstrate the override is honored).
- Full orchestrate sweep passes WITHOUT the operator setting any env vars
  before invoking pytest. Compare to the previously-required hygiene
  pattern (`JARVIS_HOME=/tmp/dp_baseline ...`).

## Target

```yaml
target_env: dev
target_project: none
```
