---
name: product-health-agent
description: Managed agent that analyzes production app engagement and operational health. Reads Firestore aggregates, Cloud Logging, and Cloud Monitoring; mounts source repos read-only; writes structured insights to a workspace Firestore collection. Designed for daily digests and on-demand deep dives on the Glam and SpinDineSwift production apps. Read-only by design.
disable-model-invocation: true
---

# Product Health Agent — Managed Observability for Production Apps

A Claude Managed Agent that answers two questions about production apps every day:

1. **What parts of the app are users engaging with most?**
2. **What's not functional well operationally?**

The agent has:
- Custom tools for Cloud Logging, Cloud Monitoring, Firestore aggregation reads
- Read access to the app's source repos (mounted at session start)
- The standard agent toolset (bash, read, write, grep, glob, web_search)
- **Zero write access to production** — only the workspace insights collection

## Status

**v1 — built 2026-04-11.** Supports Glam and SpinDineSwift on Firebase. Ready to run
daily digests and ad-hoc deep dives.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Host (cron or human invocation)                              │
│                                                              │
│  digest_runner.py / orchestrator.py                          │
│  ├── google-cloud-firestore creds (ADC)                      │
│  ├── google-cloud-logging creds (ADC)                        │
│  ├── google-cloud-monitoring creds (ADC)                     │
│  └── tools.py dispatch() — host-side tool execution          │
│                                                              │
│  Sessions are created per-run. Agent is persistent.          │
└───────────────────────┬──────────────────────────────────────┘
                        │ streams events, dispatches custom tools
                        ▼
┌──────────────────────────────────────────────────────────────┐
│ Anthropic-hosted container                                   │
│                                                              │
│  Built-in tools:                                             │
│    bash, read, write, edit, glob, grep, web_search           │
│                                                              │
│  Custom tools (declared on agent, dispatched to host):       │
│    list_functions                                            │
│    get_function_errors                                       │
│    search_logs                                               │
│    get_function_invocation_stats                             │
│    get_daily_usage_metrics      (Glam — pre-aggregated)      │
│    get_alerts                    (Glam — pre-aggregated)     │
│    get_trending_stores           (Glam-specific)             │
│    get_firestore_counts          (both apps)                 │
│    write_insight                 (ONLY write, targets        │
│                                   workspace project)         │
│                                                              │
│  Mounted repos (read-only, added per-session):               │
│    /workspace/glam                                           │
│    /workspace/spindine                                       │
└──────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│ Workspace Firestore — insights storage                       │
│                                                              │
│  tenants/{tenant_id}/product_insights/{app}/findings/{id}    │
│                                                              │
│  Each finding: {                                             │
│    severity, category, title, body,                          │
│    evidence: [...], recommended_actions: [...],              │
│    created_at, created_by: "product-health-agent"            │
│  }                                                           │
└──────────────────────────────────────────────────────────────┘
```

## Setup

Prerequisites:
- `uv` (PEP 723 inline deps)
- `ANTHROPIC_API_KEY` environment variable
- gcloud Application Default Credentials with read access to both production
  projects and write access to the workspace project:
  ```bash
  gcloud auth application-default login
  ```

### 1. Copy and customize the config

```bash
cd claude/skills/product-health-agent
cp config.example.json /path/to/your-workspace/product_health.config.json
# edit project IDs and tenant_id
```

### 2. Run one-time setup

```bash
./setup_agent.py --config /path/to/your-workspace/product_health.config.json
```

This creates:
- A Cloud environment (`product-health-env`)
- The Product Health Analyst agent with the full custom tool surface
- Persists both IDs to `state/agent_ids.json` (gitignored)

Re-running is a no-op unless you pass `--force`.

### 3. Run a digest or an ad-hoc session

```bash
# Daily digest (runs one session per configured app)
./digest_runner.py --config /path/to/your-workspace/product_health.config.json

# Just one app
./digest_runner.py --config ... --apps glam

# Ad-hoc deep dive
./orchestrator.py --config ... --app spindine \
  --prompt "Why is nearbyRestaurantsSimple erroring? Check the last 24h and find the root cause."
