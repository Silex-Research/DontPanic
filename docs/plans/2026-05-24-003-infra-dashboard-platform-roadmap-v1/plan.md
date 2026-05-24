---
id: 2026-05-24-003-infra-dashboard-platform-roadmap-v1
title: Dashboard platform roadmap v1
description: |
  Tracking-only parent for the full dashboard platform arc after the closed
  Visual Operating Console v0 roadmap. Consolidates the local operator
  console, multi-project dashboard, value-language IA, interactive
  Architecture Explorer, future review/configuration surfaces, optional
  realtime/team adapters, and later conversational/multi-agent workflows into
  one sequenced roadmap with explicit trigger conditions.
type: infra
tier: architectural
status: completed
date: "2026-05-24"
goal_type: infra
surfaces:
  - ux
  - docs
  - infra
agents_required: []
human_gates:
  - pre_impl
loop_caps:
  max_iterations: 1
  no_progress_threshold: 1
  wall_clock_hours: 1
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-23-003-infra-visual-operating-console-roadmap-v0
  - 2026-05-23-004-feat-operator-console-v0
  - 2026-05-23-005-feat-dashboard-project-selector-v0
  - 2026-05-09-003-feat-state-projection-v0
  - 2026-05-19-004-feat-architecture-map-with-drift-v0
  - 2026-05-23-002-feat-install-reconcile-foundation-v0
  - 2026-05-23-007-feat-plan-intake-readiness-v0
  - 2026-05-22-003-feat-capability-center-v1
  - 2026-05-22-004-feat-capability-guided-setup-v2
  - 2026-05-24-001-feat-dashboard-value-language-ia-v0
  - 2026-05-24-002-feat-dashboard-architecture-explorer-v1
  - 2026-05-09-004-feat-firebase-dashboard-adapter-v0
  - 2026-05-20-001-infra-external-integrations-bridge-v0
links:
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
---

# Dashboard Platform Roadmap v1

## Strategic Outcome

DontPanic's dashboard should become the local visual home for operating AI
software work across one or many repositories:

```text
See what needs attention, understand the system, review evidence, and copy the
next governed command without losing the trust boundary between dashboard and
terminal.
```

The dashboard is not a replacement for the operator's terminal, IDE, or GitHub
review flow. It is the coordination layer above them: a state viewer, decision
surface, architecture explorer, and command emitter for humans and agents.

## Predecessor

`2026-05-23-003-infra-visual-operating-console-roadmap-v0` is the closed V0
predecessor. It remains the historical parent for the first operator-console
slice. This roadmap opens the V1+ arc rather than reopening the completed V0
roadmap.

## Product Invariants

- **Local-first by default.** The dashboard must work without Firebase,
  hosted services, or remote credentials.
- **Read-only unless a future ADR explicitly changes that.** Current dashboard
  surfaces show state and emit commands; they do not silently mutate state.
- **Command-emitter, not hidden actor.** Any action shown in the dashboard must
  make the governed CLI/MCP action visible.
- **Value-first, technical-second.** Primary UI copy explains user/business
  value. Technical IDs, paths, and source/provenance remain available in
  details.
- **Project-aware.** One DontPanic install can operate many repos/apps. The
  dashboard must distinguish global, project, and fleet state.
- **Credible data only.** Empty states and warnings must name missing/stale
  data instead of filling the UI with demo content.

## Milestones

### V0 - Foundation (Closed)

Completed predecessor work:

- `2026-05-23-004-feat-operator-console-v0` - local What Now dashboard
- `2026-05-23-005-feat-dashboard-project-selector-v0` - multi-repo selector
- `2026-05-09-003-feat-state-projection-v0` - stable read-only state projection
- `2026-05-19-004-feat-architecture-map-with-drift-v0` - architecture JSON/HTML substrate
- `2026-05-23-002-feat-install-reconcile-foundation-v0` - install drift substrate
- `2026-05-23-007-feat-plan-intake-readiness-v0` - planning/readiness recommender substrate
- `2026-05-22-003-feat-capability-center-v1` - visual capability status
- `2026-05-22-004-feat-capability-guided-setup-v2` - guided setup substrate

### V1 - Coherent Product Surface (Lockable Now)

Executable child plans:

- `2026-05-24-001-feat-dashboard-value-language-ia-v0`
- `2026-05-24-002-feat-dashboard-architecture-explorer-v1`

Sequencing:

1. Lock the value-language IA plan first so shell branding, navigation, and
   first-read copy are coherent.
2. Architecture Explorer F001 may run in parallel because it owns view-model
   and flow-definition substrate, not dashboard shell edits.
3. Architecture Explorer F002+ should wait until the IA shell/nav cleanup lands
   or must explicitly reconcile against the cleaned shell before merge.

V1 outcome:

- non-technical reviewers can understand what needs attention and why
- technical operators and agents can still recover exact substrate
- Architecture becomes a first-class interactive flow explorer, not an iframe
  or placeholder

### V2 - Action And Review Surfaces (Future)

Draft only after V1 has operated for at least two weeks and the operator reports
a specific review/decision/configuration friction that V1 does not solve.

Candidate child plans:

- `dashboard-review-evidence-v1`
- `dashboard-decisions-queue-v1`
- `dashboard-configuration-readonly-v1`

V2 remains read-only/command-emitter by default.

### V3 - Inline Action And Streaming (Future ADR Required)

Draft only after a written ADR accepts that part of the dashboard may become a
governed action surface. This is a different trust model from V0/V1/V2.

Candidate child plans:

- `dashboard-local-executor-v1`
- `dashboard-streaming-volley-panel-v1`
- `dashboard-agent-session-registry-v1`

V3 must preserve the terminal as a trusted execution surface unless the ADR
explicitly chooses a different boundary.

### V4 - Team / Shared / Realtime (Capability-Gated Future)

Open when either a second operator creates real multi-user friction or external
demand requires shared visibility.

Related active/optional plans:

- `2026-05-09-004-feat-firebase-dashboard-adapter-v0`
- `2026-05-20-001-infra-external-integrations-bridge-v0`

Candidate child plan:

- `dashboard-realtime-collab-v1`

Firebase remains an optional adapter, not a prerequisite for the local
dashboard.

### V5 - Multi-Agent Compare And Conversational Authoring (Future)

Open only after V0-V3 surfaces have been used for at least four weeks and the
operator reports one of these concrete needs:

- compare Claude/Codex/Gemini/Grok/local outputs on the same feature
- draft and refine plans through a dashboard conversation instead of editing
  plan files directly

Candidate child plans:

- `dashboard-agent-compare-v1`
- `dashboard-conversational-plan-authoring-v1`

## Current Build Recommendation

Do not dispatch the two V1 child plans as full parallel dashboard edits. Their
write scopes collide in `dashboard/index.html`, core routing, and shared CSS.

Recommended route:

1. Lock and dispatch `2026-05-24-001-feat-dashboard-value-language-ia-v0`.
2. In parallel, dispatch only `2026-05-24-002` F001 if worker ownership can be
   restricted to architecture view-model, flow definitions, tests, and design
   intake.
3. After IA shell/nav cleanup lands, dispatch Architecture Explorer F002-F005.

## Non-Goals

- Reopening the completed V0 roadmap.
- Treating Firebase as required for local dashboard use.
- Adding dashboard mutation paths without an ADR.
- Drafting V2-V5 child plans before their trigger conditions are met.
- Merging unrelated repo architecture graphs in fleet mode.
- Using demo dashboard data where credible local state is missing.
