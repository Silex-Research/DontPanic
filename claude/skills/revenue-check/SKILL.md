---
name: revenue-check
description: Pull product revenue per app from Firestore (or fixtures) and produce a cash-flow report
trigger_keywords: [revenue, cash flow, revenue check, profitability]
file_patterns: []
applicable_agents: [all]
phase: on-demand
---

# revenue-check

## Purpose

Aggregate product revenue per app and write `dashboard/state/revenue.json` so cost-model can compute net cash-flow positions. Source-aware: each app declares an adapter (`glam` reads Firestore `creatorEarningsLedger`; `spindine` is deferred to a follow-up — see D001 in the parent plan). Stub mode reads fixtures so fresh-clone tests need zero credentials.

## Arguments

| Argument | Required | Description |
|---|---|---|
| `--stub` | no | Use the FixtureAdapter for every app instead of live Firestore. Fresh-clone tests use this. |
| `--live` | no | Explicitly opt in to live adapters that may require ADC. Mutually exclusive with `--stub` / `--fixtures`. |
| `--apps` | no | Comma-separated list of apps to query (default: `Styln`). SpinDine is intentionally not in the default list — see D001. |
| `--out` | no | Path for revenue.json output (default: `dashboard/state/revenue.json`) |
| `--evidence-dir` | no | Where to write the cash-flow report (default: `evidence/revenue-check/`) |
| `--costs` | no | Path to costs.json for the cash-flow report (default: `dashboard/state/costs.json`) |
| `--as-of` | no | ISO-8601 timestamp to override "now" (deterministic tests) |
| `--fixtures` | no | Directory containing per-app fixture subdirectories. Implies `--stub`. |

If no mode is supplied: refuses to run live (avoids surprising network calls). Use `--stub` for fresh-clone testing or `--live` for operator-approved Firestore/deferred adapters.

## Prerequisites

- For live mode: `firebase-admin` available + the orchestrator service-account key present under `.secrets/` (or ADC) so `scripts/jarvis_orchestrate/firebase_client.py` can be imported. Project ID is read from `environments.json` at runtime, not hardcoded here.
- For stub mode: nothing.

## Steps

1. **Resolve adapters** — for each requested app, choose an adapter. `Styln` → GlamLedgerAdapter (Firestore `creatorEarningsLedger`). `Spin & Dine` → DeferredAdapter (returns `source: 'unavailable'`, references D001 follow-up). Override with FixtureAdapter when `--stub` is set.
2. **Aggregate** — for each app, sum monthly revenue from the adapter. Glam: sum `creatorEarningsLedger.amount` where `category in ('finalized', 'estimated')` and the row's month equals the as-of month.
3. **Write revenue.json** — shape: `{ generated, by_app: { <app>: { monthly_revenue_usd, source, granularity, last_event_at } } }`.
4. **Render cash-flow report** — read `dashboard/state/costs.json`, compute `net = revenue − GCP cost` per app, output evidence/<run-id>/cash-flow-<ts>.{md,json}.

## Output

- `dashboard/state/revenue.json` (NEW file). Sibling of costs.json — explicitly outside the protected dirty-files list per D005.
- `evidence/revenue-check/<run-id>/cash-flow-<ts>.{md,json}` — markdown + JSON cash-flow snapshot.

Exit code is 0 on success, 0 with `source: 'unavailable'` for deferred apps, 2 on malformed CLI flags.

## Examples

```
python -m claude.skills.revenue-check.revenue_check \
  --stub \
  --fixtures claude/skills/revenue-check/tests/fixtures/nominal/ \
  --as-of 2026-04-28T12:00:00Z \
  --out /tmp/rev.json \
  --evidence-dir /tmp/rev-evidence/
```

Expected: writes `/tmp/rev.json` with a `by_app` map for the fixture apps and a cash-flow report under `/tmp/rev-evidence/`.

```
python -m claude.skills.revenue-check.revenue_check --live --apps Styln
```

Expected: reads the Glam Firestore adapter using ADC and writes `dashboard/state/revenue.json`.
