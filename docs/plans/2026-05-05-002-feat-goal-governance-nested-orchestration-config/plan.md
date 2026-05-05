---
id: 2026-05-05-002-feat-goal-governance-nested-orchestration-config
title: Plan F0 — Nested orchestration configuration for goal governance
type: feat
tier: cross-cutting
status: active
date: "2026-05-05"
description: |
  **Plan F0 of the Goal Governance V1 sequence** (per
  `docs/GOAL_GOVERNANCE_V1.md` §9). Configures the
  already-shipped nested-orchestration substrate
  (`2026-05-02-003-feat-nested-orchestration-v1`,
  `scripts/dontpanic_orchestrate/nested_orchestration.py`) for the
  new goal-governance use case. Does **not** rebuild nested
  orchestration; adds goal-gap-specific constants, templates, and a
  triage classifier next to the existing primitives.

  Without F0, F1's pre-impl sufficiency auditor and F2's post-impl
  completion auditor can detect "this should be a child plan," but
  the system has no consistent rails for spawning / chartering /
  returning-from goal-gap child plans. F0 is the rails.

  Scope is policy/configuration + a pure classifier helper +
  templates + tests + docs. **No runtime spawning automation.**
  Operator remains responsible for deciding whether to actually
  open a child plan based on the classifier's recommendation;
  the caps in F0 are safety rails, not auto-spawn triggers.

motivation: |
  Locked at the Goal Governance V1 design turn (commit `28880ab`).
  The §3.3 gap-triage rules + §6.3 cluster coherence rule + §6.4
  child-plan threshold + §5 vendor policy are policy decisions that
  the next governance layer (F1 + F2) will rely on. Without the
  policy codified into the existing nested-orchestration substrate,
  F1 surfaces "this should be a child plan" findings that have no
  defined target shape, and the operator has to improvise charter
  shape / return condition / evidence path for each one. That is
  exactly the substrate-vs-policy conflation that produces ad-hoc
  patches at the next layer up.

  F0 closes that gap before F1 starts dogfooding goal audits
  against Spin & Dine and Glam (see GOAL_GOVERNANCE_V1.md §9 Plan
  F1.5–F1.7 acceptance).

agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 1
  no_progress_threshold: 1
  wall_clock_hours: 2
  hard_stop: false
privacy_tier: internal
protected_paths:
  # Same protected set as Plans A–E.
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - claude/shared/
  # The shipped nested-orchestration core. F0 ADDS to this file
  # (constants/templates/classifier helper); it does NOT modify
  # the existing parent/child metadata, depth/cycle/signature
  # guards, or charter validation logic. Anything beyond additive
  # changes to the goal-gap-specific surface requires re-lock.
  - scripts/dontpanic_orchestrate/target_context_prelude.py
links:
  features: ./features.json
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Single feature, F001. Concrete deliverables:

1. **Goal-gap triage classifier** — pure function in
   `scripts/dontpanic_orchestrate/nested_orchestration.py` (or a
   sibling module if the file gets unwieldy) that takes a list of
   goal-audit findings + a cluster-coherence context and returns
   one of `{inline_fix, child_plan, follow_up_plan, operator_deferred}`
   per cluster.

2. **Threshold constants** added next to existing
   `DEFAULT_DEPTH_LIMIT`:

   ```python
   GOAL_GAP_MIN_FINDINGS_PER_CLUSTER: int = 3
   GOAL_GAP_MIN_SEVERITY_FOR_CHILD_PLAN: str = "medium"
   GOAL_GAP_MAX_CHILD_PLANS_PER_PARENT_PASS: int = 3
   GOAL_GAP_MAX_NESTING_DEPTH: int = 2  # inherits DEFAULT_DEPTH_LIMIT=3 as platform cap
   ```

3. **Goal-gap child-charter template** — a new module-level
   `GOAL_GAP_CHILD_CHARTER_TEMPLATE` constant + a builder helper
   that requires:

   - `parent_objective_contract_id`
   - `gap_class` (string identifier from goal audit findings)
   - `cluster_scope` (subsystem + journey)
   - `severity` (highest in cluster)
   - `surfaces_affected` (list)
   - `why_child_plan_not_feature` (operator-supplied rationale, NON-EMPTY required)

4. **Goal-gap return-condition template** — extends the existing
   `## Return Condition` parser to recognize a goal-gap-specific
   contract: child must produce evidence that (a) its objective
   contract is satisfied AND (b) the parent's named gap class is
   addressed. Default status enum stays `{satisfied, blocked,
   superseded}` per `_LEGAL_STATUSES`; F0 does NOT add new
   statuses.

5. **Evidence path conventions** — `evidence/goal-governance/`
   sub-tree with two passes:

   ```
   evidence/goal-governance/pre_impl/sufficiency-findings.json
   evidence/goal-governance/post_impl/completion-findings.json
   evidence/goal-governance/post_impl/journey-walks/<journey>.json
   ```

   F0 only defines the convention + constant for the path prefix;
   F1/F2 actually write to it.

