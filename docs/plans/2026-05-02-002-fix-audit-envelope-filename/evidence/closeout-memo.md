# F001 close-out memo — audit envelope filename includes feature_id (direct path)

**Plan:** `2026-05-02-002-fix-audit-envelope-filename`
**Feature:** F001
**Captured:** 2026-05-02 (post-implementation close-out)

## Why direct path (no volley)

F001's deliverable is a small, mechanical writer/callsite/test change:

- Single writer mutation in `audit_writer.write` — added required `feature_id` kwarg, regex-validated, used in filename construction.
- Two production callsite updates in `supervisor.py` (dispatch_single_agent line 595, dispatch_volley line 1342).
- One docstring update in `transcript.py`.
- Test-side mechanical updates: 16 sites in `test_audit_writer_normalize.py`, 1 in `test_ec5_classifier.py`, 2 glob patterns in `test_audit_writer_f002_supervisor_integration.py`.
- New test file with 22 tests covering all 12 acceptance clauses.

Acceptance was heavily disambiguated at lock time (D001 + D002), and the change is mechanical: no design space to explore, no interpretive lookup, no severity classification. A volley would test review-loop instability, not implementation correctness — exactly what plan 005's failure-taxonomy memory (`feedback_volley_failure_taxonomy.md`) names as the trigger condition for direct-path delivery.

Operator-approved direct path on 2026-05-02. Strict scope discipline: no audit_id payload changes, no migration of historical envelopes, no nested orchestration, no schema bump.

## Volley arc — none

No volley dispatched for F001. The change is its own validation: the new test file's collision-free + negative + structural proofs together establish the acceptance contract. Plan 005's preserved volley envelopes serve as the old-pattern readability fixture.

## Test + lint state at close-out

```
$ PYTHONPATH=scripts python3 -m pytest scripts/jarvis_orchestrate/tests/test_audit_filename_feature_id.py -q
22 passed in 1.28s

$ PYTHONPATH=scripts python3 -m pytest scripts/jarvis_orchestrate/tests/ -q
469 passed, 6 skipped in 33.17s

$ ruff check scripts/jarvis_orchestrate/
All checks passed!

$ python3 scripts/sanitization_check.py
✓ no campaign IDs or secret shapes in sanitized surface (551 files scanned)
```

Test count delta: `447 → 469` (+22 plan-002 F001 tests). Six skipped tests are pre-existing.

## Coverage summary (per acceptance #1-#12)

| Acceptance clause | Coverage |
|---|---|
| #1 — filename includes feature_id, regex-validated | `test_filename_includes_feature_id`, `test_valid_feature_id_pattern_matches_features_schema_regex` |
| #2 — both dispatch paths thread feature_id | `test_dispatch_volley_writes_filename_with_feature_id`, `test_dispatch_single_agent_writes_filename_with_feature_id` |
| #3 — collision-free F001 + F002 in same plan_dir | `test_collision_free_two_features_one_plan`, `test_collision_free_two_features_via_supervisor` |
| #4 — old-pattern envelope readable via supervisor read paths | `test_old_pattern_envelope_remains_readable` (uses real plan 005 envelope) |
| #5 — no filename-pattern globs in readers | `test_no_filename_pattern_globs_in_readers` (structural source scan of consumer modules) |
| #6 — iteration sequencing within feature | `test_filename_iteration_within_feature` |
| #7 — no historical rename / no migration | Auditor reads diff; no migration code added; verified by `git diff` showing no `docs/plans/*/audit/` walks |
| #8 — no schema change | `audit.schema.json` untouched (verified by diff) |
| #9 — negative-input proof, no-partial-artifact | `test_invalid_feature_id_raises_no_partial_artifact` (parametrized over 13 invalid inputs) |
| #10 — plan 005 untouched | Used `evidence/f002/audit-original-volley/claude-implementer-i0.json` as readability fixture (read-only); plan 005 history not edited |
| #11 — docstrings updated | `audit_writer.write` + module docstring + `transcript.py` HEADER all reference new pattern |
| #12 — existing test modules stay green | Full suite: 469 + 6 skipped (was 447 → +22 from this feature, no regressions) |

## Backwards-compat verification

- `audit_writer.write` signature change is platform-internal; the only callers are 2 production sites in `supervisor.py` + ≤ 17 test-harness sites — all updated in this commit.
- Old-pattern envelopes from plan 005 (e.g. `claude-implementer-i0.json`, no feature_id) remain readable: tested via `circuit_breakers.check_diminishing_returns` + `circuit_breakers.check_convergence_collapse` + `prompts._findings_block` consuming a real plan 005 envelope at the old pattern. All return without error.
- Structural no-glob proof: scanned `circuit_breakers.py`, `prompts.py`, `supervisor.py`, `transcript.py` for old-pattern hard-coded filename regexes (`-i\d+\.json`, `-implementer-i`, `-auditor-i`). None present.

## Schema discipline

`audit.schema.json` and `features.schema.json` are unchanged. The new validation regex (`^F\d{3}$`) is a runtime check at `audit_writer.write` boundary; the source-of-truth regex still lives in `features.schema.json` `$defs.feature.properties.id.pattern`. A drift-detector test (`test_valid_feature_id_pattern_matches_features_schema_regex`) reads both literals and asserts equality — future schema bumps will surface as a test failure rather than silent drift.

## Files in this commit

```
scripts/jarvis_orchestrate/audit_writer.py                       (mod — +13/-3)
scripts/jarvis_orchestrate/supervisor.py                         (mod — 2 callsites)
scripts/jarvis_orchestrate/transcript.py                         (mod — docstring)
scripts/jarvis_orchestrate/tests/test_audit_filename_feature_id.py  (new — 22 tests)
scripts/jarvis_orchestrate/tests/test_audit_writer_normalize.py     (mod — sed-pass feature_id="F001" through 16 callsites + _audit_filename helper)
scripts/jarvis_orchestrate/tests/test_audit_writer_f002_supervisor_integration.py  (mod — glob pattern relaxed to drop hard-coded `-i*` shape)
scripts/jarvis_orchestrate/tests/test_ec5_classifier.py          (mod — 1 callsite gets feature_id="F001")
docs/plans/2026-05-02-002-fix-audit-envelope-filename/decisions.jsonl  (mod — D003 close-out)
docs/plans/2026-05-02-002-fix-audit-envelope-filename/features.json    (mod — F001 passes:true with evidence_refs)
docs/plans/2026-05-02-002-fix-audit-envelope-filename/evidence/closeout-memo.md  (new — this file)
```

No audit/ envelopes touched. No prior-plan evidence mutated. No schema changes.

## Plan 002 status

After this commit, plan 002 is fully closed (single feature):
- F001 (audit envelope filename includes feature_id) — `passes:true`, signed off 2026-05-02T18:30Z (D003)

Queued follow-ups:
1. **Nested orchestration plan** — design captured in memory `project_jarvis_nested_orchestration_v1.md`. Slot per operator queue order (was: after audit-filename close-out).
