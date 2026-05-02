# F003 close-out memo — EC5 severity classifier (direct path)

**Plan:** `2026-05-01-005-feat-target-context-platform-fix`
**Feature:** F003
**Captured:** 2026-05-02 (post-implementation close-out)

## Why direct path (no volley)

F003's deliverable is a small, well-bounded platform patch:
- One pure helper module (`ec5_classifier.py`, ~140 lines) with three exports.
- One narrow wiring point (`build_audit` calls `apply_ec5_classifier_to_findings` between finding-extraction and status-derivation).
- One prompt-template paragraph addition (`EC5_AUDITOR_RULE` constant, embedded in `auditor_prompt`).

Acceptance was disambiguated across multiple prior D-entries before F003 implementation began: D005 (severity is platform-enforced, not trust-based), D008 (description preservation on downgrade), D010 (F001 close-out deferred meta-recursive HIGH to F002+F003), D011 (F002 manual remediation cycle), D012 (F002 confirmation-volley remediation including the verbatim-case-c structural-impossibility clarification).

A volley on this surface would test current review-loop instability, not the implementation. F002's two volleys already produced the relevant adversarial cases:
- Header-only false-positive no-op (real correctness defect, drove F002 MEDIUM remediation in D012; F003's classifier inherits the strict `parse_prelude_block`-based detection).
- Verbatim case-c byte-equality interpretive disagreement (D012 clarification still applies — F003 uses the same documented sanitization transform via `_load_fixture`).
- Forward-only proof regression (D012 LOW restoration; orthogonal to F003 scope).

The failure-taxonomy memory (`feedback_volley_failure_taxonomy.md`, captured during F002 close-out) names this exact scenario: when prior rounds have produced enough adversarial signal and the surface is well-bounded, additional volleys are more likely to produce `interpretive_disagreement`-class findings than `feature_defect`-class. The cost (tokens + diminishing-returns risk) is unjustified.

Operator-approved direct path on 2026-05-02. Strict scope discipline: no audit-filename collision work, no nested-orchestration work, no schema bump.

## Volley arc — none

No volley dispatched for F003. All adversarial validation came from prior F002 rounds (preserved verbatim under `evidence/f002/audit-original-volley/` and committed under `audit/`).

## Test + lint state at close-out

```
$ PYTHONPATH=scripts python3 -m pytest scripts/jarvis_orchestrate/tests/test_ec5_classifier.py -q
19 passed in 0.20s

$ PYTHONPATH=scripts python3 -m pytest scripts/jarvis_orchestrate/tests/ -q
447 passed, 6 skipped in 7.87s

$ ruff check scripts/jarvis_orchestrate/
All checks passed!

$ python3 scripts/sanitization_check.py
✓ no campaign IDs or secret shapes in sanitized surface (544 files scanned)
```

Test count delta: `428 → 447` (+19 F003 tests). Six skipped tests are pre-existing.

## Coverage summary

Per acceptance #2 — classifier verdicts on all 7 F001 fixtures (+ 1 synthetic malformed-prelude case):

| Fixture | Verdict | Why |
|---|---|---|
| case-a (raw) | `i0` | struct valid, no prelude in summary |
| case-a (post-F002 inject) | `none` | canonical prelude injected, values match struct |
| case-b (post-F002 inject) | `none` | same shape as case-a post-injection |
| case-c (golden) | `none` | already canonical, values match struct |
| case-d (struct absent) | `i1` | `validate_target_context` raises |
| case-e (empty env) | `i1` | struct invalid |
| case-f (commands without target) | `i1` | struct invalid |
| **case-g (value mismatch)** | **`i1`** | struct valid + prelude well-formed BUT env=prod ≠ struct env=dev — narrow-rule negative control |
| synthetic malformed prelude | `i0` | struct valid + header present + body malformed (parse raises) |

Aggregation behavior (per acceptance #4 + #5 + #7):
- Verdict `none` → drop EC5 finding.
- Verdict `i0` → set severity = `advisory` (mapped from abstract verdict via `EC5_VERDICT_SEVERITY`); preserve `issue` / `evidence` / `recommendation` / `code` verbatim.
- Verdict `i1` → leave finding untouched.
- Non-EC5 findings → pass through with same dict identity (no mutation).
- Input list never mutated (caller can introspect pre-classification state if needed for evidence packaging).

Backwards-compat (acceptance #10): findings without `code` field but with `issue` text matching `_EC5_TEXT_HEURISTIC` (regex anchored on `target<sep>context...prelude` bigram, separator ∈ {space, hyphen, period, underscore}) are detected and downgraded.

## Schema discipline (D006)

`audit.schema.json` is unchanged. The classifier's abstract `'i0'` verdict maps to the existing `'advisory'` severity enum value at the aggregation boundary. No new severity values, no new finding fields.

## Prompt template (acceptance #6 + #9)

`EC5_AUDITOR_RULE` constant added to `prompts.py` and embedded in `auditor_prompt` between finding-listing instructions and the final reply-format directive. Includes the value-mismatch carve-out explicitly:

> NEVER downgrade based on struct validity alone; value-mismatches are real findings even when struct is valid.

No agent retraining — prompt-as-context change only. The supervisor's classifier defensively re-applies the rule at finding-aggregation, so vendors slow to internalize the rule still produce correct severity (D005).

## Files in this commit

```
scripts/jarvis_orchestrate/ec5_classifier.py        (new — ~140 lines)
scripts/jarvis_orchestrate/audit_writer.py          (modified — 5-line classifier wiring)
scripts/jarvis_orchestrate/prompts.py               (modified — EC5_AUDITOR_RULE constant + auditor_prompt include)
scripts/jarvis_orchestrate/tests/test_ec5_classifier.py  (new — 19 tests)
docs/plans/2026-05-01-005-feat-target-context-platform-fix/decisions.jsonl  (modified — D014 close-out)
docs/plans/2026-05-01-005-feat-target-context-platform-fix/features.json    (modified — F003 passes:true)
docs/plans/2026-05-01-005-feat-target-context-platform-fix/evidence/f003-closeout-memo.md  (new — this file)
```

No audit/ envelopes touched (no volley ran). No prior-feature evidence mutated.

## Plan 005 status

After this commit, plan 005 is fully closed:
- F001 (helpers + fixtures) — `passes:true`, signed off 2026-05-02T07:30Z (D010)
- F002 (audit_writer auto-injection) — `passes:true`, signed off 2026-05-02T16:55Z (D011 + D012)
- F003 (severity classifier) — `passes:true`, signed off 2026-05-02T17:30Z (D014)

Queued follow-ups (per operator order):
1. Audit envelope filename collision (D013) — small platform plan after plan 005 close-out.
2. Nested orchestration (memory: `project_jarvis_nested_orchestration_v1.md`) — after the audit-filename plan.
