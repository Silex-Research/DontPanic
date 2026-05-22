---
id: 2026-05-22-001-infra-external-capability-operations-roadmap-v0
title: External Capability Operations Roadmap v0 — humans and agents configure and operate external integrations through a single discoverable surface
description: |
  Roadmap meta-plan that tracks the multi-version arc from
  capabilities/*.json manifest convention (already shipped via ADR-001)
  through CLI status, dashboard Capability Center, MCP projection, and
  guided setup. This plan documents the strategic outcome and future
  architecture; executable work lives in child plans. V0a and V0b are
  complete. The operator has now promoted V1/V2 from trigger-gated future
  milestones to concrete child plans so the roadmap can move through the
  orchestrator.
type: infra
tier: cross-cutting
status: active
date: "2026-05-22"
goal_type: infra
surfaces:
  - infra
  - docs
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
  - 2026-05-09-004-feat-firebase-dashboard-adapter-v0
  - 2026-05-10-001-feat-printing-press-adapter-skill
  - 2026-05-20-001-infra-external-integrations-bridge-v0
  - 2026-05-21-001-feat-capability-manifest-consumers-v0
  - 2026-05-22-002-feat-capability-status-v0
  - 2026-05-22-003-feat-capability-center-v1
  - 2026-05-22-004-feat-capability-guided-setup-v2
links:
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
---

# External Capability Operations Roadmap v0

## Status

**Tracking parent, active.** This plan documents the strategic arc and
tracks child-plan progress. It does NOT ship code itself. Child plans
(V0 / V1 / V2) carry the executable work. Earlier revisions kept this
plan `status: draft` indefinitely; the operator has now explicitly
promoted the roadmap into an active tracking parent so V1/V2 can be
implemented through the orchestrator while preserving the parent/child
audit trail. The convention of "meta-planning as a tracking plan" is
currently learned operator discipline, not first-class DontPanic schema;
see D003 + the `feedback_dontpanic_meta_planning_gap` memory note.

## Strategic Outcome

When the iterative arc lands, both humans and agents can answer five
questions for any external integration in seconds, through a single
discoverable surface:

1. **What is this capability?** Is it core or optional? PM tool,
   notification sink, dashboard adapter, agent CLI?
2. **What's configured?** Which fields/CLIs/services are already in
   place on this instance?
3. **What's missing?** Which credentials, env vars, deploy steps,
   account claims need to happen before this capability is usable?
4. **What's the next action?** Concrete command, link, or task — with
   `automatable` vs `human-required` clearly labeled.
5. **Who owns it?** DontPanic core, adapter author, or operator — the
   `owner_boundary` from the manifest, surfaced contextually.

The operator should never be in the position of asking "wait, do I need
Firebase?" or "where do I configure Linear?" The answer should be one
command (`dontpanic capabilities status firebase-dashboard`) or one view
(the static dashboard Capability Center). Same for agents — every
missing capability should be exportable as a structured task so an
operator can say "agent, configure whatever's automatable, then tell
me what only I can do."

## Final Outcome (Once Fully Implemented)

This is the north star — what DontPanic looks like when V0 + V1 + V2
have all landed:

### Capability is a first-class concept

Every external integration is declared by `capabilities/<id>.json`. The
manifest is the **single source of truth** for verification, setup
guidance, ownership boundaries, mutation rules, and per-step
automation. No setup logic lives in scattered docs, runbooks, or hand-
maintained checklists. Adding a new capability (Aha, Jira, Sentry,
GitHub Projects, OpenClaw broker, alternate agent CLIs, etc.) means
authoring one JSON file, declaring its probes against the prereq
registry, and (where the capability is more than a notification sink)
registering its adapter — at which point the capability appears in
every manifest-aware surface (CLI status, dashboard, MCP projection,
guided setup, plan-lock validation) without per-surface product code.
Some capabilities will still require non-trivial probe or adapter
code; the manifest convention reduces the per-surface multiplier, not
the per-capability minimum.

### One discoverable status surface, three projections

The same `capabilities-status.json` powers three surfaces, each
optimized for its consumer:

- **CLI** (`dontpanic capabilities status [--format=json]`) — humans at
  terminal, agents via subprocess, CI integrations. JSON output is the
  agent-handoff shape (see below).
- **Static dashboard Capability Center** — visual review for humans.
  Per-capability cards with status badges (ready / needs setup / missing
  credentials / not installed / optional / blocked), copyable commands,
  setup checklist, owner-boundary labels. Lives in the **static/core
  dashboard** — no Firebase dependency. Operators with no Firebase setup
  still see their Capability Center.
- **MCP read-only projection** (`capabilities.get_status`) — for
  agents reasoning about the operator's environment without shelling
  out. Read-only by design; mutations always go through governed paths.

### Agents and humans share the same task model

Every missing capability surfaces as a structured task with explicit
automation labels:

```json
{
  "capability_id": "firebase-dashboard",
  "status": "blocked",
  "missing": ["MCP_TUNNEL_URL", "MCP_TUNNEL_TOKEN", "DONTPANIC_OPERATOR_UIDS"],
  "human_required": ["create tunnel", "paste Firebase secret"],
  "automatable": ["verify CLI", "deploy rules", "run smoke test", "update plan evidence"]
}
```

Operators say "agent, configure whatever's automatable; tell me what's
human-only." Agents run the deterministic steps (CLI verifies, deploy
commands with confirm gates, rule deploys, smoke tests), produce a
short list of remaining human-required steps with exact commands, and
hand back. **Secrets are never stored or displayed by DontPanic** — only
their absence is surfaced, with the exact command the operator runs to
provide them. DontPanic guides and verifies; it does not become a
secret manager.

### Setup is guided, not improvised

When an operator (or agent) requests setup for a capability that's not
yet ready, `dontpanic capabilities setup <id>` walks the declared
`setup_steps[]` from the manifest. Each step has a probe to verify it,
a command template to run, and an `automatable` flag. The runner
executes automatable steps, displays human-required steps with exact
commands, and re-runs verification until the capability is `ready` or
explicitly blocked. Every mutation flows through governed paths (MCP
tools with confirm gates, or scoped shell commands recorded as
evidence). No silent failures — every attempt produces a durable record.

### Onboarding stays small

`dontpanic init --profile core` remains minimal — Python, claude CLI, git,
gh auth (when remote present). It never asks about Firebase, Linear,
Discord, or any specific adapter. Operators discover and configure
capabilities AFTER core is working, on demand, through
`dontpanic capabilities` — not upfront in onboarding. Profiles
(`firebase-dashboard`, `discord`, etc.) gate which capabilities the
doctor verifies, but they don't expand the init prereq list.

### Plans declare their capability needs

Every plan can declare `external_refs[]` and `requires_capabilities[]`
in frontmatter. At lock time, the orchestrator validates that referenced
capabilities exist in the manifest registry and emits
`evidence/required-capabilities.json` — an advisory sidecar that
documents what the plan needs, what's currently configured, and what's
blocked. Auditors can review whether a plan's evidence boundary matches
its declared capability needs. Future-you can return to a plan months
later and immediately know what external setup it required.

### The system improves itself

When an operator hits friction on a capability (missing step, wrong
mapping, confusing setup), the fix lives in one place — the manifest
file. The fix propagates to CLI, dashboard, MCP projection, guided
setup, and plan-lock validation simultaneously. There's one schema to
evolve, one JSON file per capability to keep current. Drift is visible
(schema validation, probe failures) rather than silent (out-of-date doc
nobody read).

## Future Architecture State

Single source of truth: `capabilities/<id>.json` declared per ADR-001.

Consumers (built in dependency order):

```
capabilities/*.json (declared)
    ↓
scripts/dontpanic_orchestrate/capabilities.py — loader + schema validator (V0a, shipped)
    ↓
    ├─→ doctor profile probes (V0a F002, in-flight)
    ├─→ adapter registry capability_id binding (V0a F003, in-flight)
    ├─→ setup_steps[] additive schema extension (V0b F001)
    ├─→ plan-lock required-capabilities.json sidecar (V0b F003)
    ├─→ CLI capabilities status [--format=json] (V0b F002)
    │       ↓
    │   ~/.dontpanic/capabilities-status.json (local cache)
    │
    ├─→ static dashboard Capability Center (V1, future + prerequisite + demand signal)
    ├─→ MCP capabilities.get_status (V1, future + prerequisite + demand signal)
    │
    └─→ guided setup runner (V2, future + demand signal)
            ↓
        setup_steps[] with automatable/human-required + verify probes
```

Manifest schema is `1.0.0` (current). V0b adds `setup_steps[]` as an
ADDITIVE optional field on the existing v1.0 schema — `schema_version`
const stays `"1.0.0"` because the change is backward-compatible.
Agent-conventions VERSION receives a minor bump to flag the additive
change. V1 / V2 may require a const bump if a non-additive change
becomes necessary; any such bump will be an explicit, breaking-aware
decision tracked in the child plan's decisions log. No new schema
directory (no `schemas/v1.1/`) is being created in V0.

## Milestones

### V0a — Manifest Consumer Foundation (ALREADY IN-FLIGHT)

**Child plan:** `docs/plans/2026-05-21-001-feat-capability-manifest-consumers-v0/`

**Scope:** Manifest loader + JSON schema validation
(`capabilities.py`), doctor/prereq probe `capability_id` binding,
adapter registry `capability_id` binding. Turns ADR-001 manifests from
prose into a machine-checkable contract that downstream consumers can
bind to.

**Status:** Completed. F001-F005 are passes:true.

### V0b — Status Surface (LOCKABLE NOW, layered on V0a)

**Child plan:** `docs/plans/2026-05-22-002-feat-capability-status-v0/`

**Scope:** Add `setup_steps[]` as an optional field to the existing
v1.0 capability schema (additive — `schema_version` const stays
`1.0.0`); extend the existing `capabilities.py` module with a
`SetupStep` model; ship `dontpanic capabilities status
[--format=json]` CLI with local cache and `ProbeStatus.PENDING`
semantics; ship plan-lock advisory sidecar that reads
existing `external_refs[]` + new optional `requires_capabilities[]`.
Backfill `setup_steps[]` on the four checked-in manifests, deepest on
`firebase-dashboard.json` (operator's real blocker).

**Status:** Completed. F001-F003 are passes:true. V0b produced the
`dontpanic capabilities status` CLI, `setup_steps[]`, cache, and
lock-time advisory sidecar.

**Coupling to V0a:** V0b F001 (schema additive) is independent. V0b
F002 (CLI) soft-depends on V0a F002 — when probe `capability_id`
binding is not yet shipped, V0b F002 degrades gracefully via
`ProbeStatus.PENDING` and an advisory note explaining the binding gap.
V0b F003 (lock-time sidecar) more strictly depends on V0a F002+F003 —
adapter `capability_id` binding is the natural seam where
`external_refs[].uri` maps to a registered adapter's capability.

### V1 — Static Dashboard Capability Center + MCP Read-Only Projection (ACTIVE CHILD)

**Child plan:** `docs/plans/2026-05-22-003-feat-capability-center-v1/`

**Scope:** Static dashboard "Capability Center" view that reads
`~/.dontpanic/capabilities-status.json` and renders per-capability cards
(status badge, owner-boundary, missing fields, copyable commands).
Lives in the static/core dashboard — NOT in the Firebase realtime
dashboard. MCP `capabilities.get_status` read-only tool exposes the
same data for agent consumption.

**Activation:** Operator override on 2026-05-22 promoted V1 to
executable child work. The static dashboard substrate exists under
`dashboard/`, and the operator explicitly asked to complete the roadmap
through orchestrator-driven child plans rather than waiting for more
calendar time.

**Status:** Draft child plan, ready to lock and dispatch F001 first.
F001 (dashboard view) and F002 (MCP read-only projection) are disjoint
enough to dispatch separately after lock if the operator wants
parallelism, but F001 is the recommended first slice because it
validates the human-review surface.

### V2 — Guided Setup Runner (DRAFT CHILD, SEQUENCED AFTER V1)

**Child plan:** `docs/plans/2026-05-22-004-feat-capability-guided-setup-v2/`

**Scope:** `dontpanic capabilities setup <id> [--print-steps]
[--automate-safe]` walks `setup_steps[]` from the manifest. Runs
automatable steps; surfaces human-required steps with exact commands.
Mutations flow through governed paths (MCP tools with confirm, or
scoped shell commands recorded as evidence). Failures produce durable
records. Re-runs verification probes until ready or explicitly blocked.

**Activation:** Drafted now per operator request to build out the full
roadmap, but sequenced after V1. V2 should not lock until V1 is accepted
because guided setup needs the V1 review/projection surfaces to make
human/agent handoff understandable.

**Status:** Draft child plan with F001 print-only setup, F002 guarded
automatable execution, and F003 setup evidence/roadmap close-out.

## Why a Meta-Plan, Not a Monolithic Plan

This roadmap deliberately separates strategy from execution:

- **Strategic outcome** + **final outcome** + **future architecture
  state** live here, in the meta plan.
- **What must be true for this slice** lives in each child plan.
- **How exactly to build** lives only in the current child plan.
- **What we are deliberately not building yet** lives in this plan's
  `decisions.jsonl`.

This prevents two failure modes:

1. **Too tactical** — fixing today's Firebase blocker and later
   rediscovering the same pattern for Linear, Discord, OpenClaw,
   alternate agent CLIs. The roadmap binds the tactical work to a
   coherent architectural vision.
2. **Too architectural** — building the full registry/dashboard/MCP/
   setup framework before one status CLI proves the shape. The slice-
   at-a-time discipline + explicit V1/V2 trigger conditions prevent
   premature scope expansion.

## Convention Caveat: Meta-Planning Is Not First-Class

DontPanic's plan schema does not yet have first-class support for
"roadmap" or "milestone" plans. There is no `plan_kind: roadmap` enum,
no `milestone: bool` flag on features, no `trigger_condition` field, no
lock-time refusal of milestone features without explicit unlock. The
ingredients exist (parent/child plans, dependencies field, decisions.jsonl,
status enum), but the discipline of "this plan tracks an arc, V1/V2 are
documented but not dispatchable" lives entirely in the operator's head
and these decisions.

This is a real product gap but NOT one we're fixing now. It will be
worth promoting to first-class after 2-3 roadmap-style plans benefit
from the convention. See decisions.jsonl D003 + memory entry
`feedback_dontpanic_meta_planning_gap.md` for the deferred work.

## Connection to Existing Artifacts

- **ADR-001** (`docs/adr/ADR-001-external-capability-model.md`) — the
  architectural commitment this roadmap operationalizes.
- **`capabilities/*.json`** — the four manifests (agent-claude-cli,
  discord-notify, firebase-dashboard, linear) this roadmap projects
  through CLI / dashboard / MCP / setup.
- **Plan 2026-05-09-004** (Firebase dashboard adapter) — pending
  amendment to cite `capabilities/firebase-dashboard.json` and split
  static dashboard from Firebase realtime adapter.
- **Plan 2026-05-20-001** (External integrations bridge) — adds
  `external_refs[]` to plan frontmatter; this roadmap's V0 validates
  refs against the manifest registry.
- **Plan 2026-05-10-001** (Printing Press adapter skill) — produces the
  per-service MCP binaries that adapters wrap and that capability
  manifests describe.

## Status (Reiterated)

`active` — tracking parent only. V0a and V0b complete. V1 child plan
(`2026-05-22-003-feat-capability-center-v1`) is the next executable
work. V2 child plan (`2026-05-22-004-feat-capability-guided-setup-v2`)
is drafted and waits on V1.
