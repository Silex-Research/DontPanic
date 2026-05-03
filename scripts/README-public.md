# DontPanic — Personal AI Control Dashboard

A modular, local-first control dashboard for managing multiple AI coding harnesses (Claude Code, Codex, Gemini, Grok, Kimi, Qwen) across multiple projects.

## What You Get

| Page | What It Does |
|---|---|
| **Command Center** | Agent status, token budgets, task queue, activity feed, metrics charts |
| **Cloud Costs** | GCP billing scorecards, service breakdown, monthly trends (connects to BigQuery) |
| **Financial Analysis** | Ticker search, watchlist, price charts, Buffett-Munger deep analysis with Bayesian confidence sliders |
| **Mission Control** | Kanban board with project filters, agent sidebar, live feed |
| **Security** | Audit log of hook decisions, per-agent security profiles, threat feed |
| **Settings** | Harness sync status, active projects, theme toggle |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/Silex-Research/DontPanic.git
cd DontPanic

# 2. Install test dependencies (optional — dashboard runs without npm)
cd dashboard && npm install && cd ..

# 3. Open the dashboard
open dashboard/index.html
# Or serve locally:
npx serve dashboard
```

The dashboard loads with demo data out of the box. Customize `dashboard/state/*.json` to show your own data.

## Connect Your Data

### Cloud Costs (BigQuery)

1. Enable [billing export](https://cloud.google.com/billing/docs/how-to/export-data-bigquery) in GCP Console
2. Edit `scripts/refresh-costs.sh` with your BigQuery table names
3. Run `./scripts/refresh-costs.sh` to populate `dashboard/state/costs.json`

### Agent Status

Update `dashboard/state/agents.json` with your harness data. If you use Claude Code hooks, wire them to append to this file on session start/end.

### Tasks

Update `dashboard/state/tasks.json` manually or via a script. Each task has:
```json
{ "id": "t1", "title": "...", "project": "myapp", "status": "in_progress", "priority": "high", "agent": "claude", "created": "2026-03-23T12:00:00Z" }
```

### Deploy to Firebase Hosting

```bash
# 1. Create a Firebase project
firebase projects:create my-dontpanic-dashboard

# 2. Configure
echo '{ "projects": { "default": "my-dontpanic-dashboard" } }' > .firebaserc

# 3. Deploy
firebase deploy --only hosting
```

## Architecture

```
dashboard/
├── index.html              # Shell — nav + page container
├── core.css                # Shared design tokens, panel styles
├── core.js                 # Router, state loader, page registration
├── pages/                  # Each page is self-contained
│   ├── command-center/     # command-center.js + .css
│   ├── cloud-costs/
│   ├── financial/
│   ├── mission-control/
│   ├── security/
│   └── settings/
├── lib/                    # Extracted pure logic (testable)
│   ├── formatters.js
│   ├── financial-logic.js
│   ├── cloud-costs-logic.js
│   └── ...
├── state/                  # Local JSON state files
│   ├── agents.json
│   ├── tasks.json
│   ├── costs.json
│   ├── activity.json
│   └── security.json
└── tests/                  # 319 tests (Vitest + jsdom)
    ├── unit/
    └── integration/
```

### Adding a New Page

1. Create `dashboard/pages/my-page/my-page.js` and `.css`
2. Register via the legacy dashboard namespace: `Jarvis.registerPage({ id: 'my-page', label: 'My Page', init(state) {...} })`
3. Add CSS link to `index.html`

Pages are fully isolated — zero merge conflicts with other pages.

## Harness Config Sync

The `sync.sh` script syncs AI harness configurations across Claude Code, Codex, Gemini, and Cursor:

```bash
./sync.sh status   # Show differences between repo and live configs
./sync.sh pull     # Copy from live configs into repo
./sync.sh push     # Deploy from repo into live configs
```

## Tests

```bash
cd dashboard
npm test              # 319 tests, all passing
npm run test:watch    # Watch mode
npm run test:coverage # Coverage report
```

## License

MIT
