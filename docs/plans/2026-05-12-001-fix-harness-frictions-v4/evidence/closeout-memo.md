---
status: operator_resolved
reason_class: spec_ambiguity
plan_id: 2026-05-12-001-fix-harness-frictions-v4
feature_id: F003
closed_at: 2026-05-12T17:53:30Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-12-001-fix-harness-frictions-v4 / F003

## Operator decision

This feature was closed under class `spec_ambiguity` after operator review of a `stopped_no_progress` terminal. The audit finding is recorded as non-defect; the close-out workflow generated this template, cleared `breaker:no_progress`, wrote the signoff envelope, and flipped `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 5 (see structured target_context.commands_run)

[F003] Repo: DontPanic  
Env: dev  
Project: (none)

Overall verdict: needs_changes.

FINDING (medium, correctness): Parse-warning findings do not match the F003-required category. Evidence: F003 requires `severity=advisory category=parsing`, but [supervisor.py](/Users/bayesian/Documents/GitHub/DontPanic/scripts/dontpanic_orchestrate/supervisor.py:2487) and [supervisor.py](/Users/bayesian/Documents/GitHub/DontPanic/scripts/dontpanic_orchestrate/supervisor.py:2505) emit `category: "correctness"`. Recommendation: either add schema support for `parsing` and emit it, or update the plan/spec to explicitly use the schema-supported category.

FINDING (medium, test_coverag...

## Rationale (operator)

F003 functional scope is delivered: every `shlex.split()` in the agent-output-parsing pipeline is wrapped with try/except (`command_guard.py:257`), the supervisor backstop `try/except ValueError` around `dispatch_volley`'s iter loop is in place (`supervisor.py:1565`, `2315`), three failure-mode tests cover unbalanced single-quote / unbalanced double-quote / trailing backslash, and the Plan 004 F002 reproducer test loads the real persisted envelope. Full sweep 1916 passed. The iter1 auditor raised two findings, both non-defect:

1. **Category `parsing` vs `correctness` (spec_ambiguity).** F003 features.json step 3 says findings should be `category=parsing`, but `claude/shared/schemas/v1.0/audit.schema.json:75` enumerates only `{correctness, security, performance, architecture, style, currency, redaction, test_coverage, documentation}` — `parsing` is not a valid value. The implementer's `category=correctness` is the only schema-valid path and matches existing convention at `audit_writer.py:313` + `supervisor.py:2438/2460`. Adding `parsing` to the enum would require an agent-conventions VERSION bump + subtree sync — out of scope for v4 lock-time correction. See D008.

2. **Test_coverage rigor (already-known v4.1 carry).** Auditor wants the Plan 004 F002 replay to drive the full `dispatch_volley` terminal path rather than just `_apply_target_accountability` + per-command guard. The implementer already upgraded from fabricated commands → real persisted envelope in iter1; the deeper full-volley integration shape pairs with the D007 strict-terminal-pin work already queued for v4.1. See D009.

No re-dispatch needed. Close-out class `spec_ambiguity` per v3 F003 taxonomy.

## Follow-ups

- v4.1 cleanup commit: bundle (a) `parsing` category enum addition + agent-conventions VERSION bump + subtree, (b) D007 strict-terminal-pin tightening, (c) D009 full-volley replay test for Plan 004 F002 reproducer.

## Evidence references

- `audit/signoff-2026-05-12-001-fix-harness-frictions-v4.json`
- `audit/codex-auditor-F003-i1.json` (latest auditor envelope)
- `audit/claude-implementer-F003-i1.json` (signed_off implementer at 1916 tests passing)
- `audit/no_progress_classification_F003_iter2.json`
- `decisions.jsonl` D008, D009

## Return Condition

Operator close-out for F003 (`spec_ambiguity`). The shlex-safe handling, backstop ValueError catch, and failure-mode tests are landed at 1916 tests passing; no schema-invalid category change required; v4.1 cleanup carries the `parsing` enum addition + test_coverage rigor.

