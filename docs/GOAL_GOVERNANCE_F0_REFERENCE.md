# Goal Governance F0 Reference

F0 configures the existing nested-orchestration substrate for the goal-governance
use case described in [GOAL_GOVERNANCE_V1.md](./GOAL_GOVERNANCE_V1.md).
It does not add runtime spawning automation.

## Triage

Source: `GOAL_GOVERNANCE_V1.md` §3.3, §6.3, §6.4.

Code:

- `GoalGapFinding`
- `GoalGapClusterContext`
- `classify_goal_gap_cluster()`

The classifier returns one of:

- `inline_fix`
- `child_plan`
- `follow_up_plan`
- `operator_deferred`

`child_plan` requires:

- at least `GOAL_GAP_MIN_FINDINGS_PER_CLUSTER` findings,
- at least one finding with severity `GOAL_GAP_MIN_SEVERITY_FOR_CHILD_PLAN` or higher,
- cluster coherence `subsystem_and_journey`.

The classifier is pure. It recommends a class; it never spawns a child plan.

## Caps

Source: `GOAL_GOVERNANCE_V1.md` §6.4 and F0 lock decisions.

Code:

- `GOAL_GAP_MAX_CHILD_PLANS_PER_PARENT_PASS`
- `GOAL_GAP_MAX_NESTING_DEPTH`
- `validate_goal_gap_child_plan_caps()`

Caps are refusal points for operator-approved spawning. They are not auto-spawn
triggers and they do not replace Plan 003 depth/cycle/signature guards.

## Child Charter

Source: `GOAL_GOVERNANCE_V1.md` §3.3 and §9.

Code:

- `GOAL_GAP_CHILD_CHARTER_TEMPLATE`
- `build_goal_gap_charter()`

Goal-gap child charters record:

- `parent_objective_contract_id`
- `gap_class`
- `cluster_scope`
- `severity`
- `surfaces_affected`
- `why_child_plan_not_feature`

These goal-gap fields are rendered as schema comments above a valid
`child_charter:` block. The builder validates them before rendering, while the
existing `ChildCharter(extra="forbid")` model remains unchanged and can still
parse the generated `child_charter:` block.

The rationale is required so future maintainers can understand why the gap was
handled as a child plan instead of an inline feature fix.

## Fan-In

Source: `GOAL_GOVERNANCE_V1.md` §3.3 and Plan 003 parent fan-in protocol.

Code:

- `GOAL_GAP_FAN_IN_MEMO_TEMPLATE`
- `parse_goal_gap_fan_in_memo_fields()`

The sibling parser validates goal-gap fields:

- `objective_contract_id:`
- `gap_class_closed:`

It reuses the existing `## Return Condition` parser and legal statuses:

- `satisfied`
- `blocked`
- `superseded`

## Evidence Paths

Source: `GOAL_GOVERNANCE_V1.md` §7.

Code:

- `GOAL_GOVERNANCE_EVIDENCE_PREFIX`
- `goal_governance_evidence_path()`

Layout:

```text
evidence/
  goal-governance/
    pre_impl/
    post_impl/
```

F1 writes pre-implementation sufficiency evidence. F2 writes post-implementation
completion evidence.

## Next Plan

F1 depends on F0. F1 should use these helpers when it implements objective
contracts and the pre-implementation sufficiency auditor.
