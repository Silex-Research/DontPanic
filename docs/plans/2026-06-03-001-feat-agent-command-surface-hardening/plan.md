---
id: 2026-06-03-001-feat-agent-command-surface-hardening
title: Agent command-surface hardening
status: active
description: |
  Make every DontPanic command an interactive agent is likely to touch
  self-describing, policy-aware, and discoverable from the CLI. Agents should
  not infer workflow from flag docs alone; root help, workflow command help,
  machine JSON surfaces, and the generated agent brief must all point to the
  same safe operating model.
type: feat
tier: cross-cutting
date: "2026-06-03"
goal_type: new_feature
surfaces:
  - infra
  - docs
  - ux
agents_required:
  - claude
  - codex
human_gates:
  - pre_merge
loop_caps:
  max_iterations: 2
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-06-02-001-feat-control-plane-action-spine
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  objective_contract: ./objective_contract.json
---

# Agent command-surface hardening

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal CLI / agent-surface plan. No external service setup.

## Why

DontPanic now has the core primitives that make an interactive agent competent:
`agent brief`, `agent status`, `what-now`, `next`, command validation, the
ActionItem control-plane spine, and repo onboarding. But an agent that lands on a
specific command such as `dispatch-from-plan --help`, `next --help`, or
`plan lock --help` can still see ordinary flag documentation without the safe
workflow policy around it.

That recreates the original Grok failure in a smaller form: the agent is not
wrong because it cannot run commands; it is wrong because it starts from the
wrong surface and guesses the operating policy. A Harbor-style CLI makes the
agent entrypoint impossible to miss:

```text
Start here (for AI agents):
  harbor skills get harbor
```

DontPanic needs the same affordance, but grounded in its own model:

- Start with `dontpanic agent brief`, `dontpanic what-now --json`, and
  `dontpanic next --format json`.
- Execute only commands surfaced as automatable ActionItems or explicit
  candidate commands.
- Ask the human only when DontPanic marks an action as requiring human input.
- Do not manually drive feature-to-feature continuation from an outer agent.
- Understand which commands are read-only, mutating, paid/dispatching, human-gate,
  or dashboard/human-decision surfaces.

This is not a new orchestrator loop. It is command-surface hygiene so humans and
interactive agents discover and use the existing control plane correctly.

## Scope In

- Agent-facing command inventory over the real top-level command set and the
  high-risk subcommands agents interact with.
- Root `dontpanic --help` and workflow command help sections that point agents to
  the canonical operating flow.
- Machine-readable guidance for agents: stable JSON describing command class,
  risk, read/write/paid behavior, and preferred predecessor commands.
- A packaged DontPanic guidance artifact for agent/harness environments that
  want a “load this skill/guide” surface, without inventing a new command brain.
- Tests that fail when a new top-level command is added without agent-facing
  guidance.

## Scope Out

- Autonomous-safe cross-feature run loop. That belongs after the ActionItem
  classification and budget-reservation work.
- Fleet scheduler / auto-parallelism.
- Same-plan parallelism and worktree isolation.
- Desktop app wrapper.
- Rewriting existing command implementations beyond help/guidance surfaces.
- Replacing the generated `agent brief`; this plan extends discovery around it.

## Feature Order

F001 defines the pure command-guidance model. F002 populates the inventory.
F003 exposes the inventory as read-only JSON. F004 adds the root help
entrypoint. F005 adds class-specific workflow help snippets. F006 adds the
versioned local guide artifact. F007 adds coverage gates so future command
surfaces cannot drift.

## Risk

The main risk is duplicating the command manifest, command-validation specs,
ActionItem policy, and agent brief. The plan avoids that by treating F001's
inventory as a projection over existing sources of truth, not a hand-maintained
alternate command list. The second risk is over-teaching commands with long prose;
acceptance requires short agent sections and machine JSON, not a new manual in
every help page.
