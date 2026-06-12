---
id: 2026-06-04-003-feat-integration-operator-actions
title: Integration operator-actions (deploy / credentials / smoke)
type: feat
tier: cross-cutting
status: active
date: "2026-06-04"
goal_type: new_feature
description: >
  The operational surface for operator-owned integration work — Firebase deploys,
  Linear/PM credentials, Discord webhook setup, smoke tests — modelled as dashboard
  ActionItems (what / why / creds-required / exact command / evidence / reversible),
  NOT as implementation features. Re-homes the operator-gated remainders of the
  firebase-dashboard-adapter and external-integrations-bridge plans.
motivation: >
  The 2026-06-04 audit found "open" integration features that are actually
  operator-owned steps: firebase Cloud Functions are coded + tested but need a live
  deploy + smoke (credentials); the Linear linked-status chip needs PM credentials +
  projection wiring. Per the plans-vs-operator-actions principle, deploy/credential/
  smoke work belongs in the action model, with plans requiring the action as
  evidence rather than pretending it is code.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
privacy_tier: internal

links:
  features: ./features.json
  decisions: ./decisions.jsonl
  objective_contract: ./objective_contract.json
---

# Integration operator-actions

## Target

```yaml
target_env: dev
target_project: none
```

This plan defines the ACTION CATALOG and the cheap in-repo smoke; live deploys and
credential setup are executed by the operator against their own
Firebase/Linear/Discord, gated by the catalog's ActionItems.

## Problem / Motivation

Deploys, credentials, and smoke tests for Firebase / Linear / Discord are
operator-owned and credential-bearing — they cannot pass through an agent volley.
Today they sit mis-filed as code features (firebase-adapter F003/F005, ext-bridge
F003), so they read as backlog. They should be ActionItems that say plainly: what
needs doing, why it matters, whether credentials are required, the exact command or
button, what evidence proves it worked, and whether it is safe/reversible.

## Proposed Approach

A small catalog of integration ActionItems + one genuinely-cheap in-repo smoke (the
static-dashboard path that applies today), with gated deploy/realtime actions parked
behind their real trigger (multi-operator need, active PM sync). Mostly operational
surface, minimal code.

## Scope (in)

- F001 Integration ActionItem catalog: Firebase functions deploy, Firebase realtime
  smoke, static-dashboard smoke, Linear credential setup, Discord webhook setup —
  each with what/why/creds/exact-command/evidence/reversible.
- F002 Static dashboard smoke action (applies now): a runnable check that
  `state export-dashboard` → static dashboard renders, with evidence capture.
  (Re-homes firebase-adapter F005 static half.)
- F003 Gated realtime/deploy actions: Firebase functions deploy + realtime smoke as
  ActionItems gated on multi-operator need + credentials. (Re-homes firebase-adapter
  F003/F005 realtime half; parked behind trigger.)
- F004 Integration status surfacing: per-integration status routed through the
  existing what-now/operator-console surfaces (no separate integrations panel),
  derived from catalog + evidence per the status matrix below.

## Integration catalog (F001 literal rows)

| integration_id | action_id | command (operator_command unless marked exact) | credential_env_vars | evidence_expected |
|---|---|---|---|---|
| static-dashboard | static-dashboard-smoke | `dontpanic integrations smoke static-dashboard` (exact_command) | [] | smoke record outcome=passed |
| firebase-functions-deploy | firebase-creds | provision Firebase service credentials, then `dontpanic integrations attest firebase-functions-deploy --action firebase-creds --outcome passed` | [FIREBASE_TOKEN] | attestation record (action_id firebase-creds) |
| firebase-functions-deploy | firebase-deploy | `firebase deploy --only functions` (operator_command), then attest with --action firebase-deploy | [FIREBASE_TOKEN] | attestation record (action_id firebase-deploy) |
| firebase-realtime-smoke | firebase-realtime-smoke | follow dashboard/functions/RUNBOOK.md smoke, then attest with --action firebase-realtime-smoke | [FIREBASE_TOKEN] | attestation record outcome=passed |
| discord-webhook | discord-webhook | set the Discord webhook env var, then attest with --action discord-webhook | [DONTPANIC_DISCORD_WEBHOOK_URL] | attestation record (action_id discord-webhook) |
| linear-credentials | linear-creds | provision Linear API credentials, then attest with --action linear-creds | [LINEAR_API_KEY] | attestation record (action_id linear-creds) |

Trigger: firebase-deploy and firebase-realtime-smoke carry trigger_condition
"multi-operator dashboard need" (trigger attestation action_id firebase-trigger).
Fixtures assert these literals; implementation MUST NOT drift from this table
without a plan amendment.

## Integration status matrix (F004 contract)

Evidence = integration-evidence files written by write_integration_evidence()
(F002 contract). Status is derived per integration:

| integration | pending | configured | deployed | smoke-passing |
|---|---|---|---|---|
| static-dashboard | no evidence | n/a (no creds) | n/a | smoke evidence outcome=passed |
| firebase-functions-deploy | no evidence | attested credential-setup evidence (action_id firebase-creds) | attested deploy evidence (action_id firebase-deploy) | n/a (smoke is a separate row) |
| firebase-realtime-smoke | no evidence | configured = deploy row reached deployed | n/a | attested smoke evidence outcome=passed (action_id firebase-realtime-smoke) |
| discord-webhook | no evidence | attested webhook-setup evidence (action_id discord-webhook) | n/a | n/a (configured is terminal) |
| linear-credentials | no evidence | attested credential evidence (action_id linear-creds) | n/a | n/a (configured is terminal; projection work tracked in ext-bridge) |

Status derives EXCLUSIVELY from evidence records (env-var presence is a display
hint, never a status driver). Evidence files are append-only JSONL (one per integration; records never rewritten).
The status FLOOR is the highest status achieved by passed records in the history; a
later outcome=failed record surfaces a failure flag in the item copy without
regressing the floor - statuses never regress silently and prior success is never
overwritten. After an integration's pending ActionItems clear, it remains visible in
the quiet band of the existing what-now/operator-console surfaces with its derived
status label; only pending integrations occupy the needs-action band.

## Scope (out)

- Writing the Firebase/Linear/Discord credentials or running the live deploy (operator).
- The PM-tool projection enrichment + chip code (a build feature under the
  ext-bridge plan IF Linear sync is activated; tracked there, not here).
- Multi-operator realtime as a default (demand-gated).

## Acceptance

Each operator-owned integration step is represented as an ActionItem carrying
what/why/creds-required/exact-command/evidence/reversible; the static-dashboard smoke
runs in-repo today and captures evidence; deploy/realtime actions are present but
gated (no silent execution); the dashboard truthfully reflects per-integration status.
