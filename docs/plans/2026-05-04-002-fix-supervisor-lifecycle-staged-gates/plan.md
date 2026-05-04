---
id: 2026-05-04-002-fix-supervisor-lifecycle-staged-gates
title: Fix — Lifecycle-staged human-gate evaluation in the supervisor
type: fix
tier: cross-cutting
status: active
date: "2026-05-04"
description: |
  Stage human-gate evaluation across the dispatch lifecycle. The
  supervisor currently evaluates declared `human_gates` as a single
  upfront set — every gate (including `pre_merge`, which conceptually
  belongs *after* the auditor signs off) must be cleared before
  iteration 0 fires. Plan B fixes this by firing each declared human
  gate at its canonical lifecycle point. `pre_impl` blocks before
  implementer iteration 0; `pre_merge` blocks only when a candidate
  successful signoff is ready and before `signoff_writer` writes
  `passes:true`.

  Single feature. Volley execution (locked at the parent-sequence
  scoping turn). Behavioral semantic change with real auditor
  signal — adversarial review catches missed call sites, ordering
  bugs, and resume edge cases that grep cannot.

  Plan B touches **human gates only**. Circuit-breaker (`breaker:*`)
  timing is explicitly unchanged (D001). Resume-discipline CLI
  invariants (bare `dontpanic resume <plan>` exits 2) are explicitly
  preserved (D002). `gate-state.json` schema is **additive** —
  legacy `cleared_gates` field stays verbatim, two new optional
  fields layer on top (D004).
motivation: |
  The upfront-evaluation pattern was a known platform quirk — see
  D009 of plan 2026-05-03-001 and the gates-evaluated-upfront entry
  of `feedback_orchestrator_dogfood_lessons` memory. It surfaced
  repeatedly across Phase B (plan 2026-05-03-003): F002 and F003
  both required operators to fictionally pre-clear `pre_merge`
  before there was anything to approve. The workaround ("clear both
  gates upfront, ship, review on the operator's machine") is
  reliable but it is exactly the wrong shape — `pre_merge` should
  *be* the operator's review gate after the auditor signs off, not
  a ritual signature beforehand.

  Plan A (canonical module rename, commit `8edd953`) merged today.
  Plan B's diffs anchor on `dontpanic_orchestrate` from day zero —
  no rebase against the rename. Test isolation lessons from Plan A
  apply directly: the supervisor module caches state at first
  import, so Plan B's tests must NOT delete entries from
  `sys.modules` to force re-imports.

  Plan B itself runs under the OLD upfront-evaluation regime
  (since the staged behavior is not yet shipped). The operator
  clears both gates upfront when dispatching this plan. This is
  not a self-deadlock per the no-self-deadlocking-plans memory —
  the operator can still clear gates the same way every prior
  volley required. The lifecycle-staged behavior applies to plans
  run *after* Plan B merges.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  no_progress_threshold: 2
  wall_clock_hours: 3
  hard_stop: false
privacy_tier: internal
protected_paths:
  # Historical plan dirs are durable records; only this plan's own
  # new dir touches docs/plans/ in this commit boundary.
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - claude/shared/
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Single feature, three concrete behavior changes:

1. **`pre_impl` blocks before iteration 0** of the implementer
   phase. Evaluated AFTER plan load + capability checks but
   BEFORE the implementer subprocess spawns. Once cleared (via
   `dontpanic approve` / `dontpanic resume --gate pre_impl` /
   `dontpanic resume --all`), the implementer fires.

2. **`pre_merge` blocks only at candidate-signoff readiness.** It
   fires after the auditor's terminal verdict is `signoff` (no
   blocking findings) AND before `signoff_writer` would write
   `passes: true`. It does NOT fire when the run is terminating
   on `needs_changes`, `stopped_no_progress`,
   `stopped_diminishing_returns`, timeout, breaker stop, or any
   other non-success terminal state (D005).

