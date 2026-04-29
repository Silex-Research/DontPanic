---
name: cost-guard
description: Compare observed app-level run-rate to per-app and per-model budgets, emit INBOX warnings on breach
trigger_keywords: [cost alert, budget guard, cost guard, check budget, budget breach]
file_patterns: []
applicable_agents: [all]
phase: on-demand
---

# cost-guard

## Purpose

Watch app-level financial state and warn an operator when GCP burn or LLM token consumption is on track to breach a configured budget. cost-guard is the alarm complement to F001 cost-model: cost-model tells you what the trajectory is, cost-guard tells you whether the trajectory matters. Writes findings into the existing F008 INBOX.md surface so cost alerts share an inbox with `quota_warn` and `breaker_tripped` rather than introducing a new operator channel.

This skill is **app-level**, distinct from F006 budget_ceiling which guards orchestration-agent quotas inside autonomous dispatches. Different lane, different consumer.

## Arguments

| Argument | Required | Description |
|---|---|---|
| `--costs` | no | Path to costs.json (default: `dashboard/state/costs.json`) |
| `--quota` | no | Path to quota_state.json (default: `~/.jarvis/quota_state.json`) |
| `--budgets` | no | Path to cost_budgets.json (default: `config/cost_budgets.json`) |
| `--inbox-dir` | no | Directory containing INBOX.md (default: `dashboard/state/cost-guard/`) |
| `--seen-state` | no | Path to dedupe state file (default: `dashboard/state/cost-guard/cost_guard_seen.json`) |
| `--as-of` | no | Override "now" with an ISO-8601 timestamp for deterministic tests |
| `--fixtures` | no | Directory containing `costs.json`, `quota_state.json`, `cost_budgets.json` — convenient for testing |

If no arguments: reads defaults and writes to `dashboard/state/cost-guard/INBOX.md`.

## Prerequisites

- `config/cost_budgets.json` exists. Ships with sentinel zeros — cost-guard short-circuits with `no_budgets_configured` if the operator hasn't filled in numbers.
- `scripts/quota_check.py` and `scripts/maintainer/refresh-costs.sh` have been run. cost-guard treats state files >24h old as stale and emits `data_stale` instead of false-positive breach entries.

## Steps

1. **Load** — read costs.json + quota_state.json + cost_budgets.json. Missing budget config → exit 0 with a single `no_budgets_configured` finding.
2. **Stale-data check** — if either input has `generated` >24h old, emit one `data_stale` finding and short-circuit.
3. **Project** — compute MTD daily rate for each app (mirrors F001 cost-model). Compute week-to-date burn for each LLM model.
4. **Compare** — for each app where `gcp_monthly_budget_usd > 0`, ratio = `projected_month_end / budget`. For each LLM model where `weekly_token_budget` (or `weekly_call_budget`) > 0, ratio = `projected_week_end / budget`.
5. **Emit** — `cost_breach` (ratio >= 1.0) or `cost_warn` (ratio >= 0.8) entries via the F008 INBOX writer (`scripts/jarvis_orchestrate/inbox.py`). Always honor the resolved threshold values; the `--budgets` JSON may override defaults via `thresholds.warn` and `thresholds.breach`.
6. **Idempotency** — dedupe key = `sha256(scope|kind|week_start)`. Re-runs within the same calendar week with the same condition append zero new INBOX entries.

## Output

- INBOX.md entries appended (one per breached scope|kind tuple, deduplicated within a week).
- Updated `cost_guard_seen.json` recording dedupe keys.
- Stdout summary: counts of entries appended + skipped + already-seen.

Exit code is 0 in all expected cases (including all-zero budgets and stale data — both are explicit findings, not errors). Exit 2 on malformed CLI flags.

## Examples

```
python -m claude.skills.cost_guard.cost_guard \
  --fixtures claude/skills/cost-guard/tests/fixtures/breach/ \
  --as-of 2026-04-28T12:00:00Z \
  --inbox-dir /tmp/cg-test/ \
  --seen-state /tmp/cg-test/seen.json
```

Expected: appends one `cost_breach` entry per breached app to `/tmp/cg-test/INBOX.md`. Re-running with identical args appends nothing.
