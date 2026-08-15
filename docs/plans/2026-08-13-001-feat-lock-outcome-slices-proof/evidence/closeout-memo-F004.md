---
status: operator_finished
reason_class: signed_off_adjacent
plan_id: 2026-08-13-001-feat-lock-outcome-slices-proof
feature_id: F004
closed_at: 2026-08-14T19:45:22Z
latest_audit_status: signed_off
---

# Closeout memo — 2026-08-13-001-feat-lock-outcome-slices-proof / F004

## Operator decision

This feature was finished under terminal class `signed_off_adjacent` via the operator-finish close path (no re-dispatch, no breaker required). operator_finish (terminal=signed_off_adjacent): the auditor signed off; a downstream gate blocked the automated finalize. Operator accepted the feature as merge-ready. See evidence/closeout-memo.md. The close wrote the signoff envelope, recorded the terminal class in the operator-resolution sidecar, and flipped `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 7 (see structured target_context.commands_run)

[F004] Repo: DontPanic  
Env: dev  
Project: (none)

Overall verdict: **signed_off**. All six F004 acceptance clauses are implemented; target declarations match, no forbidden command shapes were recorded, and no F002 scoring or F005 durability logic changed. FINDING (advisory, documentation): the implementer summary is truncated mid-test name and records the targeted Python probe as a placeholder rather than its reproducible command, although the corresponding regression exists and collects successfully. Ruff, schema validation, patch hygiene, and both targeted in-memory probes passed. The focused pytest execution was blocked before collection because the read-only...

## Rationale (operator)

The auditor signed off at iteration 1 with no correctness findings. The `blocked`
terminal is the same patch_completeness catch-22 that closed F002: the check
fails on *untracked OR unstaged_modified*, and the implementer necessarily
writes its test file during the volley, so no amount of operator pre-staging
clears it. Staged by hand afterwards; 99 tests pass across the F002 and F004
suites.

Three earlier rounds under the previous contract found real and progressively
deeper defects, all now fixed:

  - partial overlap — locked `{F001,F002}` paired with live `{F001,F003}`
    consumed the live slice, so F003's proof was owed by nobody;
  - a positional fallback that survived for records naming no features, so
    changing only a live slice's number changed the obligation set;
  - duplicate identities — two slices naming the same proving features reported
    false drift when swapped, because pairing was greedy by live order.

`_pair_locked_with_live` now matches identity exactly, never consults the
numeric index, and disambiguates same-identity slices by capability text.
Where identity and capability both match, the slices are genuinely
interchangeable and the code says so rather than implying a distinction the
data cannot support.

Defect found while closing this feature, and repaired here: `close
--operator-resolved` writes a single `evidence/closeout-memo.md` per PLAN, not
per feature. Closing F004 silently overwrote F002's memo, leaving F002's
`evidence_refs` pointing at a document describing a different feature — an
artifact asserting something untrue, which is the exact failure class this plan
and 2026-08-10-001 exist to fix. F002's memo was recovered from commit ef3f2d5
and both are now stored per-feature as `closeout-memo-F002.md` and
`closeout-memo-F004.md`, with each feature's refs repointed. The tool still has
the bug. See D012.

Standing advisory, unaddressed across four rounds: the implementer's audit
envelope carries stale or non-replayable content — a resolved finding it never
cleared, a truncated summary, and a probe recorded as a placeholder rather than
its actual command.
