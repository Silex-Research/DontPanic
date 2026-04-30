---
id: 2026-04-30-001-fix-quota-tracker-vendor-native
title: Vendor-native quota tracker — per-vendor window+unit observed signal with operator caps file
type: fix
tier: local
status: draft
date: "2026-04-30"
description: |
  `scripts/quota_check.py` reports claude=320.6%, codex=538.0%, gemini=0%, grok=0% — all wrong against the corresponding vendor dashboards. Three independent root causes per vendor (cache-token weighting at 1.0× when Anthropic meters ≪1×, line-counting `~/.codex/history.jsonl` instead of reading per-thread tokens from `~/.codex/state_5.sqlite`, wrong path `~/.config/gemini/` instead of `~/.gemini/`, no metering source for Grok). Replace single-window raw-token approach with per-vendor native windows and units: Claude (rolling 7d weekly + 5h session, calibrated cost-weighted "messages"), Codex (rolling 5h messages from state_5.sqlite, tier from auth.json JWT), Gemini (rolling 24h requests, tier from oauth_creds.json vs env), Grok (stub until local CLI/API key path exists). Caps move out of the plan-frontmatter `quota_caps` field into operator-editable `~/.jarvis/quota_caps.json` keyed by vendor+window+tier. Subsumes plan 004's open D001 — once vendor-native, plan-level `quota_caps` schema becomes vestigial and 004 collapses to schema cleanup + F006/F007 consumer update.
