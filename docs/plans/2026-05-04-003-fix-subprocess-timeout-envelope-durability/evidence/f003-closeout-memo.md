# F003 close-out memo — 2026-05-05

Plan: `2026-05-04-003-fix-subprocess-timeout-envelope-durability`
Feature: F003 — supervisor classifier excludes timeout-with-work envelopes from no-progress and diminishing-returns counting.

## Volley outcome

F003 ran through the locked volley path. Plan B's staged gates behaved correctly:

- `pre_impl` paused before iteration 0 and was cleared explicitly.
- `pre_merge` did not fire because the volley ended on a non-success terminal path.

The volley ended `stopped_no_progress` after two `needs_changes` auditor verdicts, but it produced useful implementation and audit signal.

| Iteration | Implementer | Auditor verdict | Triage |
|---|---|---|---|
| i0 | Timed out after 600s; F002 evidence rendered `audit_status=blocked`, timeout byte markers, `worktree_changed=unknown` | `needs_changes` | Two substantive findings: skipped timeout-with-work rounds could still advance the no-progress baseline; blocked-without-work regression allowed `stopped_diminishing_returns` instead of exact `stopped_no_progress`. |
| i1 | Landed fixes and reported local verification | `needs_changes` | Only remaining issue was missing explicit `signed_off` coverage in detector matrices. Fixed during direct close-out. |

The final close-out path is accepted-on-direct-review per D011. The volley found real issues; the direct patch only completed the final test-coverage gap.

## What Landed

| File | Change |
|---|---|
| `scripts/dontpanic_orchestrate/circuit_breakers.py` | Adds `_envelope_is_timeout_with_work()`, best-effort audit envelope loading, implementer/auditor round pairing, no-progress envelope filtering, and diminishing-returns window filtering. |
| `scripts/dontpanic_orchestrate/supervisor.py` | Reads the implementer envelope after each implementer round, appends a transcript note for timeout-with-work, passes the envelope into no-progress detection, and avoids advancing `prior_aud_status` for skipped timeout-with-work rounds. |
| `scripts/dontpanic_orchestrate/transcript.py` | Adds `append_note()` for operator-visible non-terminal classifier notes. |
| `scripts/dontpanic_orchestrate/tests/test_timeout_with_work_classifier.py` | Adds 39 focused tests across classifier helper, no-progress, diminishing-returns, transcript fidelity, synthetic volley behavior, prior-status carry-over, auditor invocation, boundary discipline, and isolation discipline. |

## Finding Disposition

| Finding | Class | Resolution |
|---|---|---|
| i0: skipped timeout-with-work round could become the prior no-progress baseline | feature_defect | Fixed by not advancing `prior_aud_status` when the current implementer envelope is timeout-with-work. `prior_aud_path` still updates so the next implementer sees fresh auditor context. |
| i0: blocked-without-work regression did not assert exact `stopped_no_progress` | regression | Fixed by shaping synthetic findings to avoid diminishing-returns and asserting exact `stopped_no_progress`. |
| i0: transcript fidelity did not prove all shapes appear | test_coverage | Fixed with transcript row + classifier note coverage for all four shapes. |
| i1: signed_off envelope shape missing from detector matrices | test_coverage | Fixed by adding `signed_off` to both no-progress and diminishing-returns parametric matrices. |
| implementer i0 timeout | already-known/platform | F001/F002 made the timeout diagnosable. F003 was already expected to run under the old classifier until merged. |

## Acceptance Coverage

| # | Acceptance | Result |
|---|---|---|
| 1 | Classifier helper exists and is pure | `_envelope_is_timeout_with_work()` returns true only for `audit_status=blocked` plus `worktree_changed=true`; tests cover invalid inputs and no mutation. |
| 2 | No-progress excludes timeout-with-work | Parametric no-progress test covers `blocked/true`, `blocked/false`, `blocked/unknown`, `signed_off`, and legacy missing-marker shape. |
| 3 | Diminishing-returns excludes timeout-with-work | Parametric diminishing-returns test covers the same required shapes plus legacy missing-marker shape. |
| 4 | Loop history fidelity | Tests assert all shapes remain on disk and appear in transcript rows; timeout-with-work also gets the classifier note. |
| 5 | Plan-B-shaped run terminates `stopped_cap` | Synthetic two-round timeout-with-work run reaches iteration cap instead of no-progress or diminishing-returns. |
| 6 | Legitimate no-progress still terminates `stopped_no_progress` | Synthetic blocked-without-work run uses distinct findings to isolate no-progress and asserts exact terminal status. |
| 7 | No breaker enum / threshold / terminal-status changes | Boundary test inspects the diff and permits only the known status literals used as context; no enum, threshold, or terminal mapping changed. |
| 8 | Auditor invocation unchanged | Synthetic executor test proves auditor receives the implementer audit after a timeout-with-work implementer round. |
| 9 | Transcript visibility | `append_note()` writes the operator-visible timeout-with-work classification line. |
| 10 | Test isolation discipline | Test file contains no `del sys.modules`; helper restoration uses `importlib.reload(supervisor)`. |
| 11 | Full suite passes | Full orchestrate suite excluding Plan-D EC5 purity file: 959 passed, 6 skipped. |
| 12 | Ruff check + format clean | F003 touched files pass ruff check and format check. |
| 13 | Sanitization clean | `python scripts/sanitization_check.py`: 0 findings, 689 files scanned. |
| 14 | No historical docs/plans churn | Only this plan directory is touched; historical plan dirs remain unstaged/untouched. |
| 15 | No audit schema changes | F003 only reads F002 markers; it adds no audit envelope fields and no audit_status values. |

## Verification

Focused:

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=scripts python -m pytest -p no:cacheprovider scripts/dontpanic_orchestrate/tests/test_timeout_with_work_classifier.py
39 passed in 0.56s
```

Broad:

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=scripts python -m pytest -p no:cacheprovider scripts/dontpanic_orchestrate/tests --ignore=scripts/dontpanic_orchestrate/tests/test_ec5_classifier.py
959 passed, 6 skipped, 1 warning in 38.10s
```

Additional checks:

- Ruff check: clean on `circuit_breakers.py`, `supervisor.py`, `transcript.py`, and `test_timeout_with_work_classifier.py`.
- Ruff format check: clean on the same files.
- Sanitization: clean, 689 files scanned.

## Validator Caveat

Running the generic plan validator against the whole plan directory after dispatch currently fails on generated `audit/gate-state.json`:

```text
audit/gate-state.json — task_id: Field required; audit_id: Field required; agent: Field required; agent_role: Field required; iteration: Field required
```

That file is canonical gate state, not an audit envelope. The validator is attempting to validate every JSON under `audit/` as an audit envelope. `plan.md`, `features.json`, and the four F003 audit envelopes validate; the false-positive is a validator hygiene issue, not an F003 defect.

## Plan State

Plan C is complete:

- F001 — shared subprocess runner: passes true.
- F002 — timeout evidence in audit envelopes: passes true.
- F003 — timeout-with-work classifier: passes true.

Next queued platform fix remains Plan D: EC5 classifier purity after the rename.
