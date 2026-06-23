---
id: 2026-06-22-001-fix-dashboard-live-agents-projection
title: Surface live volley/supervisor state in the dashboard Work board
type: fix
tier: cross-cutting
status: abandoned
date: "2026-06-22"
goal_type: parity
description: >
  The dashboard loads the canonical supervisors stream but never surfaces it in
  the Work board, so a running volley shows zero live agents even while a
  supervisor is registered. The projection layer maps the plans stream to the
  legacy tasks shape and the inbox stream to the legacy activity shape, but it
  leaves the legacy agents shape untouched and no view consumes the supervisors
  stream. This plan closes that consumer-side gap: a small projection from the
  loaded supervisors stream into the shape the Work board renders, wired into the
  same load path, and proven end to end so a real registered supervisor shows as
  a live agent rather than via a hand-built fixture.
motivation: >
  Operators reported the Work board reading zero running during an active volley.
  Investigation showed the producer side is healthy (the supervisors stream is
  derived from the active-supervisor registry and already carries a live count),
  so the fix is purely on the dashboard consumer side. Making live execution
  visible is core to the dashboard being a trustworthy operator surface.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  hard_stop: false
privacy_tier: internal
dependencies: []
links:
  features: ./features.json
  objective_contract: ./objective_contract.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  audits_dir: ./audit/
---

## Target

```yaml
target_env: dev
target_project: none
```

# Surface live volley/supervisor state in the dashboard Work board

## Problem / Motivation

The dashboard loads the canonical supervisors stream into application state
(it is one of the seven loaded streams), and the Python producer derives that
stream from the active-supervisor registry plus a live-execution count. But the
browser projection that adapts canonical state into the legacy view shapes only
covers two of three legacy keys: it fills the tasks shape from the plans stream
and the activity shape from the inbox stream, and explicitly leaves the agents
shape static. No view consumes the supervisors stream directly either.

The result: during an active volley a supervisor is registered and present in
the loaded supervisors stream, yet the Work board renders zero live agents. The
data arrives; nothing surfaces it. This is a dashboard consumer-side gap, not a
producer problem.

## Proposed Approach

1. **Projection from the supervisors stream into the live-agents shape** — a
   small pure function that reads the loaded supervisors stream and produces the
   live-agents list the Work board renders (a stable id, a display name, a
   busy-or-idle status, the current plan/feature focus, and a last-updated
   stamp). It carries no secret shapes and mirrors the existing legacy-precedence
   rule: only derive from the stream when the stream is present, never clobber a
   meaningful static value otherwise. (D001, D002)

2. **Wire it into the existing load path** — invoke the new projection from the
   same place the plans-and-inbox projection already runs, so a single load both
   adapts canonical state and lights up the live-agents lane. Read-only with
   respect to all on-disk state. (D003)

3. **Prove it end to end, not via a hand-built fixture** — the producer already
   sources the supervisors stream from the active-supervisor registry. The
   acceptance binds a browser projection test to that producer shape (a fixture
   derived from the real stream entry contract, guarded against drift) and
   asserts that a registered active supervisor surfaces as one live agent with a
   non-zero running count through the real load-and-project path. This follows
   the operator-outcome rule: enter through the surface the operator sees, and do
   not build an adapter for data the producer never emits. (D004)

## Scope (in)

- A pure projection from the loaded supervisors stream into the live-agents view
  shape, with unit coverage for present, empty, and partial-entry streams.
- Wiring of that projection into the existing browser load path next to the
  plans-and-inbox projection.
- A producer-contract-guarded projection test proving a registered supervisor
  surfaces as a live agent with a non-zero running count, plus a no-secret-shape
  assertion on the projected output.

## Scope (out)

- No change to the Python producer: the supervisors stream and its registry
  source are already correct. (D005)
- No new dashboard page, tab, or visual redesign — this lights up the existing
  Work board lane only.
- No realtime/websocket push; the existing load/refresh cadence is unchanged.
- No change to the upgrade-readiness plan or any other active plan.

## Acceptance

- A pure projection turns a loaded supervisors stream into the live-agents view
  shape (id, name, busy-or-idle status, current focus, updated stamp) and is
  covered for present, empty, and partial-entry inputs.
- The projection runs inside the existing browser load path alongside the
  plans-and-inbox projection and never writes any on-disk state.
- A projection test whose input shape is bound to the producer stream contract
  (guarded against drift) shows a registered active supervisor rendering as one
  live agent with a non-zero running count through the real load-and-project
  path.
- The legacy-precedence rule holds: an absent supervisors stream does not erase a
  meaningful static value, and a present stream takes precedence.
- The projected output contains no secret shapes.

## Risks

- **Producer emits nothing during some volleys** — if the registry is empty the
  lane honestly shows zero; the end-to-end feature distinguishes "nothing
  running" from "running but not surfaced" so the fix is verifiable.
- **Shape drift between producer and browser fixture** — mitigated by binding the
  test fixture to the producer stream contract and failing on drift.
- **Double-source confusion** — the live-agents lane derives only from the
  supervisors stream; it does not mix in the plans-derived tasks shape.
