---
id: 2026-06-04-003-feat-integration-operator-actions
title: Integration operator-actions (deploy / credentials / smoke)
type: feat
tier: cross-cutting
status: draft
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
- F004 Integration status surfacing: dashboard shows each integration as
  configured / deployed / smoke-passing / pending, consuming the catalog.

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
