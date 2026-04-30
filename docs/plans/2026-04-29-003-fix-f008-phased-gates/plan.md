---
id: 2026-04-29-003-fix-f008-phased-gates
title: F008 phased gates — split pre_impl and pre_merge across the volley lifecycle
type: fix
tier: local
status: active
date: "2026-04-29"
description: |
  The supervisor currently evaluates ALL declared `human_gates` upfront before iteration 0 of any volley. That makes pre_merge a duplicate operator-confirmation gate alongside pre_impl rather than a true post-implementation merge checkpoint. This fix splits gate evaluation across the volley lifecycle: pre_impl gates fire before round 0; pre_merge gates fire only after the volley terminates with `signed_off` (and therefore never fire on `paused_on_gate` or `stopped_*` terminals). Other lifecycle-phase gates can be added the same way.
motivation: |
  Surfaced by the changelog-skill dogfood (commit 8995dee, decisions D003-update-1 and D003-update-2 in plan 2026-04-29-001-feat-changelog-skill). Run 1 paused on `['pre_impl', 'pre_merge']` before iteration 0; after approving pre_impl, run 2 re-paused on pre_merge — also before iteration 0. The operator had to approve pre_merge upfront to let the volley start, which means pre_merge currently has zero post-implementation safety value despite its name. This isn't a regression; it's an F008 design gap that the dogfood was the first run to encounter under realistic conditions.
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

# F008 phased gates — split pre_impl and pre_merge across the volley lifecycle

## Thesis

Lifecycle-named gates should fire at their lifecycle position. `pre_impl` already does (it is checked before any iteration starts). `pre_merge` should fire only after the volley produces a sign-off and only as a final operator-confirmation before any merge step would land. Today both are checked together upfront, which empties pre_merge of meaning.

## Current behavior (evidence)

- `scripts/jarvis_orchestrate/supervisor.py` `dispatch_volley` calls a single `_check_gates(...)` upfront and pauses on any unmet gate before iteration 0 starts.
- Dogfood evidence: `docs/plans/2026-04-29-001-feat-changelog-skill/audit/gate-state.json` records two pause/approve cycles before iteration 0 (one for each gate). After both were cleared, iteration 0 ran. After iteration 0 hit F006 budget_ceiling, no pre_merge re-evaluation happened — the volley terminated as `stopped_budget`.
- The `pre_merge` semantic is therefore "second operator-approval gate", not "post-implementation merge gate".

## Target

```yaml
target_env: dev
target_project: jarvis-a6ee1
```

## Provenance

- Surfaced by: changelog-skill dogfood (plan `2026-04-29-001-feat-changelog-skill`, commit `8995dee`).
- Recorded as: D003-update-1 (gate-pacing observation) and D003-update-2 (semantic compromise on pre_merge for the dogfood) in that plan's decisions.jsonl.
- F008 originally landed in commits `[F008-engagement: ...]` series (parent F008, signed off 2026-04-26+).

## Approach (locked 2026-04-29 — see decisions.jsonl D001/D002/D003)

1. **Categorize declared gates by lifecycle phase.** A small mapping in `gate_pause` (or a sibling module) that classifies each declared gate name into a phase: `pre_impl` (before iteration 0), `mid_volley` (between iterations — reserved, no current consumers), `pre_merge` (after `signed_off` only, before any merge step), `post_merge` (reserved). Unknown gate names default to `pre_impl` for backward compatibility.
2. **Split the upfront check.** `dispatch_volley` evaluates only `pre_impl`-phase gates before round 0. `pre_merge`-phase gates are evaluated in `_emit_volley_terminal` (or equivalent) only when `final_status == 'signed_off'`. Other terminal states (`stopped_*`, `paused_on_gate`, `blocked`) skip pre_merge entirely — pre_merge has nothing to confirm if no merge is on the table.
3. **Update INBOX + gate-state semantics.** The pause event for pre_merge should reference iteration count + signoff_id so the operator knows what they're approving. Cleared-gates list in `audit/gate-state.json` retains both phases.
4. **Backwards compatibility.** Existing plans with `human_gates: [pre_impl, pre_merge]` keep working; behavior change is timing only (pre_merge fires later, not at all if no signoff). Existing tests that asserted upfront pre_merge pauses get updated to assert post-signoff pause.
5. **Resolved at lock-time (D002).** `pre_merge` does NOT fire on `needs_changes` terminals — sign-off is binary. needs_changes means the auditor wants another round, not that there is something to merge.

## Acceptance

- A new plan with `human_gates: [pre_impl, pre_merge]` and a synthetic always-sign-off mock executor pauses **only** on pre_impl before iteration 0; after pre_impl is cleared, the volley runs to sign-off; pre_merge is then evaluated and the supervisor re-pauses with a `gate_hit` INBOX event referencing the signoff_id.
- A second synthetic plan that terminates with `stopped_budget` produces no pre_merge pause — `audit/gate-state.json` shows pre_merge as still un-cleared but the volley terminates without re-prompting.
- Existing F008 tests pass (regression sweep across `test_f008_*.py`).
- Dogfood: re-run the changelog plan (or a fresh trivial sub-plan) and confirm phased semantics empirically.

## Out of scope

- Cross-call audit threading (separate F005a follow-up — see D010 of changelog plan).
- Quota-budget schema/breaker semantics (separate F006 follow-up — see plan `2026-04-29-004-fix-f006-budget-semantics`).
- Adding new gate phases beyond pre_impl / pre_merge in this plan (the categorization mapping should be extensible, but only those two are wired for now).

## Risks

- **Test churn.** Any synthetic test that asserted "pre_merge pauses upfront" needs updating. Should be small — F008 tests already grew during the engagement-surface work.
- **Operator habit.** Operators expect both gates to pause before iteration 0; the new behavior delays pre_merge until after sign-off. INBOX wording should make the new timing explicit.
- **Edge case: pre_merge flips a previously-signed-off run.** Resolved at lock-time (D003): amend signoff.json with `pre_merge_rejected: true` + timestamp + actor; emit `gate_rejected` INBOX event; set plan status to `blocked` so a normal `jarvis resume` cannot override. CLI: `jarvis-orchestrate reject <plan-id> pre_merge [--reason '...']`. WIP stays in workspace as draft (not auto-reverted); operator decides revisit path.