6. **Parent fan-in memo — sibling parser, NOT extension.** Add
   `parse_goal_gap_fan_in_memo_fields(memo_path) -> dict` as a
   sibling to the existing fan-in memo parser, NOT an extension
   of it. The sibling calls `parse_return_condition_section()`
   first to reuse status validation, then validates additional
   goal-gap-specific required fields: `objective_contract_id:`
   and `gap_class_closed:`. Existing generic fan-in parser
   behavior is unchanged — touching it would risk regressing
   non-goal-gap plans. (Per amendment at D001 lock turn.)

7. **Tests** under
   `scripts/dontpanic_orchestrate/tests/test_goal_governance_config.py`:

   - Triage classifier returns correct class for representative
     finding clusters.
   - Charter builder rejects missing `why_child_plan_not_feature`.
   - Cap enforcement: synthesizing 4 child plans against one
     parent triggers the cap.
   - Goal-gap child charter inherits Plan 003 anti-recursion
     (depth/cycle/signature) without bypass.
   - Evidence path constant matches the documented convention.

8. **Documentation** — short reference page at
   `docs/GOAL_GOVERNANCE_F0_REFERENCE.md` mapping the constants
   and templates F0 adds against the GOAL_GOVERNANCE_V1.md
   policy sections. Future maintainers can read either side and
   trace to the other.

## Out of scope (deliberate)

- **Runtime spawning automation.** The classifier is a pure
  function; nothing in F0 actually spawns a child plan. Operator
  decides + invokes existing nested-orchestration spawn machinery
  (which already works per `2026-05-02-003`).
- **Modifying existing nested-orchestration core logic.**
  Parent/child metadata, depth/cycle/signature guards, charter
  parser, return-condition parser, commit_policy enforcement —
  all unchanged. F0 only ADDS goal-gap-specific constants,
  templates, and a classifier helper next to them.
- **F1 sufficiency auditor implementation.** That is Plan F1.
- **F2 completion auditor implementation.** That is Plan F2.
- **MCP work.** That is Plan G.
- **Dashboard / visibility surface.** That is Plan H.
- **OpenClaw integration.** None needed — locked per Goal
  Governance V1 §6.7.
- **Cross-instance coordination.** Out of scope; tracked as a
  Plan H scope decision or a separate Plan I (per
  GOAL_GOVERNANCE_V1.md §9 Plan H entry).

## Locked decisions (operator-supplied at F0 lock turn)

1. **F0 configures the existing nested-orchestration substrate;
   does NOT redesign it.** D001.
2. **F0 is a prerequisite to F1.** D002.
3. **Child plan spawning remains explicit / operator-approved.**
   D003 — caps are safety rails, not auto-spawn triggers.
4. **Goal-gap child plans inherit Plan 003 anti-recursion rules**
   (depth, cycle, repeated-finding signature). D004.
5. **Evidence path convention** is `evidence/goal-governance/<pass>/...`
   per GOAL_GOVERNANCE_V1.md §9 Plan F0.6. D005.
6. **`why_child_plan_not_feature` rationale is required** on
   every spawned charter. D006.
7. **No new return-condition statuses** beyond the existing
   `{satisfied, blocked, superseded}` enum. D007.
8. **Direct-path execution.** Mechanical configuration + pure
   classifier + templates + tests; no semantic decisions for an
   auditor to debate. D008.
9. **Unknown severity is invalid for goal-gap triage and raises
   `ValueError`** — no silent fallback to "below threshold."
   Malformed auditor output should fail loudly so it can be fixed
   upstream rather than masking real findings. D010.

## Execution path

**Direct.** Same rationale as Plans A, C-F001/F002, D, E:
mechanical config + tests, deterministic acceptance, no auditor
debate surface. Volley quota unjustified.

## Acceptance summary

Binding contract is in `features.json` F001. Highlights:

- All 8 deliverables shipped (classifier, constants, charter
  template, return-condition reuse, evidence path helper,
  goal-gap fan-in sibling parser, typed input structures, tests,
  docs reference).
- Existing nested-orchestration tests still green (zero regressions
  vs Plan D's 979/6 baseline).
- Goal-gap-specific tests cover classifier, charter rejection
  on missing rationale, cap enforcement, anti-recursion
  inheritance, evidence path constant, unknown-severity rejection.
- **Additive-only invariant** (refined wording per amendment at
  D001 lock turn) — all of:
  - no behavior changes to existing public APIs;
  - no changes to existing Pydantic model fields;
  - no changes to existing guard conditions
    (depth/cycle/signature);
  - no changes to existing return-condition statuses
    (`{satisfied, blocked, superseded}`);
  - additive helpers / constants / templates / typed structures
    only, plus `__all__` exports as needed.
- Ruff clean. Sanitization clean.
- F0 commits before F1 lock.
