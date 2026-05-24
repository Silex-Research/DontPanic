---
id: 2026-05-24-001-feat-dashboard-value-language-ia-v0
title: Dashboard value-language IA v0
description: |
  Executable V1 child of the Dashboard Platform Roadmap. Integrates
  Claude Design dashboard assets and rewrites the local dashboard information
  architecture around operator and business value instead of internal
  DontPanic nouns. Keeps the dashboard read-only by default and command-emitter
  only; no new execution, review, architecture, or configuration surfaces.
type: feat
tier: cross-cutting
status: active
date: "2026-05-24"
goal_type: new_feature
surfaces:
  - ux
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
  wall_clock_hours: 8
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-24-003-infra-dashboard-platform-roadmap-v1
  - 2026-05-23-003-infra-visual-operating-console-roadmap-v0
  - 2026-05-23-004-feat-operator-console-v0
  - 2026-05-23-005-feat-dashboard-project-selector-v0
  - 2026-05-23-007-feat-plan-intake-readiness-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  objective_contract: ./objective_contract.json
orchestration:
  parent_plan_id: 2026-05-24-003-infra-dashboard-platform-roadmap-v1
  spawn_reason: operator_manual
  depth_limit: 3
---

# Dashboard Value-Language IA v0

## Motivation

The local dashboard now has credible DontPanic substrate: What Now actions,
capability status, project selection, state projection, build warnings, and
operator-local refresh. The UI still reads like an internal engineering
console. A non-technical operator or business stakeholder sees terms such as
gates, capabilities, supervisors, volleys, and manifests before understanding
the user value:

- what needs approval
- what is blocked
- what work is running
- which tools need setup
- whether the system is safe to keep using
- what command to copy when human action is required

This plan keeps DontPanic technically exact while changing the first-read
language to value-first labels with progressive disclosure. The UI should make
sense to a product owner, founder, or non-technical reviewer without hiding the
machine-readable identifiers agents and auditors need.

## Target

```yaml
target_env: dev
target_project: none
```

## Product Language Model

V0 adopts a two-layer language rule:

1. Primary labels describe user value and operational intent.
2. Technical DontPanic terms remain visible in secondary metadata, tooltips,
   details rows, source/provenance footers, and copied commands.

Examples:

| Internal term | Primary UI language | Technical disclosure |
|---|---|---|
| What Now | Home / Needs Attention | action item cache |
| Gate | Approval Needed | pre_impl / pre_merge gate |
| Capability | Tools & Setup | capability_id, owner_boundary |
| Supervisor / volley | Active AI Work / Active Reviews | supervisor_id, feature_id |
| Reconcile drift | Setup Drift | install snapshot comparison |
| Quota / breaker | Budget Guardrail | quota state / breaker name |
| Mission Control | Work | plan and feature lifecycle |
| Settings | Preferences | UI-local settings only |

The purpose is not to hide complexity. The purpose is to sequence it: value
first, exact substrate second.

## Boundaries

In scope:

- integrate Claude Design assets into the existing static dashboard shell
- replace Jarvis-era dashboard branding with DontPanic
- reorganize the V0 nav around value-first labels
- apply the existing four-band status taxonomy without adding new health bands
- render `optional` as a separate relevance chip, not a status color
- hide, delete, defer, or capability-gate non-core/demo tabs according to the
  decisions in this plan
- convert copy and empty states into non-technical, action-oriented language
- preserve exact CLI commands and technical IDs where they matter
- add dashboard copy/design documentation so future pages follow the same
  language rules
- establish the clean V1 shell/nav baseline that the Architecture Explorer
  integrates into

Out of scope:

- Architecture tab implementation
- Architecture may appear only as a muted future nav affordance with an exact
  command or plan pointer; the interactive architecture explorer ships in a
  separate child plan
- Review/Evidence tab implementation
- full Configuration editor or inline config mutation
- Agent Session Registry
- local executor, streaming logs, inline approve/reject, or browser terminals
- Firebase realtime dashboard mutation
- replacing the dashboard with a new framework

## V0 Navigation

Visible V0 surfaces:

| Nav label | Backing page | Audience question |
|---|---|---|
| Needs Attention | What Now | What needs me now? |
| Work | Mission Control, read-only | What work is planned, running, or done? |
| Tools & Setup | Capability Center | Which integrations are ready or need setup? |
| Health | Status/security/readiness summary | Is this install safe and current enough to use? |
| Preferences | Settings, UI-local only | How does this dashboard behave for me? |

Deferred or hidden surfaces:

- `Financial`: remove from core nav; Jarvis-era artifact.
- `Cloud Costs`: defer until a real cost capability manifest exists.
- `Security`: keep only as `Health` content backed by credible data; otherwise
  show a missing-data state with source/provenance.
- `Firebase`, `Linear`, `Discord`: future `Integrations` grouping, hidden unless
  capability data supports rendering.
- `Architecture`, `Review`, `Configuration`, `Agent Sessions`: future child
  plans, not this V0.

The sidebar may use `Home` as the route label if the first page title and
first-viewport content clearly say `Needs Attention`. The primary capability
page label must not be `Capabilities`; use `Tools & Setup` or `Connections`.

## Design Translation Strategy

Claude Design may produce React/JSX components. The runtime implementation
must port useful patterns into the existing vanilla static dashboard:

- design tokens, spacing, color, typography, and status treatments are adopted
  as CSS
- small components such as command chips, badges, status pills, provenance
  footers, and empty states are ported to vanilla DOM helpers
- full React page components are treated as visual specifications, not runtime
  dependencies
- drag-to-command is allowed only if the drop action previews or emits a
  command and never mutates state; otherwise drag affordances must be removed

## Multi-Project Requirement

Because the project selector is already shipped, design and implementation must
include at least one fleet-mode treatment:

- Home / Needs Attention groups actions by project in `All Projects` mode
- Work clearly distinguishes project-scoped state from fleet summaries
- Health shows whether warnings are global, project-specific, or fleet-level

## Design Asset Intake

Claude Design assets are expected under:

```text
docs/design/dashboard-value-language-ia-v0/
```

Acceptable inputs:

- visual mockups
- component inventory
- design tokens
- copy deck
- empty-state examples
- implementation notes

The implementation should adapt the existing static dashboard HTML/CSS/JS. A
framework rewrite is explicitly out of scope.

## Success Bar

A non-technical reviewer should be able to open the local dashboard and answer
these questions in under one minute:

- Is anything waiting on me?
- Is any AI work blocked or risky?
- Which tools are connected and which need setup?
- Is this DontPanic install healthy enough to keep operating?
- What exact command should I copy next?

An agent or technical operator should still be able to recover exact
DontPanic substrate from the same view:

- plan_id
- feature_id
- gate name
- capability_id
- source state file
- last updated timestamp
- exact CLI command
