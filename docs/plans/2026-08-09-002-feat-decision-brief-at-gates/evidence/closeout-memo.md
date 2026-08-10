---
status: operator_finished
reason_class: operator_verified
plan_id: 2026-08-09-002-feat-decision-brief-at-gates
feature_id: F002
closed_at: 2026-08-10T01:11:46Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-08-09-002-feat-decision-brief-at-gates / F002

## Operator decision

This feature was finished under terminal class `operator_verified` via the operator-finish close path (no re-dispatch, no breaker required). operator_finish (terminal=operator_verified): operator verified the feature out-of-band — All three acceptance criteria verified directly against artifacts. AC1 (amended per D014): 117 plans validated against schema 1.15.0 and 1.16.0 produce identical per-plan exit codes — 23 non-zero under both, zero outcome changes (evidence/f002-validation-outcome-parity.txt). AC2: git status shows no existing plan file modified. AC3: cmp confirms claude/shared features.schema.json and features_model.py are byte-identical to agent-conventions; both read VERSION 1.16.0. The auditor's iter-0 needs_changes was correct at the time — the subtree pull and validation had not run. Both have since been completed by the operator (commits 2693583, f08bee0).. See evidence/closeout-memo.md. The close wrote the signoff envelope, recorded the terminal class in the operator-resolution sidecar, and flipped `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 7 (see structured target_context.commands_run)

[F002] Repo: DontPanic  
Env: dev  
Project: (none)

Overall verdict: **needs_changes**. The implementer’s Repo/Env/Project declaration is correct, structured context matches, and the empty `commands_run` contains no forbidden command shapes.

FINDING (high, correctness): F002 was not implemented. Evidence: `agent-conventions/VERSION` remains `1.10.0`, `claude/shared/VERSION` is `1.15.0`, `claude/shared` has no F002 changes, and the source/consumer feature-schema hashes differ (`2d9be9…` versus `77c96c…`; `cmp` exits 1). Recommendation: reconcile F001 onto the 1.15 sync baseline, bump and commit the next version, subtree-pull it into `claude/shared/`, then verify b...

## Rationale (operator)

No re-dispatch is warranted because the auditor's finding was acted on rather than
waived. Its recommendation was explicit — "reconcile F001 onto the 1.15 sync baseline,
bump and commit the next version, subtree-pull it into `claude/shared/`, then verify" —
and that is exactly the sequence that was executed: `b1ce20c` (v1.16.0 on the 1.15
baseline), `2693583` (subtree pull), `f08bee0` (all-plan validation evidence). The
finding is closed by the work, not by the close.

The root cause was mine. I merged F001 into `agent-conventions` `master` at 1.10.0
without checking which branch DontPanic's subtree actually tracks, which is
`chore/sync-upstream-1.15.0`. The volley caught it. `master` now holds a stale parallel
copy of the F001 work and should be reconciled or retired.

AC1 was amended under D014 before being claimed. As originally written it asserted the
validator exits 0 over every plan directory — a property of the baseline, not of this
change, and one that was never true (23 of 117 fail on pre-existing contract debt). The
amended criterion asserts what the feature actually owes: that no plan's validation
outcome changes. Verified by running the same 117 plans against both schema versions —
23 non-zero under each, zero outcome changes.

Two follow-ups worth filing rather than fixing here. First, the 23 failing plans are
real contract debt (missing `links.objective_contract`, `verified_by` not a list, stray
`evidence` key, naive `verified_at`, bad `evidence_refs.type`) and deserve their own
plan. Second, a process finding for the corpus: validating 117 plans by spawning one
subprocess per plan exceeds ten minutes and reads as a hung agent — almost certainly
what produced this auditor's "complete walks were stopped with exit 130." In a single
process the same work takes seconds. The feature was not too large; the verification
method was. Also recurring from D011: this memo again renders "(latest auditor envelope
not located)" immediately below a successfully lifted summary of that envelope.

## Evidence references

- `audit/signoff-2026-08-09-002-feat-decision-brief-at-gates.json`
- `audit/codex-auditor-F002-i0.json` — auditor verdict `needs_changes`, since remediated
- `evidence/f002-validation-outcome-parity.txt` — AC1, 117 plans × 2 schema versions
- `evidence/f002-all-plan-validation-1.16.0.txt` — full post-pull validation run

