---
status: operator_resolved
reason_class: implementation_defect
plan_id: 2026-05-19-002-feat-install-ux-hardening-v0
feature_id: F003
closed_at: 2026-05-20T15:20:05Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-19-002-feat-install-ux-hardening-v0 / F003

## Operator decision

This feature was closed under class `implementation_defect` after operator review of a `stopped_no_progress` terminal. The audit finding is recorded as non-defect; the close-out workflow generated this template, cleared `breaker:no_progress`, wrote the signoff envelope, and flipped `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 2 (see structured target_context.commands_run)

[F003] Repo: DontPanic
Env: dev
Project: (none)

Overall verdict: needs_changes. The implementer audit summary declared `Repo: DontPanic`, `Env: dev`, and `Project: (none)` correctly; `target_context.commands_run` was empty, so I found no forbidden command shapes there.

FINDING (high, correctness): `dontpanic smoke --mode=mocked --json` crashes instead of returning exit code 2 for an env blocker. Evidence: `run_smoke()` catches `tempfile.mkdtemp()` failure, then calls `tempfile.gettempdir()` again while formatting the error at `scripts/dontpanic_orchestrate/smoke/__init__.py:611-614`, producing an uncaught `FileNotFoundError`. Recommendation: avoid re-calling `get...

## Rationale (operator — fill in)

<!--
Explain in 2-4 sentences:
  - Why the finding does not warrant a re-dispatch.
  - What spec/doc/convention change (if any) should follow to
    prevent the same friction next time.
  - Any follow-up tickets, plan IDs, or D-entries to file.
-->

## Evidence references

- `audit/signoff-2026-05-19-002-feat-install-ux-hardening-v0.json`
- `(latest auditor envelope not located)`

