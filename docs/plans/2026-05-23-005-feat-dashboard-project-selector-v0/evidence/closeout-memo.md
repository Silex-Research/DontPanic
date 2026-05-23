---
status: operator_resolved
reason_class: implementation_defect
plan_id: 2026-05-23-005-feat-dashboard-project-selector-v0
feature_id: F003
closed_at: 2026-05-23T07:03:36Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-23-005-feat-dashboard-project-selector-v0 / F003

## Operator decision

This feature was closed under class `implementation_defect` after operator review of a `stopped_no_progress` terminal. The latest auditor findings were valid implementation defects, not false positives. The operator patched the bounded defects locally, reran focused and full dashboard suites, then used the close-out workflow to clear `breaker:no_progress`, write the signoff envelope, and flip `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 9 (see structured target_context.commands_run)

[F003] Repo: DontPanic  
Env: dev  
Project: (none)

Verdict: needs_changes. Implementer summary declares `Repo: DontPanic`, `Env: dev`, `Project: (none)` correctly, and structured `target_context.commands_run` contains no forbidden command shapes.

FINDING (medium, correctness): The selector’s own scope badge stays stale after changing projects. Evidence: `dashboard/core.js:153-159` handles selector changes by calling `setSelectedProject()`, but `setSelectedProject()` only updates state/URL/storage and the active page; a jsdom probe showed state becomes `spindine` while the selector badge still reads `Scope: Fleet`. Recommendation: re-render the selector, or updat...

## Rationale

The auditor's second-round findings were narrow UI-state defects: the selector scope badge stayed stale after selection changes, and the selector fingerprint ignored display-name changes. Both were fixed directly in `dashboard/core.js` with regression coverage in `dashboard/tests/integration/project-selector.test.js`. A third advisory finding about the implementer audit's structured command list is a harness/evidence issue, not a product defect in F003.

## Evidence references

- `audit/signoff-2026-05-23-005-feat-dashboard-project-selector-v0.json`
- `audit/codex-auditor-F003-i1.json`
- `evidence/test-log-F003.txt`
