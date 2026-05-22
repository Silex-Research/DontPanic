---
id: 2026-05-22-002-feat-capability-status-v0
title: Capability Status v0b — setup_steps extension, status CLI, lock-time advisory sidecar
description: |
  V0b of the External Capability Operations Roadmap
  (`2026-05-22-001`). Layered strictly additively on top of V0a
  (`2026-05-21-001` capability manifest consumer foundation): adds the
  `setup_steps[]` optional field to the existing capability manifest
  schema (no new schema directory), extends `capabilities.py` (no new
  package), ships `dontpanic capabilities status` CLI with JSON
  agent-handoff format + local cache, and emits a lock-time advisory
  sidecar that consumes the existing `external_refs[]` substrate +
  a new optional `requires_capabilities[]` plan field. Backfills
  `setup_steps[]` on the four checked-in manifests, deepest on
  `firebase-dashboard.json` (operator's real current blocker). No
  dashboard surface, no MCP exposure, no setup runner — those are
  V1/V2 per the roadmap.
type: feat
tier: cross-cutting
status: draft
date: "2026-05-22"
goal_type: new_feature
surfaces:
  - infra
  - docs
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
dependencies:
  - 2026-05-22-001-infra-external-capability-operations-roadmap-v0
  - 2026-05-21-001-feat-capability-manifest-consumers-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  objective_contract: ./objective_contract.json
orchestration:
  parent_plan_id: 2026-05-22-001-infra-external-capability-operations-roadmap-v0
  spawn_reason: operator_manual
  depth_limit: 3
---

# Capability Status v0b

## Why

V0a (plan `2026-05-21-001-feat-capability-manifest-consumers-v0`)
already shipped the manifest loader (F001 complete, passes:true) and
has probe/adapter `capability_id` binding work in-flight (F002, F003).
V0a turns ADR-001 from a convention into machine-checkable manifests
plus probe/adapter linkage — but no operator-facing surface reads the
manifests and tells the operator what is configured, what is missing,
and what to do next.

The operator's current Firebase realtime dashboard work is the
concrete first-touch case: `MCP_TUNNEL_URL`, `MCP_TUNNEL_TOKEN`,
`DONTPANIC_OPERATOR_UIDS`, the operator-side bridge, and deploy
credentials are all clearly marked as `operator`-owned in
`capabilities/firebase-dashboard.json`. V0b makes that information
actionable through the lightest possible consumer surface: a CLI that
reads manifests, runs declared probes, and emits human-readable +
JSON status. The JSON output IS the agent-handoff format.

## Relationship to V0a (plan 2026-05-21-001)

| V0a (manifest consumer foundation) | V0b (this plan — status surface) |
|---|---|
| F001 loader — DONE (passes:true 2026-05-21) | F001 `setup_steps[]` schema extension + manifest backfill |
| F002 probe `capability_id` binding — in-flight | F002 `dontpanic capabilities status` CLI (soft-depends on V0a F002 — degrades gracefully via `ProbeStatus.PENDING`) |
| F003 adapter registry `capability_id` binding — in-flight | F003 lock-time advisory sidecar (depends on V0a F002+F003 substrate where relevant) |

V0b does NOT re-implement the manifest loader or probe binding. F001
extends the existing `capabilities.py` module with a `SetupStep` type;
F002 CLI reads the loader's `CapabilityIndex` directly. PENDING
semantics let V0b ship usefully before V0a F002/F003 fully land.

## What This Plan Ships

- **`setup_steps[]` optional field on capability manifest schema**
  (`claude/shared/schemas/v1.0/capability.schema.json`). Added as
  additive, backward-compatible — `schema_version` const stays
  `"1.0.0"` (no new schema directory). Agent-conventions VERSION
  receives a minor bump to flag the additive change. Each entry:
  `{id, what, automatable: bool, command_template, verify_probe,
  human_required_reason}`.
- **`SetupStep` Pydantic model + field on `CapabilityManifest`** in
  the existing `scripts/dontpanic_orchestrate/capabilities.py` module
  (no new package directory — would collide with the module name).
- **`setup_steps[]` backfill on the four checked-in manifests**:
  firebase-dashboard ≥6 steps (CLI install, gcloud auth, project
  select, rules deploy, Cloud Function deploy, MCP bridge run, smoke);
  linear ≥4 (PP binary emit, adapter register, token paste, mapping
  validate); discord-notify ≥2 (webhook URL, smoke); agent-claude-cli
  ≥2 (install, auth). All `command_template` entries use placeholders
  (e.g. `<YOUR_TOKEN>`) — no real secrets.
- **`ProbeStatus.PENDING` enum value** with semantics
  `needs_probe_implementation / unknown`. Distinct from PASS / FAIL /
  WARN / ADVISORY and explicitly NOT a synonym for "blocked". A
  capability with PENDING probes can still be `ready` if its
  non-PENDING probes pass and its `requires` resolve.
- **`dontpanic capabilities status [<id>] [--format=text|json]
  [--profile=<name>] [--no-cache-write]` CLI**. Reads manifests, runs
  probes, computes per-capability status from the closed set `{ready,
  needs_setup, blocked, not_installed, optional}`. Text output: table
  with status badges + owner_boundary chips + `Next actions` list.
  JSON output: stable schema documented in
  `evidence/json-schema-doc.md` with `{capability_id, status,
  missing[], configured[], automatable[], human_required[],
  owner_boundary, next_actions[]}`.
- **`~/.dontpanic/capabilities-status.json` cache** written after
  every status run unless `--no-cache-write`. Downstream surfaces (V1
  dashboard, V1 MCP) will consume the cache rather than re-running
  probes.
- **Optional `requires_capabilities[]` plan frontmatter field**
  added to `plan.schema.json`. Backward-compat: absent or empty array
  = no advisory. Each entry: capability_id string.
- **Plan-lock advisory sidecar**. `dontpanic plan lock` reads
  existing `external_refs[]` (v1.10.0 substrate from
  `2026-05-20-001` F002, already landed) + new
  `requires_capabilities[]`, validates each capability_id against the
  manifest registry, and emits `evidence/required-capabilities.json`
  summarizing per-capability readiness. Lock output displays a
  warning chip when any required capability is not ready. **Lock
  proceeds — sidecar is advisory only, NOT a lock-blocker.**

## What This Plan Does NOT Ship

- No dashboard Capability Center view — V1 (roadmap-gated, both
  prerequisite + demand trigger required).
- No MCP `capabilities.get_status` tool — V1.
- No `dontpanic capabilities setup <id>` guided runner — V2.
- No mutation tools — read-only surface only.
- No new plan-lock blocking behavior — sidecar is advisory.
- **No new schema version directory** — `setup_steps[]` is added as
  an optional field on the existing v1.0 schema. `schema_version`
  const stays `"1.0.0"` since the addition is backward-compatible.
- **No new `capabilities/` package directory** — extends the existing
  `scripts/dontpanic_orchestrate/capabilities.py` module.
- **No re-implementation of work in V0a (plan 2026-05-21-001)** —
  manifest loader (V0a F001 done), probe `capability_id` binding (V0a
  F002 in-flight), adapter registry `capability_id` binding (V0a F003
  in-flight) are declared as dependencies or soft-dependencies, not
  re-scoped.
- No formal agent-conventions schema bump for the status JSON
  envelope — local schema doc in evidence.

## Target

```yaml
target_env: dev
target_project: null
```

DontPanic-internal infra plan. No external Firebase / Cloud project.
Code lives in:

- `scripts/dontpanic_orchestrate/capabilities.py` (extends existing
  module)
- `scripts/dontpanic_orchestrate/capabilities_status.py` (new CLI
  command implementation; sibling module, not package)
- `claude/shared/schemas/v1.0/capability.schema.json` (additive
  field)
- `claude/shared/schemas/v1.0/plan.schema.json` (additive
  `requires_capabilities[]` field)
- `capabilities/*.json` (backfilled `setup_steps[]` on the four
  existing manifests)

## Status

`draft` — pending pre-impl review + operator lock.
