---
id: 2026-05-23-003-infra-visual-operating-console-roadmap-v0
title: Visual operating console roadmap v0
description: |
  Tracking parent for turning DontPanic's separate visual artifacts
  (static dashboard, capability center, architecture HTML, state projection,
  reconcile output) into a coherent local-first operator console. Executable
  work lives in child plans. V0 is audience-locked to the operator actively
  driving the loop: "what needs me now, what is stuck, what command should I
  run next?"
type: infra
tier: cross-cutting
status: completed
date: "2026-05-23"
goal_type: infra
surfaces:
  - ux
  - infra
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  no_progress_threshold: 2
  wall_clock_hours: 8
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-09-003-feat-state-projection-v0
  - 2026-05-19-004-feat-architecture-map-with-drift-v0
  - 2026-05-22-003-feat-capability-center-v1
  - 2026-05-23-001-infra-install-lifecycle-reconciliation-roadmap-v0
links:
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
---

# Visual Operating Console Roadmap v0

## Strategic Outcome

DontPanic should have a local-first visual home that answers one question
without making the operator inspect scattered artifacts:

```text
What needs action now?
```

The platform already has pieces:

- `dontpanic state snapshot` and `dontpanic state export-dashboard`
- bundled `dashboard/` static SPA
- Capability Center page and `capabilities.get_status`
- `dontpanic architecture regen --with-html`
- `dontpanic reconcile check`
- gate state, INBOX, active supervisors, and plan evidence

The gap is composition and audience discipline. The operator should not need to
know which artifact contains gates, capability setup, reconcile drift, or
supervisor stuck state. One command should open a local console and one cache
file should expose the same "what now" model to agents.

## Audience Model

The dashboard has multiple audiences, but V0 serves exactly one.

| Audience | Question | Roadmap phase |
|---|---|---|
| Operator driving the loop | What needs me now? | V0 |
| Operator overseeing the system | What is the platform doing overall? | V1 |
| Auditor | What happened and what evidence supports it? | V1 |
| Newcomer | What is this architecture and how do I learn it? | V1 |
| Shared team | Can multiple people operate the board remotely? | V2 |

V0 must not become a general-purpose portal. It is an operating console for the
person currently driving DontPanic work.

## Milestones

### V0 — Operator-In-The-Loop Console

Executable child: `2026-05-23-004-feat-operator-console-v0`

Scope:

- `dontpanic dashboard build|open|serve`
- local-only lightweight server with file watch and cache output
- shared four-band status taxonomy
- shared `ActionItem` provider model
- "What Now" view sourced from gates, capability status, reconcile drift, and
  active supervisor/stuck states
- projection-to-view adapter repair so dashboard pages consume current
  projection/state files without shape drift
- `dontpanic init` and `dontpanic doctor` point operators at the console

Status: lockable now.

### V1 — Overseeing, Audit, and Newcomer Views

Future child.

Scope:

- plans/features roster
- read-only mission board (not drag/drop kanban)
- architecture page embedding or linking the regenerated architecture HTML,
  freshness state, and exact regen command
- evidence and decisions browser

Trigger:

- V0 has shipped, and at least two weeks of operator use produce a concrete
  friction signal that cannot be solved in the action-focused "What Now" view.

### V2 — Shared Realtime Operations

Future child.

Scope:

- optional Firebase realtime adapter handoff
- remote approve/dispatch through governed Cloud Functions and DontPanic MCP
- multi-operator presence and shared operating view
- optional Tailscale/Cloudflare/ngrok exposure guidance

Trigger:

- `2026-05-09-004-feat-firebase-dashboard-adapter-v0` F003 and F005 are closed
  with end-to-end evidence, and the operator has a real shared-operator demand
  signal. V2 is not a placeholder in V0.

## Architecture Rules

1. Local-first is core. Firebase is an optional adapter, never required for V0.
2. Kanban language is reserved for interactive governed mutation paths. V0 uses
   "operator board" or "mission board" for read-only displays.
3. Next actions come from a single provider model, not from per-page prose.
4. Status colors map every subsystem into a shared four-band taxonomy:
   `ready`, `advisory`, `needs_action`, `info`.
5. Dashboard server is localhost-only by default. It writes a cache file so
   agents and auditors can consume the same model without HTTP.
6. Architecture HTML is V1. V0 may show an architecture-stale action, but does
   not embed the architecture page.

## Out Of Scope For V0

- architecture page or embedded architecture graph
- plans/features roster
- evidence browser
- read-only mission board
- drag/drop plan mutation
- Firebase realtime adapter
- remote approve/dispatch
- hosted control plane
