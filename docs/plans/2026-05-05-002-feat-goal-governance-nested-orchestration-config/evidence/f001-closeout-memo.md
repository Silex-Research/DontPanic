# F001 close-out memo — 2026-05-05

Plan: `2026-05-05-002-feat-goal-governance-nested-orchestration-config`
Feature: F001 — Goal-gap triage and child-plan configuration.

## Direct-path rationale

F001 is policy/configuration on top of the already-shipped nested orchestration substrate. The design surface was locked in `GOAL_GOVERNANCE_V1.md` and this plan's D001-D010 decisions; the implementation is additive constants, typed inputs, pure helpers, templates, tests, and a reference doc. No runtime spawning automation was added.

## What landed

| File | Change | Role |
|---|---|---|
| `scripts/dontpanic_orchestrate/nested_orchestration.py` | Added `GOAL_GAP_*` thresholds, `_GOAL_GAP_SEVERITY_RANK`, `GoalGapFinding`, `GoalGapClusterContext`, `classify_goal_gap_cluster()`, `validate_goal_gap_child_plan_caps()`, `GOAL_GOVERNANCE_EVIDENCE_PREFIX`, `goal_governance_evidence_path()`, `GOAL_GAP_CHILD_CHARTER_TEMPLATE`, `build_goal_gap_charter()`, `GOAL_GAP_FAN_IN_MEMO_TEMPLATE`, and `parse_goal_gap_fan_in_memo_fields()` | Goal-governance configuration surface for F1/F2 |
| `scripts/dontpanic_orchestrate/tests/test_goal_governance_config.py` | New focused test file, 18 tests | Classifier, severity validation, cap enforcement, charter builder, inherited guards, fan-in parser, and evidence-path coverage |
| `docs/GOAL_GOVERNANCE_F0_REFERENCE.md` | New reference doc | Maps F0 additions to `GOAL_GOVERNANCE_V1.md` and documents the no-auto-spawn boundary |

## Acceptance coverage

| Area | Result |
|---|---|
| Triage classifier | `classify_goal_gap_cluster()` is pure and returns `inline_fix`, `child_plan`, `follow_up_plan`, or `operator_deferred` from typed `GoalGapFinding` / `GoalGapClusterContext` inputs. |
| Child-plan threshold | `child_plan` requires at least 3 findings, at least one medium+ finding, and `coherence_rule == "subsystem_and_journey"`. Negative cases cover advisory-only clusters and incoherent clusters. |
| Unknown severity | `GoalGapFinding(severity="bogus")` raises at construction time; `build_goal_gap_charter(severity="bogus", ...)` raises at builder time. No silent fallback. |
| Cap enforcement | `validate_goal_gap_child_plan_caps()` rejects the 4th child and rejects child creation beyond `GOAL_GAP_MAX_NESTING_DEPTH = 2`; builder calls the cap helper before rendering. |
| Charter rationale | `build_goal_gap_charter()` requires `why_child_plan_not_feature` and rejects short rationale text. |
| Anti-recursion inheritance | Existing depth, cycle, and repeated-finding signature guards still refuse invalid goal-gap child plans. |
| Return-condition status | Existing `{satisfied, blocked, superseded}` parser handles goal-gap memos unchanged. |
| Goal-gap fan-in parser | `parse_goal_gap_fan_in_memo_fields()` is a sibling parser that reuses `parse_return_condition_section()` and requires `objective_contract_id:` plus `gap_class_closed:`. |
| Evidence paths | `goal_governance_evidence_path()` produces `evidence/goal-governance/{pre_impl|post_impl}/...` and rejects absolute or parent-directory artifact escapes. |
| Reference doc | `docs/GOAL_GOVERNANCE_F0_REFERENCE.md` links F0 helpers and constants back to Goal Governance V1 sections. |

## Additive invariant

D001's behavioral additive invariant is preserved:

- no behavior changes to existing public APIs;
- no changes to existing Pydantic model fields;
- no changes to existing depth / cycle / signature guard behavior;
- no changes to existing return-condition statuses;
- additive helpers, constants, templates, typed structures, and `__all__` exports only.

`audit_writer.py` is untouched. The severity rank table lives in `nested_orchestration.py` as locked. The generic fan-in parser is unchanged; goal-gap fan-in parsing is a sibling helper.

The goal-gap charter builder renders the new goal-gap context fields as schema comments above the generated `child_charter:` block. That keeps the existing `ChildCharter(extra="forbid")` model valid without weakening D006's builder-time requirement that those fields are supplied and validated.

## Verification

| Check | Result |
|---|---|
| Pre-flight baseline | 979 passed, 6 skipped before F0 implementation |
| Focused F0 tests | 18 passed in 0.12s |
| Full orchestrate suite | 997 passed, 6 skipped, 1 warning in 35.74s |
| Test delta | +18 exactly equals the new F0 test file count; zero regressions |
| Ruff check | clean on touched F0 code/test files |
| Ruff format check | clean on touched F0 code/test files |
| Sanitization | 0 findings, 725 files scanned |
| Plan validation | Plan F0 validates against agent-conventions v1.3.1 |

The single warning is the pre-existing Python-version support warning from `google.api_core` during legacy shim compatibility tests.

## F1 handoff

F1 can now consume the F0 surface directly:

- use `GoalGapFinding` and `GoalGapClusterContext` as the sufficiency auditor's goal-gap input shape;
- call `classify_goal_gap_cluster()` to recommend inline fix vs child plan vs follow-up vs operator-deferred;
- call `build_goal_gap_charter()` only after operator approval to prepare a child-plan charter;
- write pre-impl sufficiency evidence under `evidence/goal-governance/pre_impl/`;
- parse child fan-in memos with `parse_goal_gap_fan_in_memo_fields()`.

F0 deliberately does not spawn children automatically and has no MCP, OpenClaw, dashboard, or runtime-evidence dependency.
