---
name: cost-model
description: Project month-end and next-month spend per app and per LLM provider from existing cost state
trigger_keywords: [cost projection, spend forecast, cost model, project costs]
file_patterns: []
applicable_agents: [all]
phase: on-demand
applies_to:
  surfaces: [infra]
  goal_types: [infra, new_feature, migration]
---

# cost-model

## Purpose

Synthesize existing cost state into forward-looking projections so an operator can answer "what will Glam burn this month?" or "is the LLM bill on track?" without inspecting raw JSON. cost-model is read-only — it never mutates `quota_state.json` or `costs.json`. It produces a markdown report plus a machine-readable JSON sibling for downstream skills (notably cost-guard, F002).

Use this skill when an operator needs a current cost picture or before making a spend decision (e.g., approving a tier promotion, sizing a new agent panel).

## Arguments

| Argument | Required | Description |
|---|---|---|
| `--costs` | no | Path to costs.json (default: `dashboard/state/costs.json`) |
| `--quota` | no | Path to quota_state.json (default: `~/.jarvis/quota_state.json`) |
| `--revenue` | no | Path to revenue.json (default: `dashboard/state/revenue.json`) — optional input; absence is fine |
| `--out` | no | Output directory for the report pair (default: `evidence/cost-model/`) |
| `--as-of` | no | Override "now" with an ISO-8601 timestamp for deterministic golden-output tests |
| `--fixtures` | no | Directory containing `costs.json`, `quota_state.json`, and (optional) `revenue.json` — convenient for testing |

If no arguments: reads the default paths and writes to `evidence/cost-model/`.

## Prerequisites

- `scripts/quota_check.py` (F020) has been run at least once so `quota_state.json` exists.
- `scripts/maintainer/refresh-costs.sh` has been run at least once so `costs.json` exists.
- For revenue numbers, run `revenue-check` first; otherwise the report shows `cost-only` mode.

## Steps

1. **Load state** — read costs.json + quota_state.json + (optional) revenue.json. If any required file is missing, emit a `data_unavailable` report and exit 0 (never raise).
2. **Project GCP spend** — for each app in costs.json totals, compute MTD daily rate, project month-end as `daily_rate × days_in_month`, project next month as `daily_rate × days_in_next_month`.
3. **Project LLM consumption** — for each model in quota_state.json, compute weekly daily rate, project week-end usage and percent-of-cap, then a 4.33-week monthly projection (weekly_used × 4.33 / weekly_cap × 100 if cap is set).
4. **Render report** — emit a markdown report and a JSON sibling under `<out>/<run-id>/cost-model-<ts>.{md,json}`, where `run-id` is a deterministic hash of the input snapshot when `--as-of` is supplied.
5. **No mutation** — never write to `quota_state.json`, `costs.json`, or `revenue.json`.

## Output

Two artifacts per run, both deterministic when `--as-of` is supplied:

- `cost-model-<ts>.md` — operator-facing markdown summary (per-app GCP, per-model LLM, optional cash-flow if revenue.json present).
- `cost-model-<ts>.json` — same content in machine-readable form: `{ generated, as_of, days_in_month, days_into_month, by_app: {…}, by_llm: {…}, mode: "cost-only" | "with-revenue" | "data_unavailable" }`.

Exit code is always 0 unless invocation flags are malformed (exit 2).

## Examples

```
python -m claude.skills.cost_model.cost_model \
  --fixtures claude/skills/cost-model/tests/fixtures/nominal/ \
  --as-of 2026-04-28T12:00:00Z \
  --out /tmp/cost-model-run/
```

Expected: writes `/tmp/cost-model-run/<run-id>/cost-model-*.md` + `.json` whose `by_app["Styln"].projected_month_end_usd` matches the recorded golden value byte-for-byte.

```
python -m claude.skills.cost_model.cost_model \
  --fixtures claude/skills/cost-model/tests/fixtures/empty/ \
  --out /tmp/cost-model-empty/
```

Expected: writes a `data_unavailable` report and exits 0.
