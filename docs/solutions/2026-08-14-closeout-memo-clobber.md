---
title: close --operator-resolved silently destroys the previous feature's close-out record
tags: [orchestrator, closeout, data-loss, artifact-honesty]
date: 2026-08-14
status: root-caused, not fixed
---

# close --operator-resolved silently destroys the previous feature's close-out record

## Problem

Operator-resolving a second feature on the same plan overwrites the first
feature's close-out artifacts. No warning, no merge, no backup. The previous
memo is simply gone from the working tree, and the closed feature's
`evidence_refs` keep pointing at the path — so the record now cites a document
describing a **different feature**.

Found while closing `2026-08-13-001` F004, which destroyed F002's memo written
minutes earlier. It surfaced only because the close printed a path recognisable
from the previous close and it was checked rather than assumed.

## Root cause

Three artifacts are named per **plan** while the operation they record is per
**feature**:

```
closeout.py:60         CLOSEOUT_MEMO_RELPATH = Path("evidence") / "closeout-memo.md"
closeout.py:74         plan_dir / "audit" / f"operator-resolution-{plan_id}.json"
signoff_writer.py:191  plan_dir / "audit" / f"signoff-{plan_id}.json"
```

No filename varies by `feature_id`, so close N overwrites close N-1. The memo is
the worst of the three because it holds the operator's prose reasoning — the one
artifact that cannot be regenerated from machine state.

The audit envelopes get this right: `codex-auditor-F002-i1.json` carries both the
feature and the iteration. The close path just never adopted that convention.

## Blast radius (measured 2026-08-14)

Detected by walking every historical revision of each plan's `closeout-memo.md`
and counting distinct `feature_id:` values in its frontmatter — the decisive
test, since a memo that has held N feature ids destroyed N-1 records.

| repo | plans affected | memos destroyed |
|---|---|---|
| dontpanic | 10 | 33 |
| silex-crucible | 1 | 15 |
| quantre-migration | 2 | 3 |
| spindineswift | 0 | 0 |
| glam | 0 | 0 |
| **total** | **13** | **51** |

Worst single case: `silex-crucible/2026-07-28-001-infra-authoritative-runtime`,
where one memo file held 16 different feature ids.

A looser first pass — counting features with `verified_by` containing
`operator` — reported 51 *plans*. That over-counts: `verified_by: ['operator']`
is set by paths other than `close --operator-resolved`, and SpinDine and Glam
cleared entirely under the decisive test. Use the git-history method.

## Recovery

Every destroyed memo is in git history; nothing is permanently lost.

```bash
# list every feature whose memo passed through this file
git log --format=%H -- <plan>/evidence/closeout-memo.md | while read r; do
  git show "$r:<plan>/evidence/closeout-memo.md" | grep -m1 '^feature_id:'
done

# recover one
git show <sha>:<plan>/evidence/closeout-memo.md > <plan>/evidence/closeout-memo-<FEATURE>.md
```

Done for `2026-08-13-001` F002 (recovered from `ef3f2d5`), with both memos
stored per-feature and each feature's `evidence_refs` repointed.

## Fix

Name the artifacts for what they record:

- `evidence/closeout-memo-<FEATURE_ID>.md`
- `audit/operator-resolution-<plan_id>-<FEATURE_ID>.json`
- refuse to overwrite an existing artifact whose `feature_id` differs from the
  one being closed, rather than writing over it

The signoff envelope may be legitimately per-plan — that wants a decision rather
than a rename.

A migration should also fold recovered memos back into the affected 13 plans, or
at minimum leave a pointer so the surviving memo is not mistaken for the whole
record.

## Key learnings

- **A plan-scoped filename for a feature-scoped write is silent data loss.** The
  write succeeds, the exit code is zero, and the operator is told the close
  worked. Nothing in the output says a record was destroyed.
- This is the same failure family as the false gate render (plan
  `2026-08-10-001`) and the `sizing-lint (F001)` banner printed above
  `feature: F002` — an artifact confidently asserting something untrue about
  itself. It is the worst of the three: the false gate was reconstructible from
  the event, whereas an overwritten memo needs git.
- The bug had been live since at least 2026-05-12 and destroyed 51 records
  before anyone noticed, because the only symptom is a file quietly containing
  the wrong thing.

## References

- `2026-08-13-001-feat-lock-outcome-slices-proof` D012 — the finding as recorded
  on the plan where it surfaced
- `docs/plans/2026-08-10-001-fix-gate-identity-in-approval-copy/` — same failure
  family, different renderer
