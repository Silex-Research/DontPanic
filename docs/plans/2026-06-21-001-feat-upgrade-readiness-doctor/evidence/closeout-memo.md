---
status: operator_finished
reason_class: operator_verified
plan_id: 2026-06-21-001-feat-upgrade-readiness-doctor
feature_id: F008
closed_at: 2026-06-22T16:22:31Z
latest_audit_status: signed_off
---

# Closeout memo — 2026-06-21-001-feat-upgrade-readiness-doctor / F008

## Operator decision

This feature was finished under terminal class `operator_verified` via the operator-finish close path (no re-dispatch, no breaker required). operator_finish (terminal=operator_verified): operator verified the feature out-of-band — Codex signed off iter=3 (3 contested rounds, no findings); terminal was patch-completeness hygiene (untracked test files + ride-along). Operator verified: Python 99/99 (F008 dashboard + command_validation regression), JS/vitest 93/93 (health-logic + what-now-logic); D052 SOURCE_UPGRADE='upgrade' admitted into the closed ActionItem source vocabulary so upgrade items validate/sort/survive the provider path; no-secret-shapes test present (test_projections_carry_no_secret_shapes + sidecar leak check). CROSS-MODULE FIX (D062): F008 adds discover + backfill-canonical subcommand shapes to command_validation.py because the upgrade manifest ships 'dontpanic projects backfill-canonical' as the canonical-discovery required action's APPLY command — a codex iter2 HIGH finding caught that without it the apply command fails token-validation, parks on display-only, and what-now-logic.js drops it (apply command would silently vanish from the dashboard). Additive, traced to cli.py shapes, regression-tested. Codex pytest blocked by read-only sandbox; operator ran live.. See evidence/closeout-memo.md. The close wrote the signoff envelope, recorded the terminal class in the operator-resolution sidecar, and flipped `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 6 (see structured target_context.commands_run)

[F008] Repo: DontPanic  
Env: dev  
Project: (none)

Verdict: signed_off. No FINDINGs. The implementer declared `Repo: DontPanic`, `Env: dev`, `Project: (none)` correctly, and `target_context.commands_run` contains only pytest commands with no forbidden shapes. Code inspection matches the F008 acceptance: status projection, Health row, upgrade ActionItems, aggregation wiring, source vocabulary, upstream/last-seen handling, evidence files, and JS rendering are present.

Checks run:
$ git status --short  
$ git diff --stat HEAD~1  
$ PYTHONDONTWRITEBYTECODE=1 python -m pytest scripts/dontpanic_orchestrate/tests/test_upgrade_dashboard_f008.py scripts/dontpanic_orchest...

## Rationale (operator)

Codex signed off (iter=3 after three contested rounds, no findings); the terminal
`blocked` was patch-completeness hygiene (untracked test files + ride-along), not a
defect. Operator verified directly: Python 99/99 (F008 dashboard + command_validation
regression), JS/vitest 93/93 (health-logic + what-now-logic); D052 `SOURCE_UPGRADE`
admitted into the closed ActionItem source vocabulary; no-secret-shapes test present
(projection + sidecar leak check).

The diff that warranted scrutiny — F008 modifying `command_validation.py` (from plan
2026-05-24-004) — proved a legitimate, auditor-driven cross-module fix, not scope
creep: it adds the `discover` + `backfill-canonical` subcommand shapes so the upgrade
manifest's apply command (`dontpanic projects backfill-canonical`) validates as an
exact_command. A codex iter-2 HIGH finding caught that without it the apply command
fails token-validation → parks on display-only → `what-now-logic.js` drops it, so the
operator's apply command would silently vanish from the dashboard. Additive, traced to
the cli.py dispatch ladder, regression-tested. Recorded as D062. Follow-up: none.

## Evidence references

- `audit/signoff-2026-06-21-001-feat-upgrade-readiness-doctor.json`
- `(latest auditor envelope not located)`

