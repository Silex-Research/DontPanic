---
id: 2026-05-19-003-fix-plan-schema-orchestration-fields
title: Plan schema mismatch fix — orchestration / child_charter / commit_policy
type: fix
tier: local
status: active
date: "2026-05-19"
goal_type: infra
surfaces:
  - infra
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
  - 2026-05-12-002-fix-harness-frictions-v4-1
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
  parent_objective: "Close the silent schema-vs-runtime mismatch where every locked plan since v3 uses orchestration/child_charter/commit_policy keys in plan.md frontmatter that strict jsonschema validation rejects as additionalProperties:false violations. Quiet timebomb if a future doctor hardens validation."
  parent_acceptance_item: "Roadmap 2026-05-19 Plan 3: schema v1.9.0 lands with orchestration/child_charter/commit_policy as documented additive properties; all existing locked plans validate clean; doctor gains --validate-plans-strict check that finds zero blockers."
  allowed_paths:
    - "claude/shared/schemas/v1.0/plan.schema.json"
    - "claude/shared/schemas/v1.0/models/plan_model.py"
    - "claude/shared/VERSION"
    - "claude/shared/CHANGELOG.md"
    - "scripts/dontpanic_doctor.py"
    - "scripts/dontpanic_orchestrate/tests/**"
    - "docs/plans/2026-05-19-003-fix-plan-schema-orchestration-fields/**"
  forbidden_decisions:
    - "Do not add `required: true` constraints to the new properties. Strictly additive. Existing plans must validate after the fix."
    - "Do not regress any existing test in the current sweep (1929 baseline)."
    - "Do not modify any locked plan's plan.md frontmatter to make it 'pass' — that's inverting the fix direction. Schema accommodates the existing shape, not the other way around."
    - "Do not push upstream to agent-conventions repo — that's operator-handled out-of-band per v4.1 D003 pattern."
  return_condition_summary: "All 3 features pass; agent-conventions VERSION bumped to 1.9.0 in DontPanic subtree mirror; every existing locked plan validates against the updated schema; doctor --validate-plans-strict returns zero blockers; full sweep ≥1929 green."
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
description: |
  Every locked plan since v3 uses `orchestration`, `child_charter`, and
  `commit_policy` keys in its plan.md frontmatter. The runtime accepts
  these (plan_loader unpacks them). Strict `jsonschema.validate` against
  `claude/shared/schemas/v1.0/plan.schema.json` rejects them as
  `additionalProperties not allowed` because the schema has
  `additionalProperties: false` at the root level and these properties
  aren't declared.

  Quiet timebomb: if a future doctor or CI step hardens validation
  (Plan 2 in the roadmap was almost going to do exactly that), every
  locked plan since v3 would suddenly fail. Plan 2's doctor widening
  is now sequenced AFTER this fix per operator review.

  Three features:
  - F001 widens the schema + Pydantic mirror to declare these
    properties additively (no new required fields)
  - F002 handles the agent-conventions subtree sync into DontPanic
    (operator handles upstream push out-of-band per v4.1 D003 pattern)
  - F003 adds a doctor check that runs full jsonschema validation
    against every locked plan
motivation: |
  Each locked plan since v3 has been declaring orchestration metadata
  that's *real* (the runtime uses it for parent-plan linkage, allowed-
  paths enforcement, commit-policy gating) but *invisible* to strict
  validation. The plan_loader unpacks the fields via direct attribute
  access; the schema doesn't know about them.

  When I tried to validate v4.1's plan.md frontmatter directly against
  the v1.0 schema during the v4.1 F001 drafting session, validation
  failed with:

      Additional properties are not allowed ('child_charter',
      'commit_policy', 'orchestration' were unexpected)

  Same gap exists in every locked plan since the orchestration
  metadata pattern was introduced. The fix is purely additive: declare
  the properties in the schema with documented shapes, ship as v1.9.0.

  Without this, Plan 2 (install UX) building a stricter doctor would
  break all existing plans. With it, doctor strict-validate becomes a
  trustworthy probe.
---

# Plan Schema Mismatch Fix

## Thesis

Every locked plan since v3 uses orchestration metadata the schema
doesn't acknowledge. Runtime works; strict validation fails. Fix
the schema by adding the properties additively, ship as v1.9.0,
add a doctor probe that catches future drift.

## Scope

In scope:

- **F001** — Add `orchestration`, `child_charter`, `commit_policy`
  to `claude/shared/schemas/v1.0/plan.schema.json` as documented
  object-type properties with internal structure declared. Update
  the Pydantic mirror at `claude/shared/schemas/v1.0/models/plan_model.py`
  in tandem. Bump `claude/shared/VERSION` 1.8.0 → 1.9.0. Append
  `claude/shared/CHANGELOG.md` entry citing roadmap Plan 3 + the
  pre-existing locked plans that motivated the fix.
- **F002** — Subtree-sync the schema bump into DontPanic. Mirror
  is already inside DontPanic at `claude/shared/`; implementer
  edits there directly. Operator handles the upstream
  `agent-conventions` push out-of-band per v4.1 D003 pattern
  (umbrella plan Phase 7 — Plan 5 in the roadmap creates the
  remote that the push lands on).
- **F003** — Add `dontpanic doctor --validate-plans-strict` mode
  that walks every locked plan in `docs/plans/` and runs full
  `jsonschema.validate` against the updated v1.0 schema. Defaults
  to advisory (warns); `--strict` makes it a blocker. After this
  fix, all locked plans pass under strict mode.

Out of scope:

- Pushing upstream to the agent-conventions repo (operator handles
  per v4.1 D003 and Plan 5 in the roadmap)
- Adding new required fields to plan.md frontmatter (strictly
  additive)
- Modifying any locked plan's frontmatter to "make it pass" — the
  schema accommodates the existing shape, not the other way around
- Plan 2's broader doctor widening (separate plan, sequenced after
  this one)

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance Summary

- **F001**: schema enum/property set extended additively. Pydantic
  mirror matches. VERSION = 1.9.0. CHANGELOG entry present.
  Existing plans validate (no regressions in test sweep).
- **F002**: DontPanic `claude/shared/` mirror matches the v1.9.0
  shape. No upstream push attempted (per D003).
- **F003**: `dontpanic doctor --validate-plans-strict` walks all
  locked plans + emits per-plan validation results. Returns zero
  blockers across the current locked-plan set. Fixture test
  reproduces both modes (advisory + strict).