3. **Additive `gate-state.json` schema.** The existing
   `cleared_gates` field is preserved verbatim; existing readers
   continue to work. Two new optional fields layer on top:

   - `gate_events`: per-clearance audit log
     `{gate, stage, cleared_at, cleared_by}`
   - `pending_stage`: which lifecycle stage is currently waiting
     (`"pre_impl"` | `"pre_merge"` | `null`)

   New staged-evaluation logic reads the new fields when present
   and falls back to legacy semantics (treat all gates as cleared
   if only `cleared_gates` is populated) when not.

## Out of scope (deliberate)

- **Circuit-breaker (`breaker:*`) timing.** Breakers retain their
  current evaluation hooks — they fire whenever the breaker module
  triggers (open-on-condition), not at lifecycle stage boundaries.
  Plan B touches **human gates only**. D001.
- **Resume-discipline CLI semantics.** Bare
  `dontpanic resume <plan>` MUST still exit 2 (per the
  resume-discipline plan invariant). Plan B does NOT alter the
  CLI surface beyond what is necessary to clear staged gates one
  at a time. D002.
- **New lifecycle stages beyond `pre_impl` and `pre_merge`.**
  `pre_audit` (per-iteration) and `post_merge` are deliberately
  reserved-but-not-implemented hooks. Opening either is a separate
  plan with its own acceptance contract. D003.
- **Schema replacement of `gate-state.json`.** Additive only —
  the existing `cleared_gates` field stays. New fields layer on
  top. D004.
- **Historical plan dirs / evidence / audit envelopes / memory
  entries.** Same durability invariant as Plan A's D003. The only
  `docs/plans/` entries touched in this commit are this plan's
  own new files. AC #16.

## Cross-cutting tightenings (operator-supplied)

Per pre-draft conversation. These constrain the implementer and
are checked by the auditor before pre-merge:

1. **Breaker gates stay OUT of lifecycle staging.** No
   `breaker:*` rewiring in Plan B. D001.
2. **Resume-discipline preserved.** Bare `dontpanic resume <plan>`
   exits 2 — Plan B does NOT walk lifecycle automatically on bare
   resume. D002.
3. **`pre_merge` fires only on candidate-success path.** Five
   non-success terminal states explicitly do NOT fire pre_merge.
   D005.
4. **Additive gate-state schema, not replacement.** Existing
   readers must continue to work without modification. D004.
5. **Acceptance includes runtime ordering tests.** Plan A's AC #11
   (no-shim-relay) discipline applied here: state-file checks
   alone are insufficient; tests must verify that the gate is
   evaluated at the right *time* in the dispatch flow. D006.

## Execution path

**Volley** — committed at the parent-sequence scoping turn.
State-machine semantic change benefits from adversarial review.
Audit-focus list mirrors Plan A's AC #11 discipline: each
acceptance item has a *runtime invariant* the auditor must verify,
not just a schema/grep check.

The volley pattern follows F002 of plan 003: pre-volley
audit-focus addendum committed standalone (so the volley git diff
is clean), then `dontpanic dispatch-from-plan` runs in the
background. Both gates cleared upfront before dispatch (the
operator runs Plan B under the OLD regime — see motivation
section above).

## Audit-focus addendum (review priorities, NOT new ACs)

Required reading before implementing OR auditing this feature:
D001-D006 of this plan's `decisions.jsonl` + Plan A's
`evidence/f001-closeout-memo.md` (canonical module surfaces and
test-isolation lessons).

The acceptance items below are the binding contract. The list
here is operator-supplied review priorities — areas where a
lifecycle-bug would silently break dispatch invariants. The
auditor must touch on EACH item explicitly in their findings
paragraph (PASS/CONCERN/FAIL per item, not silence). These do
NOT add new acceptance items; they sharpen the auditor's beam:

1. **`pre_impl` ordering.** Verify by parametric test that the
   gate is checked AFTER plan load + capability checks but
   BEFORE the implementer subprocess spawns. Not earlier (would
   race plan-load), not later (defeats the gate).
