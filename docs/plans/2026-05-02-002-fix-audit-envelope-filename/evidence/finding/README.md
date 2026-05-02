# Originating context — plan 005 audit envelope collision

This directory holds a snapshot of the evidence that motivated this plan.
Plan 005 history is intentionally NOT edited; this is a one-way copy of
the relevant signals.

## Files

- `originating-d013.jsonl` — D013 from plan
  `2026-05-01-005-feat-target-context-platform-fix`'s decisions.jsonl,
  recording the deferred follow-up. Contains the full reproduction
  details (filenames involved, mitigation taken, why deferred at the
  time).

## Reproduction snapshot (without re-running anything)

The collision plays out as follows when a plan ships ≥ 2 features and
each feature dispatches its own volley against the same `plan_dir/audit/`:

1. F001 volley dispatches → writes
   `audit/claude-implementer-i0.json` and
   `audit/codex-auditor-i0.json` (and i1 if iterated).
2. F002 volley dispatches against the SAME plan dir → writes the
   SAME filenames. F001's envelopes are overwritten in working tree.
3. F002's volley terminates; F001's audit history (in working tree)
   now reflects F002's volley, not F001's.

Plan 005 mitigated this by manual copy to
`docs/plans/2026-05-01-005-feat-target-context-platform-fix/evidence/f002/audit-original-volley/`
BEFORE F002's confirmation volley dispatched. F001's pre-confirmation-
volley state is also retrievable from git at commit `836c71d` (the F001
close-out) since those envelopes were committed before F002 ran.

## What the fix changes (forward-only)

New filename pattern: `{agent}-{role}-{feature_id}-i{n}.json`. Existing
envelopes at the old pattern are not renamed. Readers that hold a
`Path` to an old-pattern envelope continue to work because supervisor
consumes audit envelopes as `list[Path]` (accumulated during dispatch),
not via filename glob.
