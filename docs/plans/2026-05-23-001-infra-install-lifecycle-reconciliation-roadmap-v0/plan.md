---
id: 2026-05-23-001-infra-install-lifecycle-reconciliation-roadmap-v0
title: Install lifecycle reconciliation roadmap v0
description: |
  Tracking parent for making DontPanic continuously reconcile an operator's
  local install against the current platform expectations. This is not an
  upgrade-only flow: it answers "what drifted since this install was
  onboarded?" at any time, using an install snapshot as the comparison anchor.
type: infra
tier: cross-cutting
status: active
date: "2026-05-23"
goal_type: infra
surfaces:
  - infra
  - ux
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  no_progress_threshold: 2
  wall_clock_hours: 6
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-22-001-infra-external-capability-operations-roadmap-v0
  - 2026-05-19-002-feat-install-ux-hardening-v0
links:
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
---

# Install Lifecycle Reconciliation Roadmap v0

## Strategic Outcome

An operator who installed DontPanic days or weeks ago can ask one question:

```bash
dontpanic reconcile check
```

and receive a deterministic answer about whether the local install still
matches the current platform's expectations. This covers new capability
manifests, changed setup steps, stale generated status caches, regenerated
agent manifests, and future config/MCP/dashboard drift. The command is
continuous reconciliation, not a discrete package upgrade ceremony.

## Architecture Rule

Reconciliation compares **current platform expectations** to an
operator-local anchor:

```text
~/.dontpanic/install-snapshot.json
```

The snapshot stores no secrets. It records ids, versions, timestamps, tool
names, capability fingerprints, and selected profile metadata. Without this
anchor, "reconcile" degenerates into another doctor sweep. The snapshot is
therefore R0 and every later reconciliation area depends on it.

## Milestones

### R0 — Install Snapshot Primitive

Executable child: `2026-05-23-002-feat-install-reconcile-foundation-v0`

Scope:

- `dontpanic init` writes/refreshes `~/.dontpanic/install-snapshot.json`.
- `dontpanic reconcile baseline` creates the snapshot for existing installs.
- Snapshot includes DontPanic version, selected profile, manifest schema,
  agent-manifest schema, MCP tool names, capability ids, and setup-step
  fingerprints.

Status: active child, lockable now.

### R1 — Capability Drift Reconciliation

Executable child: `2026-05-23-002-feat-install-reconcile-foundation-v0`

Scope:

- `dontpanic reconcile check --area=capabilities`
- Detects new/removed capability manifests, changed setup steps, and stale or
  missing `~/.dontpanic/capabilities-status.json`.
- Text and JSON output for humans and agents.

Status: active child, lockable after R0 in the same child plan.

### R2 — Config and Agent Manifest Drift

Future child.

Scope:

- Compare local `~/.dontpanic/config.json`, project config, and
  `~/.dontpanic/agent-manifest.json` against the current schema/runtime
  expectations.
- Offer preview-only regeneration; mutation requires explicit confirmation.

Trigger: at least one concrete stale-config or stale-agent-manifest support
event after R0/R1 ship.

### R3 — MCP Tool Drift

Future child.

Scope:

- Compare installed snapshot MCP tool names with current `dontpanic mcp serve`
  tool registry.
- Tell MCP-aware agents when their discovery metadata is stale.

Trigger: one new MCP tool ships after this roadmap and an existing install
does not surface it through its agent manifest without manual intervention.

### R4 — Dashboard Reconciliation View

Future child.

Scope:

- Static dashboard renders reconciliation output as drift cards.
- No Firebase dependency. Firebase realtime remains an optional adapter.

Trigger: R0/R1 shipped and operators have used CLI reconciliation enough that
visual review would reduce setup friction.

## Out Of Scope

- `dontpanic doctor --security`: current security posture audit belongs in
  doctor, not reconciliation.
- Long-running `dontpanic dashboard serve`: local static build/open is the
  safer default. A server can ship later if live refresh or team sharing
  justifies the process lifecycle.
- Automatic package updates.
- Secret storage, token creation, Firebase project creation, or external
  account provisioning.