2. **`pre_merge` non-firing on failure paths.** Parametric test
   over `needs_changes`, `stopped_no_progress`,
   `stopped_diminishing_returns`, timeout, breaker stop. None of
   these fire `pre_merge`; the run terminates without ever
   evaluating the gate.
3. **`pre_merge` firing on success path.** When the auditor's
   terminal verdict is `signoff` AND no blocking findings,
   `pre_merge` fires before `signoff_writer.write_signoff(passes=True)`.
   Verified by intercepting the signoff write path with a mock.
4. **Schema additivity.** A `gate-state.json` containing only
   the legacy `cleared_gates` field loads without error. A file
   with the new fields populated loads and is consumed
   correctly. Mixed shapes (legacy + new) round-trip cleanly.
5. **Resume CLI invariants.** Bare `dontpanic resume <plan>`
   exits 2. `dontpanic approve <plan> <gate>` clears one gate.
   `dontpanic resume <plan> --gate <gate>` clears the named
   gate if it is the canonical pending one (else exits 2).
   `dontpanic resume <plan> --all` bulk-clears pending gates
   for the current stage. NO bare-resume code path walks
   lifecycle automatically.
6. **Breaker non-interaction.** Breakers continue to pause at
   the breaker module's own evaluation point, not at lifecycle
   stage transitions. The breaker module's existing gate-pause
   integration is unchanged; greppable assertion: zero diffs
   under `circuit_breakers.py` from this commit.
7. **Stale gate-state on resume / backwards compat.** If a plan
   was started under the old upfront regime and
   `gate-state.json` shows all gates cleared (legacy shape),
   the new lifecycle code treats both stages as pre-cleared and
   proceeds without re-prompting. Verified by fixture file.
8. **No double-fire (idempotency).** Once a stage's gates are
   cleared, the supervisor must not re-evaluate that stage on
   subsequent loop iterations or on resume. Idempotent.
9. **Test-isolation discipline.** Per the Plan A learning,
   tests for Plan B must NOT delete entries from `sys.modules`
   to force re-imports of `dontpanic_orchestrate.supervisor`
   (or any other module). Module-level state caching means
   such mutations pollute neighbouring tests. Use
   `record=True` warning capture + scoped monkeypatching
   instead.

## Known caveats explicitly NOT Plan B blockers

A. **600s subprocess timeout.** If the implementer hits the
   timeout but lands real work on disk, accept on direct review
   per the F002/F003-of-plan-003 pattern. This is exactly Plan
   C's scope.

B. **`test_ec5_classifier.py` still broken** post-rename. Plan
   D's scope. Exclude from full sweep with
   `--ignore=scripts/dontpanic_orchestrate/tests/test_ec5_classifier.py`.

C. **Canonical module is `dontpanic_orchestrate`** (Plan A
   merged 2026-05-04). All Plan B diffs anchor there.
   `jarvis_orchestrate` is the non-removing shim; do NOT touch
   shim files in Plan B.

## Acceptance summary

Binding contract is in `features.json` F001. Highlights:

- **Runtime ordering tests** (D006) covering the four lifecycle
  invariants: `pre_impl` blocks before impl, clearing allows
  impl, `pre_merge` does not block before impl/audit,
  `pre_merge` blocks only on candidate-success.
- **Additive `gate-state.json` schema** — legacy shape readable
  unchanged, new fields populated by new logic.
- **Resume-discipline preserved** — bare resume still exits 2.
- **Breaker timing unchanged** — zero diffs in
  `circuit_breakers.py`.
- **Backwards compat** — old upfront-cleared `gate-state.json`
  files are treated as pre-cleared at all lifecycle stages.
- **Full orchestrate suite** (excl. `test_ec5_classifier.py`)
  passes from the canonical path.
- **Sanitization clean. Ruff clean.**
- **`git diff --name-only` for this commit shows zero entries
  under `docs/plans/` outside this plan's own new directory.**
