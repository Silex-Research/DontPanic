# Plan 2026-04-30-001 close-out memo — vendor-native quota tracker

**Plan ID:** `2026-04-30-001-fix-quota-tracker-vendor-native`
**Type:** `fix` · **Tier:** `local` · **agents:** `claude` + `codex`
**goal_type:** none declared (exempt-by-absence from F2 completion gate)
**Status flip:** `active` → `completed` on 2026-05-07 (UTC).

This memo synthesizes the four-stage close-out narrative across F001–F007 and connects the plan to its blocked follow-up (`2026-04-29-004-fix-f006-budget-semantics`). The plan dir is sparse — no per-feature memos, no `evidence/` subtree of its own — so the plan-level memo carries the close-out story directly. Per-feature evidence references in `features.json` point at production code paths (`scripts/quota_check.py`, `scripts/jarvis_orchestrate/{quota_caps_loader,calibration_loader,circuit_breakers}.py`) and the dogfood evidence dir at `docs/plans/2026-04-29-001-feat-changelog-skill/evidence/f007/` (more on that below).

## The four-stage close-out story

The story is **not** "quota fixed." Operator framing:

> bad signal replaced → caps/config/calibration rewired → consumers migrated → dogfood verified; schema cleanup remains follow-up.

| Stage | Features | What landed |
|---|---|---|
| **(1) bad signal replaced** | F001 (per-vendor signal extraction) + F002 (state schema v2) + F003 (tier detection) | `scripts/quota_check.py` rewritten to read each vendor's native window in its native unit: Claude rolling_7d weekly + rolling_5h session via `~/.claude/projects/**/*.jsonl` with cache-read 0.1× weighting; Codex rolling_5h via `~/.codex/state_5.sqlite` `threads.tokens_used`; Gemini rolling 24h requests via `~/.gemini/tmp/<projectHash>/chats/session-*.json`; Grok stub returning `signal: "absent"` until a CLI/API path exists. State emits one `vendors[].windows[]` block per (vendor, window). Tier detection from `~/.codex/auth.json` JWT (`chatgpt_plan_type`) for Codex and `~/.gemini/oauth_creds.json` vs `GEMINI_API_KEY` env for Gemini. |
| **(2) caps/config/calibration rewired** | F004 (operator caps file) + F005 (Claude calibration command) | Caps moved out of plan-frontmatter `quota_caps` into operator-editable `~/.jarvis/quota_caps.json` keyed by `vendor.tier.window` (D001). Schema rejects unknown vendor/tier/window keys at startup. New CLI: `quota-caps init` (writes researched defaults), `quota-caps show` (effective caps). Calibration: `calibrate-claude --dashboard-pct N [--window rolling_7d\|rolling_5h]` with sticky storage at `~/.jarvis/quota_calibration.json`; calibration carries explicit confidence + source + timestamp because the vendor publishes only percentages and the dashboard-to-token relationship is approximate by construction (D003). |
| **(3) consumers migrated** | F006 (split into F006a check_budget_ceiling rewrite + F006b supervisor `_quota_admission` + soft-warn migration) | `circuit_breakers.check_budget_ceiling(plan, agent)` reads `state["vendors"][agent].windows[*]`, computes `(observed_native * (calibration.ratio or 1.0)) / cap` per window, trips if any window > 1.0. Both admission paths (`dispatch_single_agent` + `dispatch_volley`) route through `_format_admission_quota_reason` (D015 fix#1) so `defer:<cause>` and numeric `percent_weekly N%` paths share a single builder. INBOX surfaces window + tier + observed-vs-cap + calibration confidence. Backward-compat fallback for missing vendor blocks logs a deprecation warning and uses the legacy `percent_weekly` path. F006a + F006b each went through two operator-review fix passes (D012/D013 for F006a, D014/D015 for F006b) before close. |
| **(4) dogfood verified** | F007 | Real-volley re-run of `2026-04-29-001-feat-changelog-skill` (claude implementer + codex auditor, `--max-iterations 1`, target `dev/<firebase-project-id>`) confirmed: tracker reports `claude rolling_7d=13.3%` (calibrated, matches operator dashboard `13%`) and `codex rolling_5h=26.1%` (cap=1B `tokens_local_proxy`); admission gate `quota_over=False`; volley terminated `stopped_diminishing_returns` at iter 1 from auditor finding-count plateau **unrelated to quota**; INBOX recorded **zero** `budget_ceiling` events; protected-path SHA-256 hashes UNCHANGED. Pre-state evidence (the original 2026-04-29 run with claude `percent_weekly=299.7%` false-trip) preserved at `docs/plans/2026-04-29-001-feat-changelog-skill/evidence/f007/pre-vendor-native-baseline/`; post-state at `.../post-vendor-native-dogfood/`. Both subdirs are tracked in HEAD; this is where D016's prose-level "evidence/f007/..." references resolve. |

## Schema cleanup remains follow-up — Plan 2026-04-29-004 (BLOCKED → reactivates on this close)

Per D008 of this plan: Plan 2026-04-29-004-fix-f006-budget-semantics flipped `status: blocked` (no `paused` enum value) at lock time with the dependency declared. After this plan's F006 lands, plan 004 reactivates and reduces in scope to:

- Remove `quota_caps` field from `claude/shared/schemas/v1.0/plan.schema.json` + `plan_model.py`.
- Update F006/F007 description text in the parent plan to reflect the per-vendor per-window model.
- Backfill any plans whose frontmatter still declares `quota_caps` so they validate after schema removal (note: plan 004 itself still declares `quota_caps: {claude: 2, codex: 1}` — the schema field exists exactly because plan 004 hasn't reactivated yet; that becomes part of the cleanup).
- Migrate `cost-model` and `cost-guard` skills off the legacy `quota_state.json` `models{}` mirror onto the per-vendor `vendors{}` shape (plan 004's D011, resolved 2026-04-30 — operator scope-extension when reactivation was anticipated).
- Hardening follow-up identified during F007 preflight: split `_codex_usage_v2` `diagnostics.signal` into `open_failed` (retry-eligible, do not interpret as zero) vs `schema_mismatch` (true table-shape error). The `unable to open database file` transient hit during F007 preflight is the same class of bug this plan was created to fix; queued in plan 004 alongside D011 cost-model migration per D016.

Verified at this close-out: plan 004 still has `status: blocked`, F001 still `passes: false`, plan 004's D005 (paused per vendor-native tracker) and D011 (cost-model migration scope) are both `resolved`. Reactivation triggers naturally on this close — operator runs the schema cleanup + migration as plan 004's reduced scope.

## D-id gap is intentional — D011 lives in plan 004

This plan's `decisions.jsonl` runs D001 → D010 → D012 → D016. **D011 was never written here.** The D011 the operator's review brief refers to lives in `docs/plans/2026-04-29-004-fix-f006-budget-semantics/decisions.jsonl` (resolved 2026-04-30, scope-extension for cost-model + cost-guard migration). This plan's D016 explicitly cites "D011 cost-model migration" as a plan-004 item, confirming the cross-plan numbering. Future readers should not treat the gap as a missing/retracted decision in this plan — it's an artifact of the quota-fix-family numbering convention where some D-ids are authored in adjacent plans.

## Critical lock-time decision worth preserving — D010

D010 ("Plan-level quota_caps for this plan: declare or omit?") is the **self-deadlock-avoidance** decision: this plan exists precisely because the broken `percent_weekly` signal reports `claude=320.6% / codex=538.0%` against any reasonable plan-declared cap. Declaring small `quota_caps` (e.g. `claude:3 / codex:2` matching plan 003's pattern) would have caused F006 to trip on the broken signal after iteration 0 of this plan's own implementation — self-deadlocking the very work that's fixing the breaker.

The `quota_caps` field is not in `plan.schema.json`'s required list, so omission is schema-valid. Implementation operator was instructed to expect `budget_ceiling` to be silent during F001–F006 and to rely on `loop_caps` (`max_iterations: 3, no_progress_threshold: 2, wall_clock_hours: 6`) + manual cost discipline. The other six breakers (`iteration_cap`, `no_progress`, `diminishing_returns`, `convergence_collapse`, `wall_clock`, `global_circuit_breaker`) remained in effect.

**Verified at this close-out**: plan.md frontmatter does NOT declare `quota_caps`. The 6 grep hits in the description prose are all references to the new operator-editable `~/.jarvis/quota_caps.json` file or the schema-cleanup-via-plan-004 work — none reintroduce a frontmatter `quota_caps` field. Self-deadlock avoidance honored.

## Cross-link to canonical-module flip

Production paths cited in evidence_refs (`scripts/jarvis_orchestrate/quota_caps_loader.py`, `scripts/jarvis_orchestrate/calibration_loader.py`, `scripts/jarvis_orchestrate/circuit_breakers.py`) still resolve correctly post the canonical-module flip (Plan 2026-05-04-001 ship `8edd953`) — the `jarvis_orchestrate` shim re-exports from the canonical `dontpanic_orchestrate` module with a one-shot `DeprecationWarning`, so the evidence_refs remain valid as historical records. Live tooling readers should mentally map `jarvis_orchestrate` → `dontpanic_orchestrate` for current canonical paths; the per-feature evidence_refs were authored pre-rename and are intentionally preserved (D004 of the canonical-module-flip plan: historical artifacts NOT renamed).

## Outer plan close — exempt-flow path

```
$ dontpanic plan close docs/plans/2026-04-30-001-fix-quota-tracker-vendor-native/
[plan close] goal_type=None is exempt from the F2 completion gate;
             status flipped active → completed without audit
```

Same exempt-flow path as the prior four Tier 1 close-outs.

## Sign-off

Plan 2026-04-30-001 ships clean. F001–F007 all `passes:true`. The bad `percent_weekly` signal is replaced; caps/config/calibration rewired into per-machine operator-editable shape; consumers (breaker + supervisor admission + soft-warn) migrated; dogfood verified the original 2026-04-29 changelog-skill failure now passes the gate (claude rolling_7d=13.3%, codex rolling_5h=26.1%, zero budget_ceiling events). Schema cleanup + cost-model/cost-guard migration + Codex SQLite open-vs-schema diagnostic split are queued in the now-reactivating plan 2026-04-29-004.

— bayesian, 2026-05-07 UTC
