---
id: 2026-05-12-002-fix-harness-frictions-v4-1
title: Harness frictions v4.1 — parsing-category enum + test_coverage rigor
type: fix
tier: local
status: completed
date: "2026-05-12"
goal_type: infra
surfaces:
  - infra
  - external-api-wrap
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  no_progress_threshold: 2
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-12-001-fix-harness-frictions-v4
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
orchestration:
  parent_plan_id: 2026-05-11-001-infra-state-projection-adapters-meta
  spawn_reason: operator_manual
  depth_limit: 3
child_charter:
  kind: implementation
  parent_objective: "Discharge v4.1 carry items banked during the v4 plan close-out so the spec_ambiguity-class deviations and test_coverage rigor gaps don't accumulate into a third friction cluster."
  parent_acceptance_item: "v4 D008 (parsing-category schema mismatch), v4 D009 (Plan 004 F002 full-volley replay rigor), and the recurring test_coverage rigor pattern (v3 F002 D007 + v4 F002 D007 + v4 F003 D009) all closed."
  allowed_paths:
    - "scripts/dontpanic_orchestrate/supervisor.py"
    - "scripts/dontpanic_orchestrate/tests/**"
    - "claude/shared/schemas/v1.0/audit.schema.json"
    - "claude/shared/VERSION"
    - "claude/shared/models/**"
    - "claude/shared/CHANGELOG.md"
    - "docs/plans/2026-05-12-002-fix-harness-frictions-v4-1/**"
  forbidden_decisions:
    - "Do not break the audit.schema.json contract for existing fields — `parsing` is a strict addition to the category enum, not a rename."
    - "Do not regress any existing test in the current sweep (1928 baseline)."
    - "Do not modify supervisor.py outside the four parse-warning emission sites (2488, 2506 plus their command_guard.py:257 backstop) and the F004 broad-except catch in dispatch_volley."
    - "Do not bundle unrelated rigor improvements — stay tightly scoped to D007 + D009 patterns."
  return_condition_summary: "F001 + F002 pass; full sweep stays ≥1928 green; agent-conventions VERSION bumped to 1.8.0 in both upstream + DontPanic subtree mirror; parsing-category emission replaces correctness at the two F003 shlex warning sites."
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
description: |
  Discharge the v4 carry queue. Two features, both deferred from
  v4 plan close-out as the natural follow-up commit:
    * F001 (v4 D008): add `parsing` to the audit.schema.json
      category enum, bump agent-conventions 1.7.0 → 1.8.0, subtree
      sync into DontPanic claude/shared/, and flip the F003 shlex
      parse-warning emission from `category=correctness` to
      `category=parsing` at supervisor.py:2488 + 2506. This makes
      the F003 spec text (which literally said `parsing`) and the
      schema (which now allows `parsing`) consistent again. Without
      this, the next plan whose findings touch parse-failure
      classification will face the same spec_ambiguity branch.
    * F002 (v4 D009 + recurring test_coverage rigor pattern):
      replace permissive terminal assertions
      (`not in {blocked, blocked_no_findings, ...}`) with strict
      `== needs_changes` in the v4 F002 + F004 fixtures; add a
      full-volley `dispatch_volley` replay of the Plan 004 F002
      reproducer that asserts the volley reaches a clean terminal
      with parse-breaking input (not just that
      `_apply_target_accountability` doesn't crash).
motivation: |
  Two banking patterns surfaced during v4. Neither is a defect
  in the v4 code that landed; both are deferred-but-tracked
  rigor that wants closing before the next cluster trigger fires:

    * Spec_ambiguity → real fix. v4 F003 emitted shlex
      parse-warning findings as `category=correctness` because
      the schema didn't allow `parsing`. The implementer made
      the only schema-valid choice. v4 D008 documented the
      deviation as spec_ambiguity per the v3 F003 taxonomy and
      deferred the schema bump. v4.1 F001 makes the spec change
      real so future plans can use `category=parsing` literally
      without a second operator-resolved close-out.
    * Test_coverage rigor as a recurring pattern. v3 F002 D007,
      v4 F002 D007, v4 F003 D009 all banked the same shape:
      replay fixtures that exercise the unit under test but
      stop short of asserting the full volley terminal path.
      The codex auditor flags this consistently. Three
      occurrences across two plans = strong signal worth
      discharging as its own batched commit rather than letting
      it drift into a v5 cluster trigger.

  Both features are tightly scoped, low-risk, and the F004
  per-iter checkpointing landed in v4 gives a clean failure
  surface if the cross-repo subtree sync goes sideways.
---

# Harness Frictions v4.1

## Thesis

Two carry items from v4 plan close-out. Both deferred-but-tracked
during v4 dispatch as out-of-scope-for-locked-AC; neither is
contested. F001 closes a spec_ambiguity loop (parsing-category
enum addition makes the v4 F003 spec text + schema consistent);
F002 closes the test_coverage rigor pattern that recurred across
three v3/v4 features in a row. Tightly scoped — no new substrate,
no new primitives.

## Scope

In scope:

- **F001** (v4 D008 close — DontPanic subtree mirror only, per D003):
  in `claude/shared/schemas/v1.0/audit.schema.json`, add `parsing`
  to the category enum (now 10 values, was 9). Bump
  `claude/shared/VERSION` 1.7.0 → 1.8.0 and append a
  `claude/shared/CHANGELOG.md` entry citing v4 F003 D008.
  Update the Pydantic mirror at `claude/shared/models/` if it
  pins the set. Flip the two F003 shlex parse-warning emission
  sites in `scripts/dontpanic_orchestrate/supervisor.py` (lines
  2488 + 2506) from `category: "correctness"` to
  `category: "parsing"`, matching the F003 features.json step 3
  spec text literally. Update the unit tests in
  `test_shlex_safe_command_guard_f003.py` (lines 128 + 535) to
  assert `category == "parsing"`. Operator handles the upstream
  push to agent-conventions (cherry-pick + tag + push) out-of-band
  after F001 closes — not in implementer scope (D003).
- **F002** (v4 D009 + recurring D007 close): tighten test_coverage
  rigor at three concrete fixture sites flagged across v3 F002 +
  v4 F002 + v4 F003 auditor envelopes:
    * `test_verdict_blocked_reconciliation_f002.py:540-586` —
      replace the permissive
      `audit_status not in {blocked, blocked_no_findings, stopped_environmental_blocker}`
      assertion with strict `== needs_changes` (D007 carry).
    * `test_verdict_blocked_reconciliation_f002.py` Plan 010 F002
      fixture — replace the hand-coded fixture with a replay of
      the actual saved codex envelope at
      `docs/plans/2026-05-10-001-feat-printing-press-adapter-skill/audit/codex-auditor-F002-i0.json`
      (D007 #2 carry).
    * `test_shlex_safe_command_guard_f003.py` — add a new test
      that drives `dispatch_volley`'s full terminal path with the
      Plan 004 F002 reproducer envelope (parse-breaking input)
      and asserts the volley reaches a clean terminal
      (`signed_off` / `needs_changes` / `blocked` / `blocked_no_findings`)
      rather than crashing mid-run (D009 carry).

Out of scope:

- Adding additional category enum values beyond `parsing` (e.g.
  `evidence_shape`, `schema_validation`). One enum extension per
  bump; future additions get their own VERSION cut.
- Refactoring the F003 shlex wrappers themselves — they work and
  the auditor signed off on the substantive logic in v4 F003.
- The pre-flight env-capability check still deferred per v3
  D006 — separate scope, distinct friction class.
- Bundling unrelated test_coverage findings from other plans.

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance Summary

- **F001**: `agent-conventions/schemas/v1.0/audit.schema.json`
  category enum contains `parsing` as a 10th value. VERSION file
  is `1.8.0`. CHANGELOG.md notes the additive enum change.
  DontPanic `claude/shared/VERSION` mirrors `1.8.0`. Subtree
  diff against upstream is clean. `scripts/dontpanic_orchestrate/supervisor.py`
  lines 2488 + 2506 emit `category: "parsing"`. Unit tests in
  `test_shlex_safe_command_guard_f003.py` assert
  `category == "parsing"`. Full sweep ≥1928 green.
- **F002**: `test_verdict_blocked_reconciliation_f002.py` fixture
  uses strict `== needs_changes` terminal assertion. Plan 010 F002
  fixture replays the on-disk codex envelope rather than
  hand-coded findings. `test_shlex_safe_command_guard_f003.py`
  adds a `dispatch_volley`-driven replay of Plan 004 F002 input
  that asserts a clean terminal. Full sweep ≥1928 green.
