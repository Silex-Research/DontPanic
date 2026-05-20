---
status: operator_resolved
reason_class: spec_ambiguity
plan_id: 2026-05-19-004-feat-architecture-map-with-drift-v0
feature_id: F003
closed_at: 2026-05-20T03:48:03Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-19-004-feat-architecture-map-with-drift-v0 / F003

## Operator decision

This feature was closed under class `spec_ambiguity` after operator review of a `stopped_no_progress` terminal. The audit finding is recorded as non-defect; the close-out workflow generated this template, cleared `breaker:no_progress`, wrote the signoff envelope, and flipped `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 7 (see structured target_context.commands_run)

[F003] Repo: DontPanic  
Env: dev  
Project: (none)

Overall verdict: needs_changes. Implementer summary declared `Repo: DontPanic`, `Env: dev`, `Project: (none)` correctly, and recorded commands contain no forbidden shapes.

FINDING (medium, correctness): The required `--strict` mode is not wired for architecture drift. Evidence: `features.json:77-82` requires `--strict` to block on `stale_major`/`ABSENT`, but `scripts/dontpanic_doctor.py:1992-2040` only wires `--strict-codes` and `--architecture-drift-strict`; `scripts/dontpanic_orchestrate/cli.py:1464-1492` also only exposes `--architecture-drift-strict`. Running `--strict` on the script is accepted as an argpar...

## Rationale (operator — fill in)

<!--
Explain in 2-4 sentences:
  - Why the finding does not warrant a re-dispatch.
  - What spec/doc/convention change (if any) should follow to
    prevent the same friction next time.
  - Any follow-up tickets, plan IDs, or D-entries to file.
-->

## Evidence references

- `audit/signoff-2026-05-19-004-feat-architecture-map-with-drift-v0.json`
- `(latest auditor envelope not located)`


## Return Condition

F003 (doctor architecture_drift probe) + F005 (opt-in pre-commit hook) shipped together in this commit. F005 signed_off on iter0 (1 round) with one advisory (perf-test rename — patched). F003 stopped_no_progress on flag-naming spec_ambiguity (implementer's `--architecture-drift-strict` chosen over spec's `--strict` to avoid argparse abbreviation collision with existing `--strict-codes`; mirrors `--validate-plans-strict` pattern from Plan 3 F003). No hand-patch required for F003. Full sweep 2036 passed / 7 skipped; sanitization clean (1288 files). See D005 (F005) + D006 (F003).