motivation: |
  Surfaced 2026-04-30 by operator inspection of claude.ai/settings/usage during follow-up to the 2026-04-29 changelog dogfood: dashboard shows 13% weekly used (Max 20x), tracker shows 320.6%. Investigation found the 25× mismatch is structural (cache-weighting + arbitrary 1B-token divisor + Mon-UTC vs Anthropic's per-account rolling-7d window), not a tuning problem. Same shape across all four vendors — each meters in a different window with a different unit, and the current "weekly tokens for everyone" abstraction cannot represent reality without misleading the F006 budget_ceiling breaker. Per-vendor research (4 parallel agents) found exploitable local signals on 3 of 4 vendors plus tier-detection paths; Grok lacks both a local CLI install and a subscriber API and stays stubbed.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
quota_caps:
  claude: 3
  codex: 2
loop_caps:
  max_iterations: 3
  no_progress_threshold: 2
  wall_clock_hours: 6
  hard_stop: false
privacy_tier: internal
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
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

# Vendor-native quota tracker

## Thesis

Every vendor meters subscribers in its own native window with its own native unit. Forcing them all into a "weekly tokens" model loses information at every step and fabricates a denominator (the hardcoded 1B/wk for Claude) that has no empirical basis. Replace the single-window approach with per-vendor signal extraction in the vendor's native window, an operator-editable caps file keyed by `vendor.tier.window`, and a state schema (`quota_state.json` v2) that emits one block per (vendor, window). Calibrate Claude with an explicit confidence + source + timestamp because the vendor publishes only percentages and the relationship between local tokens and dashboard percent is approximate by construction.

## Why each vendor's signal differs

| Vendor | Native window | Native unit | Best local signal | Cap source |
|---|---|---|---|---|
| Claude (Max 20x) | rolling 7d weekly + rolling 5h session | cost-weighted "messages" (proprietary, dashboard-only) | session JSONL `message.usage` per `model`, cache reads at 0.1× weight, calibrated against operator-supplied dashboard sample | operator config; `percent_of_plan` cap |
| Codex (ChatGPT Plus) | rolling 5h + weekly | "messages" (Plus, dynamic by task complexity); SQLite local proxy is `tokens_used` | `~/.codex/state_5.sqlite` table `threads(model, tokens_used, updated_at)` — per-thread token totals already persisted; tier via JWT in `~/.codex/auth.json` (`chatgpt_plan_type` claim) | operator config; `tokens_local_proxy` cap (best-local, not authoritative) |
| Gemini (Code Assist Individuals on this machine) | rolling 24h | requests/day (aggregate Pro+Flash) | walk `~/.gemini/tmp/<projectHash>/chats/session-*.json`; per-message `tokens.total` retained as diagnostic; tier via `oauth_creds.json` presence vs `GEMINI_API_KEY` env | operator config; `requests` cap |
| Grok | n/a (no `grok` CLI and no `XAI_API_KEY` on this machine) | n/a | stub returning `signal: "absent"` until either path exists | n/a |

Anthropic, OpenAI, Google, xAI all confirm there is no public API for the consumer subscriber tier's current usage percentage. All four require local proxies.

## Target

```yaml
target_env: dev
target_project: none
```

Host-local plan: edits `scripts/quota_check.py`, `scripts/jarvis_orchestrate/circuit_breakers.py`, and `~/.jarvis/quota_caps.json`. No GCP project is touched.

## Provenance

- Surfaced by: operator inspection of claude.ai/settings/usage on 2026-04-30 during follow-up review of plan 2026-04-29-004's open D001.
- Recorded as: D011 + D012 in plan 2026-04-29-001-feat-changelog-skill (initial finding); D001-D004 in plan 2026-04-29-004-fix-f006-budget-semantics (semantic candidates); now superseded by this plan.
- Vendor research: 4 parallel research agents (Claude/Codex/Gemini/Grok), 2026-04-30 session. Findings inline in features.json.
- Sources: Anthropic Claude Code costs docs, OpenAI Codex plan limits docs, Google Gemini Code Assist quota docs, xAI rate-limit docs. Local files verified: `~/.codex/state_5.sqlite`, `~/.gemini/oauth_creds.json`, `~/.codex/auth.json`.

## Approach (locked 2026-04-30)

Implementation order: F001+F003 in parallel → F002 → F004 → F005 → F006 → F007.

1. **F001 — Per-vendor signal extraction.** New helpers in `scripts/quota_check.py`: `_claude_usage_v2(window)` (JSONL walk, cache reads at 0.1× weight, group by `message.model`, scoped to window), `_codex_usage_v2(window)` (sqlite SELECT against `state_5.sqlite.threads`), `_gemini_usage_v2()` (walk `~/.gemini/tmp/*/chats/session-*.json`), `_grok_usage_v2()` (presence check). Drop `_codex_calls_this_week()` line-counting. Verify `tokens.total` presence in fresh Gemini session before relying on it; fall back to message-count if absent.
2. **F002 — quota_state.json schema v2.** Per-vendor block keyed by tier; per-window child block with `kind`, `observed_native`, `observed_unit`, `models{}`, optional `calibration{}` and `diagnostics{}`. Backwards-compat shim: continue to emit flat `models.{name}.percent_weekly` mirror for one release so the old breaker path still works during cutover.
3. **F003 — Tier detection.** Codex: parse JWT in `~/.codex/auth.json` (best-effort, no signature verify), extract `chatgpt_plan_type` → {plus, pro, pro_5x, pro_20x, business, enterprise}. Gemini: presence of `~/.gemini/oauth_creds.json` → "code_assist_individuals" (sub-tier distinction Pro/Ultra deferred); `GEMINI_API_KEY` env → "ai_studio_api". Claude: no detection, operator-set value in caps file. Grok: presence-only, default "absent".
4. **F004 — Operator caps file.** `~/.jarvis/quota_caps.json` (NOT in repo, NOT in `cost_budgets.json`). Schema: `{schema_version, <vendor>: {<tier>: {<window>: {cap, unit}}}}`. New CLI: `python -m jarvis_orchestrate quota-caps init` writes a starter file with researched defaults; `quota-caps show` prints current effective caps. Loader validates the file against per-vendor profile schemas at startup; rejects unknown vendor/tier/window keys.
5. **F005 — Claude calibration.** `python -m jarvis_orchestrate calibrate-claude --dashboard-pct N [--window rolling_7d]`. Reads current `observed_native` for that window, computes `ratio = dashboard_pct / observed_native`, writes calibration block: `{ratio, confidence: "manual", source: "operator_dashboard_sample", stamped_at: <iso>}`. Confidence levels: `uncalibrated` (0.0 default), `manual` (operator-sampled), `auto` (reserved — not implemented; would require a vendor API that does not exist). Tracker output always surfaces confidence + stamped_at; warn if `stamped_at` is >7 days old. Re-cal cadence is operator's responsibility; plan does not auto-trigger.
6. **F006 — Breaker rewrite.** `circuit_breakers.check_budget_ceiling(plan, agent)`: read `state["vendors"][agent].windows[*]`, for each window compute `(observed_native * (calibration.ratio or 1.0)) / cap_from_quota_caps_json`, trip if any window > 1.0. INBOX wording surfaces (a) which window tripped, (b) tier, (c) observed vs cap, (d) calibration confidence label. Backward-compat fallback: if vendor block missing from state, use old `percent_weekly` path with a deprecation warning written to logs. Plan 004's lock-time question is now answered structurally: "absolute usage ceiling per vendor's native window" — semantic (1) generalized.
7. **F007 — Tests + dogfood.** Synthetic fixtures per vendor (mock JSONL sample, mock SQLite, mock chat dir). Live verification: run `python scripts/quota_check.py` against this machine and compare each vendor percentage against current dashboards within ±10% for Claude (calibrated approximate), exact for Codex/Gemini (locally counted). Re-run changelog plan iteration 1 to confirm F005a/F006/F008 still cohere with new state shape.

## Acceptance

1. `python scripts/quota_check.py` emits state schema v2 with per-vendor per-window blocks; legacy `models.{name}.percent_weekly` mirror retained as deprecated for one release.
2. Codex 538% gone — replaced with rolling-5h + weekly tokens from `state_5.sqlite`, displayed with tier label (plus/pro/etc.) + cap source path.
3. Gemini reads from `~/.gemini/tmp/<projectHash>/chats/session-*.json`, not `~/.config/gemini/state.json` (which does not exist on this machine); tier detection prints `code_assist_individuals` for the OAuth-personal install observed locally.
4. Claude calibration command works end-to-end; calibration block recorded with confidence=`manual` + source=`operator_dashboard_sample` + stamped_at; tracker output surfaces confidence + warns when stale.
5. Grok stays stubbed when no `~/.grok/` and no `XAI_API_KEY`; output shows `signal: "absent"` (not 0%) so operator notices if a CLI is later installed and stays unwired.
6. `~/.jarvis/quota_caps.json` is the single source of truth for caps; init command writes starter file with researched defaults; show command prints effective caps.
7. F006 budget_ceiling reads new state shape, trips on per-vendor per-window threshold, surfaces calibration confidence in INBOX wording, falls back gracefully when state is in legacy shape.
8. Synthetic test fixtures + live machine verification both green; calibration confidence is `manual` (not `auto` — that is reserved for future when no such API exists).
9. Changelog plan iteration 1 dispatches without quota state schema mismatch; old breaker behavior preserved via fallback during cutover.

## Out of scope

- Anthropic admin API integration (no public consumer endpoint exists).
- Codex undocumented `backend-api/codex/usage` scraping (fragile, can break without notice).
- Gemini OpenTelemetry → GCP Cloud Monitoring export wiring (separate future feature; would give authoritative ground truth).
- Per-plan `quota_caps` overrides (deferred — defaults-only first; revisit after schema v2 proves out and operator caps file is in steady use).
- F006 productivity-breaker audit (no_progress, diminishing_returns, convergence_collapse) — separate dogfood review unless a regression appears while testing this plan.
- Plan 004 schema cleanup (remove `quota_caps` from plan.schema.json + update F006/F007 consumers) — happens after this lands; 004 stays alive as the small follow-up.
- Live OAuth introspection for Gemini sub-tier distinction (Pro vs Ultra vs Code Assist Standard) — current detection collapses all OAuth-personal to `code_assist_individuals`.
- Auto-recalibration for Claude (would require a vendor API that does not exist).

## Risks

- **Calibration drift.** Claude's cost-weighting changes if Anthropic alters cache pricing or model mix; one-time calibration goes stale silently. Mitigation: surface `stamped_at` in tracker output, warn when >7 days old, recommend operator re-cal cadence in init output.
- **Codex SQLite schema drift.** Codex CLI may rename columns or change `state_5.sqlite` shape in a minor version. Mitigation: catch sqlite errors gracefully, degrade to `signal: "schema_mismatch"` rather than crash; record observed schema version in diagnostics.
- **Gemini per-message tokens.total absent.** Not observed in v0.28 `logs.json` on this machine; may or may not be in `chats/session-*.json` (community report says yes, local install predates). Mitigation: F001 verifies on a live session; if absent, fall back to message-count without diagnostic.
- **Grok stub regression.** If a `grok` CLI is later installed but the stub keeps returning `absent`, operator may not notice. Mitigation: stub explicitly logs `grok detection: absent (no ~/.grok/, no XAI_API_KEY)` so operator sees the absence is observed.
- **Plan 004 dependency.** 004 is `blocked` (not deleted) and depends on this plan landing first. Mitigation: explicit dependency in 004's plan.md frontmatter; D-entry recording the pause reason + reactivation criterion ("after this plan's F006 lands, 004 reduces to plan.schema.json + plan_model.py field removal + consumer update in F006/F007 of parent").
- **Operator caps file divergence.** `~/.jarvis/quota_caps.json` is per-machine. Multi-machine setups will have drift. Mitigation: out of scope for now; future work could sync via operator-controlled mechanism.
- **Cost budgets vs quota budgets confusion.** Two adjacent files (`dashboard/state/costs.json` for $-spend on GCP, `~/.jarvis/quota_caps.json` for vendor-quota). Mitigation: caps file lives in `~/.jarvis/` not repo; loader documents the distinction; init command output explains the split.
