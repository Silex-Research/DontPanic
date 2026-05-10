---
id: 2026-05-09-004-feat-firebase-dashboard-adapter-v0
title: Firebase dashboard adapter v0 — realtime/team adapter for the bundled static dashboard
type: feat
tier: local
status: draft
date: "2026-05-09"
goal_type: new_feature
surfaces:
  - infra
  - web
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
protected_paths:
  - claude/shared/schemas/
dependencies:
  - 2026-05-09-003-feat-state-projection-v0
  - 2026-04-25-001-infra-jarvis-firebase-bootstrap
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
description: |
  Firebase/Firestore-side adapter that consumes the DontPanic state
  projection (plan 2026-05-09-003) and adds realtime + multi-operator
  collaboration on TOP of the bundled static dashboard at
  `DontPanic/dashboard/`. The static dashboard is OSS-friendly and
  works without Firebase (plan 2026-05-09-003 F007). This adapter is
  the OPTIONAL upgrade path for operators who want realtime team
  features (live drag-and-drop column flow, multi-operator presence,
  shared approval queue across machines). Repoints the dashboard from
  the deprecated multi-tenant `<axiom-firebase-project-id>` Firebase project
  to the personal-stack `<firebase-project-id>` project. Adds a sync layer that
  polls `dontpanic state snapshot --json` and mirrors into Firestore so
  the dashboard's existing real-time subscriptions render the live
  state. Drag-card-to-column interactions go through Cloud Functions
  that call DontPanic MCP — no direct Firestore writes for state
  changes.
motivation: |
  The Axiom dashboard already has the right shape: 5 views (Command
  Center, Mission Control kanban, Security with Approval Queue,
  Settings), real-time Firestore subscriptions, drag-and-drop column
  flow, modal detail per card. What's missing is the data path between
  DontPanic local state and the Firestore collections the dashboard
  reads. With the state projection contract from plan 2026-05-09-003,
  this becomes a pure adapter — DontPanic stays neutral, Firebase-specific
  code lives outside DontPanic core.
---

# Team Dashboard Sync

## Thesis

Three pieces, all outside DontPanic core:

1. **Repoint** dashboard config from `<axiom-firebase-project-id>` →
   `<firebase-project-id>`.
2. **Sync layer**: a polling daemon (or `dontpanic state stream`-based
   long-poller in v2) that calls `dontpanic state snapshot --json` and
   writes to Firestore at `<firebase-project-id>` under a single-tenant shape
   (`projects/<project_id>/plans`, `projects/<project_id>/agents`,
   etc.). NOT under `tenants/{tenantId}/` — the multi-tenant shape is
   archived per plan 2026-05-03-002 D002.
3. **Mutation path**: Cloud Function endpoints that the dashboard's
   drag-and-drop / approve-button UI calls. Functions translate
   dashboard-side actions into DontPanic MCP calls (`approve_gate`,
   `dispatch`, `resume`). State changes never bypass MCP — that
   preserves DontPanic's approval semantics.

Adapters do NOT write to DontPanic state directly. The projection is
read-only in this direction; mutations go through MCP.

## Scope

In scope:

- Dashboard config switch from `<axiom-firebase-project-id>` to `<firebase-project-id>`.
- Single-tenant Firestore schema mirroring the six projection streams.
- Sync daemon (Python or Node) running locally, polling every 5–15s.
- Cloud Functions for kanban column-flips, gate approves, dispatch
  triggers — each calling DontPanic MCP, never direct state mutation.
- Firestore security rules: read = authenticated operator;
  state-changing writes = denied (only Cloud Functions write).
- Smoke test: spin up dashboard locally, run a synthetic plan through
  DontPanic, verify dashboard renders + drag-flip actually mutates
  plan state.

Out of scope (explicit deferrals):

- Real-time long-poll / SSE replacing the polling daemon — depends on
  `state_stream` v1 in the parent projection plan.
- Multi-tenant Firestore (the dashboard repo's old shape) — explicit
  archive per 2026-05-03-002 D002.
- Authentication / OAuth flows — operator manages their own Firebase
  identity (existing Phase A infra).
- Alerting / ops dashboards — separate concern.
- Dashboard UI changes beyond config — UI is already correct, just
  needs data.
- Public/Observer dashboards — adapter v0 is operator-only;
  public-redact-level integration is a future extension.

## Target

```yaml
target_env: dev
target_project: <firebase-project-id>
```

## Acceptance Summary

- Dashboard at `axiom/packages/dashboard/` reads from `<firebase-project-id>`
  Firestore (verified by inspecting `firebaseConfig` in `app.js`).
- Sync daemon polls `dontpanic state snapshot --json --redact-level
  operator` and mirrors all six streams into Firestore. Latency target:
  ≤30s from local change to dashboard render.
- Cloud Functions for kanban move + gate approve + dispatch trigger
  exist and call DontPanic MCP (verified by smoke test).
- Firestore rules deny direct state-changing writes from the client.
- Smoke test: synthetic plan goes through volley_start → gate_paused →
  approve via dashboard drag → resume → signoff. Every transition
  visible in the kanban board within 30s.
- No new code in the DontPanic repo. Adapter code lives in
  `axiom/packages/dashboard/`, `axiom/packages/sync/`, or
  equivalent — NOT in `scripts/dontpanic_orchestrate/`.
