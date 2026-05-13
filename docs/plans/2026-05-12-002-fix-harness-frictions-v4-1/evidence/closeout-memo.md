---
status: operator_resolved
reason_class: spec_ambiguity
plan_id: 2026-05-12-002-fix-harness-frictions-v4-1
feature_id: F002
closed_at: 2026-05-12T23:04:25Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-12-002-fix-harness-frictions-v4-1 / F002

## Operator decision

This feature was closed under class `spec_ambiguity` after operator review of a `stopped_no_progress` terminal. The audit finding is recorded as non-defect; the close-out workflow generated this template, cleared `breaker:no_progress`, wrote the signoff envelope, and flipped `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 3 (see structured target_context.commands_run)

[F002] Repo: DontPanic  
Env: dev  
Project: (none)

Overall verdict: needs_changes. Implementer target context is correctly declared as `{Repo: DontPanic, Env: dev, Project: (none)}`, and their recorded pytest commands contain no forbidden command shapes.

FINDING (high, correctness): The required strict `needs_changes` terminal assertion is still not implemented. Evidence: `test_verdict_blocked_reconciliation_f002.py` now asserts `iter0_data["audit_status"] == "needs_changes"` but asserts the actual volley terminal as `result.final_status == "signed_off"` at lines 630-637. Recommendation: make the fixture support a strict supervisor terminal assertion for `needs_...

## Rationale (operator)

Functional scope delivered: 1929 tests passing (+1 from v4.1 F001), Plan 010 F002 fixture loads on-disk envelope via `PLAN_010_F002_REAL_FINDINGS` (acceptance #2 delivered), new `test_plan_004_f002_replay_full_dispatch_volley_reaches_clean_terminal` drives full `dispatch_volley` end-to-end with parse-breaking commands_run via mocked `_ParseBreakingExecutor` (acceptance #3 in spirit). Two non-defect findings:

1. **Strict-pin design disagreement (third occurrence — pattern, not defect).** Auditor wants `result.final_status == "needs_changes"`; implementer pinned `iter0_data["audit_status"] == "needs_changes"` instead. Implementer's articulate rationale: prior strict-pin attempts (v3 F002 D007, v4 F002 D007) coupled the test to incidental no-progress threshold mechanics. Their fix widens the fixture (round 0 replays the real envelope, round 1 returns synthetic signoff) and pins the strict assertion on round 0's on-disk audit envelope — the data-shape invariant rather than the supervisor's terminal mechanic. Both interpretations of "strict terminal assertion" are defensible. See D005.

2. **Plan 004 F002 envelope mismatch.** Spec said "load the on-disk envelope (parse-breaking input)"; the actual on-disk envelope has CLEAN commands_run (5 well-formed pytest/ruff/python invocations). The original D025 shlex crash happened during the run but the persisted envelope captured commands cleanly. Implementer correctly synthesized parse-breaking prose to actually exercise the F003 wrapper. Spec self-contradiction documented in D005.

(Third advisory finding was the recurring codex-sandbox-can't-run-pytest environmental — not actionable.)

## Follow-ups

- v5 plan candidate: strict-pin design tension has now surfaced 3 times across v3 F002 / v4 F002 / v4.1 F002. Worth either (a) explicit spec language clarifying volley-terminal vs envelope-verdict pin, or (b) a harness helper that pins both invariants atomically.
- v5 plan candidate: post-F003 audit envelope re-capture step that records the parse-breaking commands_run string verbatim into a replay fixture, since the on-disk envelope's normalized commands_run loses the breaking shape.
- v4.x candidate: D031 supervisor-subprocess-timeout class recurred again at iter0. F004 stage-aware backstop caught it cleanly (synthetic envelope) — no orphaned state.

## Evidence references

- `audit/signoff-2026-05-12-002-fix-harness-frictions-v4-1.json`
- `audit/codex-auditor-F002-i1.json` (latest auditor envelope)
- `audit/claude-implementer-F002-i1.json` (signed_off at 4.22M tokens, 1929 tests passing)
- `audit/no_progress_classification_F002_iter2.json`
- `decisions.jsonl` D005

## Return Condition

status: satisfied

Operator close-out for F002 (`spec_ambiguity`). Plan 010 F002 envelope replay landed, Plan 004 F002 full-volley replay landed (with synthetic parse-breaking input since on-disk envelope has clean commands), 1929 tests passing. Strict-pin design tension banked as v5 candidate per D005.