```

## Tool Surface

| Tool | What it does | Notes |
|---|---|---|
| `list_functions` | gcloud functions list for an app | Use first if you don't know what's deployed |
| `get_function_errors` | Cloud Logging query for ERROR+ entries | Filters by function_name, severity, since_hours |
| `search_logs` | Free-form Cloud Logging filter | Pass a raw filter fragment; time window added automatically |
| `get_function_invocation_stats` | Cloud Monitoring request_count + status breakdown | Returns per-service 2xx/4xx/5xx totals and error_rate |
| `get_daily_usage_metrics` | Reads Firestore aggregate docs | Glam only (returns available: false for SpinDine) |
| `get_alerts` | Reads the app's alerts collection | Glam has this, SpinDine doesn't |
| `get_trending_stores` | Reads Glam's store engagement cache | Glam-specific |
| `get_firestore_counts` | Cheap aggregation count queries | Works for both apps |
| `write_insight` | Records a finding in the workspace project | **Only write operation**. Strict severity enum. |

## Read-Only Guarantee

The agent has **no** write access to production. The `tools.py` module enforces this by:

1. Only instantiating the workspace project Firestore client when `write_insight` is called.
2. All other tools use read-only clients pointed at production projects.
3. No production-project `write_*` / `delete_*` tools exist at all — it's not a policy, it's
   the absence of code that could do harm.

If you want to extend with narrow write capability later (e.g. "create a GitHub issue"),
add it as a separate custom tool with an explicit confirmation step. Don't loosen this module.

## Insights Schema

Written to: `{workspace_project}/tenants/{tenant}/product_insights/{app}/findings/{auto_id}`

```json
{
  "app": "glam",
  "severity": "high",
  "category": "ops_health",
  "title": "autoTagUnprocessedPhotosGrok erroring every 6h",
  "body": "The scheduled cron runs every 6 hours (03:24, 09:24, 15:24 UTC) and logs ERROR each time. Sample message: '...'. Grep of firebase/functions/src/scheduled/auto-tag.ts:47 shows the Grok API call has no retry wrapper.",
  "evidence": [
    {"type": "log", "timestamp": "2026-04-11T15:24:04Z", "function": "autotagunprocessedphotosgrok", "message": "..."},
    {"type": "code", "path": "firebase/functions/src/scheduled/auto-tag.ts", "line": 47, "snippet": "..."}
  ],
  "recommended_actions": [
    "Wrap Grok API call in withRetry() from utils/retry.ts (matches pattern used in try-on.ts)",
    "Add alert to dailyUsageMetrics if errorCount > 10/day for this function"
  ],
  "created_at": "2026-04-11T13:05:00+00:00",
  "created_by": "product-health-agent",
  "run_date": "2026-04-11"
}
```

## Cost Envelope

With Claude Fable 5.1 (`claude-fable-5-1`, $10/$50 per 1M tokens) and daily digests for
two apps, expect ~60 sessions/month of 15-40 tool calls each. Re-baseline the per-session
cost after the first week of runs; the earlier $0.30–$1.00 per session figure was measured
on Opus 4.6 at $5/$25. Ad-hoc deep dives add on top and are human-triggered. Fable 5.1
requires 30-day data retention on the org, and a session can end with
`stop_reason: refusal`; the orchestrator should log that as its own outcome, not as idle.

## Files

```
product-health-agent/
├── SKILL.md             # This file
├── .gitignore           # Excludes state/ and local configs
├── config.example.json  # Template — copy and customize
├── tools.py             # Custom tool implementations (host-side)
├── setup_agent.py       # One-time setup — creates agent + env
├── orchestrator.py      # Runtime — creates session, streams events, dispatches tools
├── digest_runner.py     # Cron entry point — one session per configured app
└── state/               # Gitignored — persisted agent/env IDs after setup
```

## Extending

**To add a new tool:**
1. Write `_impl_your_tool(...)` in `tools.py`
2. Add the `TOOL_SPEC` entry with JSON schema
3. Add the dispatch entry to `TOOL_FUNCS`
4. Re-run `setup_agent.py --force` to update the agent with the new tool surface
   (agent update creates a new version; old sessions keep the old version)

**To support a new app:**
1. Add an entry under `apps` in config.json with the Firebase project_id
2. Add `"enum": [..., "new_app"]` to the tool specs in tools.py
3. Re-run `setup_agent.py --force`

## What This Skill Does NOT Do

- **No autonomous fixes.** Every recommended action is human-executed.
- **No writes to production.** See Read-Only Guarantee above.
- **No credential sprawl.** Firebase service-account keys stay on the host.
- **No auto-healing.** If you want PR creation or incident response automation,
  build it as a separate agent with explicit guardrails and a human approval gate.
