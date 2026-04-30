---
id: 2026-04-29-004-fix-f006-budget-semantics
title: F006 budget semantics — quota_caps schema/breaker mismatch
type: fix
tier: local
status: draft
date: "2026-04-29"
description: |
  The plan-level `quota_caps` field is bounded `[0, 100]` in both `claude/shared/schemas/v1.0/plan.schema.json` (`maximum: 100`) and `claude/shared/schemas/v1.0/models/plan_model.py` (`confloat(ge=0.0, le=100.0)`), but the runtime telemetry it is compared against — `percent_weekly` from `~/.jarvis/quota_state.json` — is unbounded above 100% (the weekly cap is a soft estimate, not a hard subscription limit). When real usage exceeds 100% (claude is currently at 320.6%), no plan-declared budget can clear F006 `budget_ceiling` without violating the schema. This is a real design flaw, not a small numbers tweak. Fix: redefine the field semantics rather than blindly raise the bound.
motivation: |
  Surfaced by the changelog-skill dogfood (commit 8995dee). After F006 budget_ceiling halted iteration 0 (claude 299.7% > plan-declared 2.0%), the operator authorized a one-time bump to claude:370 / codex:600 to allow a remediation iteration. The Pydantic + JSON schema rejected those values as `Input should be less than or equal to 100`, blocking the dispatch. plan.md was restored to schema-valid values; D011 + D012 in plan 2026-04-29-001-feat-changelog-skill record the finding and the deferral.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
quota_caps:
  claude: 2
  codex: 1
loop_caps:
  max_iterations: 1
  no_progress_threshold: 2
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/quota_check.py
  - scripts/maintainer/refresh-costs.sh
dependencies:
  - 2026-04-19-001-infra-cross-agent-orchestration
  - 2026-04-29-001-feat-changelog-skill
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# F006 budget semantics — quota_caps schema/breaker mismatch

## Thesis

`quota_caps` is doing one of three jobs and the schema disagrees with the breaker about which one. The fix is to pick the right semantic, name the field accordingly, and align the schema bound with reality. A blind `le=100 → le=1000` bump papers over the confusion and creates a worse field whose name continues to imply percentage while its values document otherwise.

## The three candidate semantics

1. **Absolute usage ceiling.** Trip when `percent_weekly_observed > cap`. Cap is unbounded (matches reality: percent_weekly itself is unbounded). Field name should reflect this — e.g. `percent_weekly_cap` with no upper bound. Today's breaker code matches this interpretation; today's schema does not.
2. **Remaining-budget floor.** Trip when `(some_max - percent_weekly_observed) < cap`. Cap stays in [0, 100] (it is "minimum percent of weekly we want to leave on the table"). Today's breaker code does not match this; today's schema would survive.
3. **Per-volley delta ceiling.** Trip when `(percent_weekly_observed - percent_weekly_at_volley_start) > cap`. Cap is bounded by what one volley could realistically consume — typically <10%. The 0–100 schema bound is harmless here. Today's breaker code does not match this; would require capturing a baseline at volley start.

(1) is what we have minus the schema bound. (2) preserves the existing range but flips the breaker. (3) is the most operator-friendly because it answers "how much will THIS plan cost me" rather than "where is the agent in its weekly trajectory" — but it is also the biggest implementation change.

## Current behavior (evidence)

- `scripts/jarvis_orchestrate/circuit_breakers.py:121-173` `check_budget_ceiling` reads `percent_weekly` from `~/.jarvis/quota_state.json` and trips when `observed > cap`. This matches semantic (1).
- `claude/shared/schemas/v1.0/plan.schema.json:33-34` declares `claude` and `codex` quota fields with `maximum: 100`. This matches semantic (2) or (3) but not (1).
- Real telemetry: `quota_check.py` produces unbounded `percent_weekly` values (claude 320.6% at the time of writing). Conclusion: schema must be lifted, breaker preserved, OR breaker must be flipped, schema preserved.

## Target

```yaml
target_env: dev
target_project: <firebase-project-id>
```

## Provenance

- Surfaced by: changelog-skill dogfood (plan `2026-04-29-001-feat-changelog-skill`, commit `8995dee`, commit `3f62607`).
- Recorded as: D011 (schema/breaker mismatch) and D012 (remediation deferred) in that plan's decisions.jsonl.
- F006 originally landed in commits `[F006 #1-#5]` and `[F006 fix#1-#4]` series; F020 quota_state in `[F020: ...]`.

## Approach (proposal — refine before lock)

1. **Investigate and decide the semantic.** Pre-impl: write up the three candidate semantics (above) with their tradeoffs and pick one. Recommend (1) with field rename to `percent_weekly_cap` — it is closest to current behavior and the most direct mental model ("trip if weekly usage exceeds N%"). Record the choice in decisions.jsonl.
2. **Schema change.** Bump agent-conventions to v1.x (minor — additive); update `plan.schema.json` and `plan_model.py`. If the field is renamed, ship a one-time validator-side compat shim that reads `quota_caps` and warns/maps to the new name for one release; otherwise, just lift the bound.
3. **Breaker change.** Update `circuit_breakers.check_budget_ceiling` to match the chosen semantic (no-op if (1) is chosen with a rename). Update INBOX `breaker_tripped` event wording.
4. **Subtree pull into Jarvis.** Pull the new agent-conventions version into `claude/shared/`. Same pattern as past version bumps (v1.1.0, v1.2.0, v1.3.0).
5. **Backfill existing plans.** All Jarvis plans that have `quota_caps` need either a field rename or a value adjustment so they validate under the new schema. List: `2026-04-19-001`, `2026-04-25-001`, `2026-04-26-006`, `2026-04-28-001`, `2026-04-29-001`, `2026-04-29-002`, plus this plan and the F008 phased-gates sibling.
6. **Cross-project coordination.** agent-conventions is consumed by Glam and SpinDine via subtree. The schema change does not affect their plans (none of them use orchestrator-level `quota_caps`), but the version bump should still surface in their RESOLVER.md / subtree commits. No code change required there.
7. **Dogfood re-run.** Re-attempt the changelog plan's iteration 1 with the new schema. Confirms the F005a/F005b/F006/F008 surfaces still cohere end-to-end.

## Acceptance

- Schema bound and breaker logic agree on a single, named semantic. New schema validates real-world quota_caps values (e.g. claude:370, codex:600 if (1) is chosen, OR cap:5 if (3) is chosen).
- `circuit_breakers.check_budget_ceiling` test suite green under the new semantic. New tests cover the boundary conditions (e.g. cap == observed, cap < observed, cap == 0, cap > 100 if applicable).
- All existing Jarvis plans validate under the new schema (backfill complete).
- Dogfood: changelog plan iteration 1 dispatches without schema rejection. Post-iteration breaker fires correctly under the new semantic.

## Out of scope

- F008 phased gates (separate plan: `2026-04-29-003-fix-f008-phased-gates`).
- Cross-call audit threading (separate F005a follow-up).
- Reworking how `quota_check.py` computes `percent_weekly` (the unboundedness is intentional — weekly cap is an estimate).

## Risks

- **Cross-repo coordination.** Schema changes go through agent-conventions subtree — slower iteration loop. Mitigated by the fact that no other repo uses `quota_caps`.
- **Field rename breaks existing plans on first read.** Mitigated by either (a) validator-side compat shim, or (b) coordinated backfill across all Jarvis plans before the version bump lands.
- **Semantic choice locks in mental model.** (1) is "weekly trajectory cap"; (3) is "this plan's blast radius". Picking (3) later requires another schema bump. Recommend documenting why (1) was chosen in the plan decisions.jsonl.
