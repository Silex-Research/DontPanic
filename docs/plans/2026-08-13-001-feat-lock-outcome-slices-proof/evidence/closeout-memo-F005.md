---
status: operator_resolved
reason_class: spec_ambiguity
plan_id: 2026-08-13-001-feat-lock-outcome-slices-proof
feature_id: F005
closed_at: 2026-08-14T22:53:05Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-08-13-001-feat-lock-outcome-slices-proof / F005

## Operator decision

This feature was closed under class `spec_ambiguity` after operator review of a `stopped_no_progress` terminal. The audit finding is recorded as non-defect; the close-out workflow generated this template, cleared `breaker:no_progress`, wrote the signoff envelope, and flipped `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 7 (see structured target_context.commands_run)

[F005] Repo: DontPanic  
Env: dev  
Project: (none)

Overall verdict: **needs_changes**. The implementer correctly declared Repo/Env/Project; structured `project: null` matches `(none)`, and empty `commands_run` contains no forbidden commands.

FINDING (medium, correctness): Structurally valid alterations to an unreceipted historical sidecar remain undetectable and are backfilled as intact. Evidence: removing a slice or changing its proof reference/method returned no defect; `backfill_lock_receipt()` would then receipt the altered bytes. Recommendation: refuse unreceipted sidecars pending explicit migration, or amend D014/D015 and acceptance to record this broader ...

## Rationale (operator)

Closed as `spec_ambiguity`, deliberately **not** `signed_off_adjacent`. The
auditor never signed off on F005, and claiming otherwise would be the same
false record this plan exists to prevent. F002 and F004 earned that class; this
one did not.

All three acceptance criteria were verified independently before closing:

  - **AC3** confirmed in code. `_record_outcome_score_before_flip` now returns
    `3` and leaves the plan draft on any scorer failure. The string "lock
    proceeds unrecorded" survives only inside a docstring describing the
    behaviour it no longer has — a grep alone would misread it as unfixed.
  - **AC1 and AC2** satisfied by the three-state model recorded in D013
    (LEGACY / INTACT / DESTROYED) and D014. AC2 requires the chosen semantics
    be recorded in `decisions.jsonl`; they are.
  - 46 tests pass in `test_outcome_score_f005.py`, executed outside the
    implementer's sandbox.

Auditor severity fell every round — 2 high, 1 high, 0 high. Two mediums remain.

**Undetectable alteration of a pre-receipt sidecar.** D014 chose to backfill a
receipt at the bytes found on disk, marked `{"backfilled": true}`. That is the
honest answer to an impossible problem: bytes that were never hashed cannot be
retroactively verified, and the marker says precisely that rather than claiming
an integrity guarantee it does not have. The auditor prefers a refusal instead.
Refusing close on any unreceipted sidecar would refuse every plan locked before
this feature existed — which AC1 explicitly forbids. The two positions cannot
both be satisfied, which is why the class is spec_ambiguity: the acceptance
never adjudicated pre-receipt bytes.

**No executed test evidence from the implementer.** Environmental, not a defect.
Its sandbox provides no writable temporary directory, so it can collect tests
but never run them. It has hit this in every round of F002, F004 and F005. The
operator-side run supplies what the sandbox cannot.

Follow-ups, none blocking:
  - The implementer sandbox's missing writable temp dir makes any
    "evidence the suite ran" acceptance unsatisfiable by the implementer alone.
    That is a harness problem, not a contract problem, and it has now cost
    findings in three consecutive features.
  - The envelope-hygiene advisory is unaddressed across five rounds: a stale
    finding the implementer never cleared, claiming `Env: dev` was missing while
    its own summary declares it.
  - If pre-receipt sidecars should refuse rather than backfill, that is a
    contract change to AC1, not a defect in this implementation.
