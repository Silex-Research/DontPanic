---
status: signed_off
reason_class: feature_complete
plan_id: 2026-05-30-001-feat-universal-agent-repo-onboarding-v0
feature_id: F009
closed_at: 2026-06-02T05:30:00Z
latest_audit_status: signed_off
---

# Closeout memo — 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 / F009

## Operator decision

F009 (active-run plan-drift reconciliation — CORE, narrowed per D056 split) is closed
`signed_off`. codex signed off on run2 iter2 after the over-scoped original timed out
(D055) and was split into F009-core + F014 (D056). The drift core is wired into the
volley dispatch path with an early, fail-closed baseline and fail-closed mid-run checks.

## Return Condition

status: satisfied

F009-core returns complete when plan drift on the VOLLEY dispatch path cannot let a paid
agent call proceed on stale context, and the safety mechanism fails closed:

- A plan-run fingerprint baseline is recorded BEFORE `plan_loader.load()` (supervisor.py),
  so it reflects true dispatch-start disk state and a pre-load edit cannot be baked in
  (codex #2). If the baseline cannot be recorded it FAILS CLOSED (raises) rather than
  running blind (codex #3).
- Mid-run drift is checked before the next paid call; additive decisions.jsonl drift is
  reconciled in-place without stopping; feature/AC/gate/role/loop-cap drift PAUSES
  (`paused_on_drift`). A drift-check error FAILS CLOSED — returns `paused_on_drift`
  instead of proceeding (codex #3).
- Tests simulate another process editing plan files mid-run on the volley path and prove
  no paid call proceeds: `test_implementer_call_skipped_on_concurrent_edit`,
  `test_auditor_call_skipped_on_concurrent_edit`, `test_gate_state_edit_skips_paid_call`
  all assert `final_status == "paused_on_drift"`.
- Single-agent dispatch guard, scope/policy human-ack workflow, and CLI/dashboard
  one-action surfacing are SPLIT to F014 (D056) — out of scope here.

## Verification

- 40 tests pass: `test_plan_drift_f009.py` (27) + `test_plan_drift_supervisor_f009.py` (13).
- Operator-implemented the two architectural fixes (D057): early fail-closed baseline +
  fail-closed mid-run check; supervisor ruff-clean; 72-test regression green.
- Cross-agent: codex `signed_off` on run2 iter2.

## Evidence references

- `audit/codex-auditor-F009-i2.json` (run2) — verdict `signed_off`
- `scripts/dontpanic_orchestrate/plan_drift.py` — fingerprint/detect/classify/reconcile
- `scripts/dontpanic_orchestrate/supervisor.py` — early fail-closed baseline + fail-closed drift pause
- `scripts/dontpanic_orchestrate/tests/test_plan_drift_f009.py`, `test_plan_drift_supervisor_f009.py`
- decisions `D055` (over-scope), `D056` (split), `D057` (core fixes)
