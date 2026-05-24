---
status: operator_resolved
reason_class: implementation_defect
plan_id: 2026-05-24-004-feat-event-messaging-v1
feature_id: F001
closed_at: 2026-05-24T17:14:09Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-24-004-feat-event-messaging-v1 / F001

## Operator decision

This feature was closed under class `implementation_defect` after operator review of a `stopped_no_progress` terminal. The audit finding is recorded as non-defect; the close-out workflow generated this template, cleared `breaker:no_progress`, wrote the signoff envelope, and flipped `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 6 (see structured target_context.commands_run)

[F001] Repo: DontPanic
Env: dev
Project: (none)

Overall verdict: needs_changes. Implementer target declaration is correct, and `target_context.commands_run` contains no forbidden command shapes.

FINDING (high, correctness): `validate_command_tokens` still does not mirror the real CLI flag surfaces. Evidence: `command_validation.py` rejects real commands like `doctor --json`, `dispatch-from-plan <plan> --confirm`, `dispatch-from-plan <plan> --allow-incomplete-patch ...`, `plan lock <plan> --ignore-sufficiency-findings ...`, `setup --implementer claude`, `capabilities status F001 --format json`, and `next --format json`; it also accepts stale/nonexistent shapes lik...

## Rationale (operator)

Auditor findings were real `implementation_defect` (stale `--strict` flag accepted by the validator; real flags missing from doctor/dispatch-from-plan/plan-lock/setup/capabilities/next). Re-dispatching risked a second loop on the same mechanical inventory work since the per-subcommand argparse construction is inline at ~18 sites and the implementer had already converged on the SubcommandSpec abstraction. Path C per architect/PM call: operator hand-patched the validator vocabulary against verified `cli.py` line locations, replaced the single stale `--allow-incomplete-patch-reason` test with parametrized `auditor_cited_real_cli_shapes_validate` (17 cases) and `auditor_cited_stale_shapes_now_reject` (10 cases), and ran the focused suite to green. Both the false-negative class (real commands rejected) and false-positive class (stale flags accepted) the auditor flagged are now pinned by tests.

**Why not re-dispatch:** the validator was structurally correct (SubcommandSpec is the right abstraction per D012); only the per-subcommand flag map was incomplete. Re-running paid claude+codex on a mechanical enumeration would have burned budget without changing the architectural shape.

**Why not narrow F001 acceptance:** the implementer shipped a stronger validator than D012 strictly required (per-subcommand flag enforcement vs token-only-shape). Narrowing the acceptance post-hoc would have weakened the D008 honest-commands contract that F003 depends on. Path C preserves the stronger shape.

**Follow-up:** none required for F001. F002 (NotifyEvent metadata extension + inbox_event field + 6 new emit sites) proceeds against the now-passing validator. If future cli.py subcommand additions introduce drift, the `auditor_cited_real_cli_shapes_validate` parametrized test catches it at PR review per D021's manual-discipline rule.

## Evidence references

- `audit/signoff-2026-05-24-004-feat-event-messaging-v1.json` — signoff envelope
- `audit/codex-auditor-F001-i1.json` — auditor's final findings (cited above)
- `audit/no_progress_classification_F001_iter2.json` — no_progress taxonomy that triggered Path C
- `scripts/dontpanic_orchestrate/command_validation.py` — patched validator
- `scripts/dontpanic_orchestrate/tests/test_command_validation_f001.py` — parametrized pin tests for the cited examples
