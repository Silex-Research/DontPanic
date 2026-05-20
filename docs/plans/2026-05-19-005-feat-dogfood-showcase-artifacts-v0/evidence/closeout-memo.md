---
status: operator_resolved
reason_class: implementation_defect
plan_id: 2026-05-19-005-feat-dogfood-showcase-artifacts-v0
feature_id: F001
closed_at: 2026-05-20T05:25:10Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-19-005-feat-dogfood-showcase-artifacts-v0 / F001

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

Overall verdict: needs_changes. Implementer declared `Repo: DontPanic`, `Env: dev`, `Project: (none)` correctly, structured `target_context` matches, and I found no forbidden command shapes.

FINDING (high, security): `docs/showcase/` is exempted from the actual sanitization scan, so secret-shape scanning does not apply there. Evidence: `scripts/sanitization_check.py` adds `docs/showcase/` to `ALLOWED_PREFIXES`, and `main()` skips allowed paths before calling `scan_line`; a probe showed a fake AWS-key-shaped line under `docs/showcase/leaky.json` would be skipped even though `scan_line` detects it. Recommendation: spl...

## Rationale (operator — fill in)

<!--
Explain in 2-4 sentences:
  - Why the finding does not warrant a re-dispatch.
  - What spec/doc/convention change (if any) should follow to
    prevent the same friction next time.
  - Any follow-up tickets, plan IDs, or D-entries to file.
-->

## Evidence references

- `audit/signoff-2026-05-19-005-feat-dogfood-showcase-artifacts-v0.json`
- `(latest auditor envelope not located)`


## Return Condition

F001 shipped after hand-patching two real findings: (1) high/security — sanitization_check split: docs/showcase/ moved from ALLOWED_PREFIXES (which skipped ALL scanning) to new CAMPAIGN_IDS_OK_BUT_SCAN_SECRETS tier (campaign IDs OK but secret-shape regexes still apply). New allows_campaign_ids_only() predicate + scan_line(secrets_only=True) path + main() threads it through. (2) medium/test_coverage — added test_generator_with_four_targets_produces_expected_artifact_matrix covering the full v0 acceptance matrix (4 synthetic targets with disjoint artifact sets). Updated existing sanitization test to assert the split-policy contract. Full sweep 2072 passed / 7 skipped (+22 showcase tests including new 4-target fixture). Sanitization clean (1333 files). Plan 5 F001 ready for F002 (showcase docs + index).
