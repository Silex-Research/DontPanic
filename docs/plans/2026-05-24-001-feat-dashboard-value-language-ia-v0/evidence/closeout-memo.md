---
status: operator_resolved
reason_class: implementation_defect
plan_id: 2026-05-24-001-feat-dashboard-value-language-ia-v0
feature_id: F004
closed_at: 2026-05-24T14:16:25Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-24-001-feat-dashboard-value-language-ia-v0 / F004

## Operator decision

This feature was closed under class `implementation_defect` after operator review of a `stopped_no_progress` terminal. The latest auditor findings were actionable implementation/documentation defects; the operator patched them directly, reran focused verification, cleared `breaker:no_progress`, wrote the signoff envelope, and flipped `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 5 (see structured target_context.commands_run)

[F004] Repo: DontPanic
Env: dev
Project: (none)

Verdict: needs_changes. Implementer target declaration is correct (`Repo: DontPanic`, `Env: dev`, `Project: (none)`; structured `env=dev`, `project=null`), and I found no forbidden command shapes in their `target_context.commands_run`.

FINDING (high, correctness): Project-filtered Needs Attention provenance reports the wrong state source. Evidence: `pages/what-now/what-now.js:37-45` routes project views through `renderProjectWhatNowHTML(fleetWhatNow, ...)`, but `dashboard/lib/what-now-logic.js:876-890` reuses `renderPopulatedHTML(..., 'project')`; that footer uses `WHAT_NOW_SOURCE` (`dashboard/state/what-now.jso...

## Rationale (operator)

The remaining F004 findings were narrow and directly patched: project-filtered Needs Attention now passes fleet provenance through the reused populated/quiet renderers, the accessibility note now reflects the actual selectable `<pre>` command emission used by Tools & Setup, and the sanitization log now names the full plan/design/snapshot scope. Focused verification passed after the patch: 215 provenance/value-language/dashboard tests; syntax checks for `what-now-logic.js` and `provenance.js`; `dontpanic dashboard build`; and `dontpanic dashboard serve --once --no-watch`. No re-dispatch was needed because the residual issues were fully understood, locally corrected, and covered by existing F004 evidence tests plus the explicit evidence artifacts.

## Evidence references

- `audit/signoff-2026-05-24-001-feat-dashboard-value-language-ia-v0.json`
- `(latest auditor envelope not located)`
