---
id: 2026-05-09-004-feat-firebase-dashboard-adapter-v0
title: Firebase dashboard adapter v0 — realtime/team adapter for the bundled static dashboard
type: feat
tier: local
status: active
date: "2026-05-09"
goal_type: infra
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
orchestration:
  parent_plan_id: 2026-05-11-001-infra-state-projection-adapters-meta
  spawn_reason: operator_manual
  depth_limit: 3
child_charter:
  kind: implementation
  parent_objective: "Ship Firebase realtime adapter on top of state-projection v0 so multiple operators can collaborate on a kanban dashboard with shared approval queue."
  parent_acceptance_item: "Parent F003: Plan 004 F001 and F002 closed via dispatch_volley with audit-envelope evidence; F003-F005 deferred until operator credentials in place."
  allowed_paths:
    - "dashboard/**"
    - "scripts/firebase_adapter/**"
    - "docs/plans/2026-05-09-004-feat-firebase-dashboard-adapter-v0/**"
  forbidden_decisions:
    - "Do not modify scripts/dontpanic_orchestrate/** — adapter only, never DontPanic core."
    - "Do not run firebase deploy or attempt to provision Cloud Functions / Firestore rules — F003+ are operator-deferred."
    - "Do not bypass MCP for state mutations — never write state-changing data directly to Firestore from the client."
  return_condition_summary: "Plan 004 F001 + F002 closed with passes:true; F003 + F004 + F005 explicitly deferred via D-entry citing deploy-credential dependency."
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
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
target_project: none
```

> **Rescope note (D007, 2026-05-11):** target_project lowered from `<firebase-project-id>`
> to `none` for the F001+F002 scope. Per parent_acceptance_item, F003-F005 are
> credential-deferred — without real Firebase access, F001+F002 cannot meaningfully
> target `<firebase-project-id>`. They build the static-layered config + sync daemon
> against local fixtures / Firebase emulator. F003+ will reactivate
> `target_project: <firebase-project-id>` once the operator has SA key + seed state ready.

## Acceptance Summary

F001+F002 (this session, no live credentials):

- Dashboard at `dashboard/` (per plan 2026-05-09-003 F007) gains an
  opt-in Firebase realtime layer — static fallback unchanged when no
  Firebase config is present.
- `firebaseConfig` block is plumbed but its values are placeholders /
  example template; real `<firebase-project-id>` config lands when credentials
  reactivate per F003+.
- Sync daemon scaffold lives at `scripts/firebase_adapter/` (outside
  `scripts/dontpanic_orchestrate/` per D001 adapter boundary). Diff
  logic + idempotency verified against local-mock or Firebase emulator
  rather than real Firestore.
- Firestore paths use single-tenant `projects/{project_id}/...` shape.
- No new code in `scripts/dontpanic_orchestrate/` — adapter only.

F003-F005 (deferred, per parent_acceptance_item):

- Cloud Functions for kanban move / gate approve / dispatch — need
  real Firebase deploy.
- Firestore rules — need real project deploy.
- End-to-end smoke test against `<firebase-project-id>` with synthetic plan
  drag-through.

The deferred items reactivate when the operator has SA key + seed state
ready for `<firebase-project-id>`. See D007 for the rescope rationale.
