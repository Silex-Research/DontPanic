# F001 close-out memo — 2026-05-04

Plan: `2026-05-04-002-fix-supervisor-lifecycle-staged-gates`
Feature: F001 — stage human-gate evaluation across the supervisor lifecycle.

## Volley outcome

The volley terminated `stopped_no_progress` after two rounds. The implementer wrapper timed out before flushing a complete audit envelope, but real edits landed on disk:

- `scripts/dontpanic_orchestrate/cli.py`
- `scripts/dontpanic_orchestrate/gate_pause.py`
- `scripts/dontpanic_orchestrate/supervisor.py`
- `scripts/dontpanic_orchestrate/tests/test_f008_engagement_surface.py`

This matches D010's timeout caveat: accept on direct review when the work landed, verify acceptance on the operator machine, and leave the subprocess timeout / envelope durability fix to the queued Plan C.

## Remediation Applied

The i1 auditor findings were real and bounded:

| Finding | Classification | Close-out action |
|---|---|---|
| Missing `test_lifecycle_staged_gates.py` | feature_defect | Added dedicated runtime-ordering, compatibility, breaker non-interaction, and idempotency tests. |
| Stale `test_cli_resume.py` semantics | regression | Updated lifecycle-gate cases so `--gate` requires the pending stage, already-cleared lifecycle gates exit 2, and `--all` clears current stage only. |
| Ruff format dirty | spec-clarification | Ran ruff format on touched source and tests. |

Additional helper updates were required in pre-existing synthetic tests that used `resume_all(..., declared_gates=["pre_impl"])` as a pre-clear shortcut. Under Plan B that is intentionally no longer valid without a pending stage, so those helpers now seed and approve the lifecycle stage explicitly.

## Behavior Landed

| Surface | Result |
|---|---|
| `pre_impl` | Evaluated after plan load / executor capability checks and before iteration-0 implementer dispatch. Pauses with `pending_stage: "pre_impl"`. |
| `pre_merge` | Evaluated only when auditor returns `signed_off`, immediately before success signoff would be written. Failure evidence does not wait on `pre_merge`. |
| `gate-state.json` | Additive shape: legacy `cleared_gates` remains; staged paths add `gate_events`, `pending_stage`, and `completed_stages`. Legacy dict-shaped `cleared_gates` loads compatibly. |
| CLI resume/approve | Bare `dontpanic resume <plan>` still exits 2. `approve` / `resume --gate` clear only the currently pending lifecycle gate. `resume --all` clears the current stage only. |
| Breakers | `circuit_breakers.py` was not touched. Active `breaker:*` gates still pause at breaker timing, not lifecycle-stage timing. |

## Verification

Commands run on the operator machine:

| Check | Result |
|---|---|
| `pytest scripts/dontpanic_orchestrate/tests/test_lifecycle_staged_gates.py scripts/dontpanic_orchestrate/tests/test_cli_resume.py scripts/dontpanic_orchestrate/tests/test_f008_engagement_surface.py` | 38 passed |
| Affected-file regression suite (`test_lifecycle_staged_gates.py`, `test_cli_resume.py`, `test_f008_engagement_surface.py`, `test_environments_loader.py`, `test_f006_circuit_breakers.py`, `test_plan_target.py`, `test_target_context.py`) | 140 passed |
| `pytest scripts/dontpanic_orchestrate/tests --ignore=scripts/dontpanic_orchestrate/tests/test_ec5_classifier.py` | 886 passed, 6 skipped |
| `ruff check scripts/dontpanic_orchestrate scripts/dontpanic_doctor.py scripts/jarvis_doctor.py` | All checks passed |
| `ruff format --check ...` on touched files | 10 files already formatted |
| `python scripts/sanitization_check.py` | 0 findings, 671 files scanned |
| `git diff -- scripts/dontpanic_orchestrate/circuit_breakers.py` | Empty diff |

Known non-blocking validator caveat: `python3 claude/shared/schemas/v1.0/validate.py docs/plans/2026-05-04-002-fix-supervisor-lifecycle-staged-gates` still tries to validate `audit/gate-state.json` as if it were an audit envelope and fails on missing audit fields. That command is not used as the Plan B acceptance gate because the plan's `audit/` directory intentionally contains non-envelope operational state. The code/test/sanitization checks above are the authoritative close-out evidence for this feature.

## Remaining Work

- Plan C: fix the 600s subprocess timeout / envelope durability issue that caused the volley wrapper to truncate implementer evidence.
- Plan D: fix the known `test_ec5_classifier.py` purity regression that remains excluded from the full suite per the prior D011 caveat.
