---
id: 2026-06-04-002-feat-local-harness-adapter-runtime
title: Local harness adapter runtime (OpenClaw / Hermes / future)
type: infra
tier: cross-cutting
status: draft
date: "2026-06-04"
goal_type: new_feature
description: >
  Generic adapter layer that lets a LOCAL agent harness (OpenClaw, Hermes, or any
  future local harness) operate DontPanic safely — discover the command surface,
  invoke safe actions, and route human-required actions to the dashboard — WITHOUT
  becoming DontPanic. Supersedes the OpenClaw-specific 2026-05-03-002 by treating
  OpenClaw and Hermes as examples of one class.
motivation: >
  The OpenClaw-specific plan (2026-05-03-002) was ~70% pre-empted by shipped work
  (agent brief/commands/guide, `mcp serve`, NotifyEvent + Discord sink, event_copy,
  firebase_adapter) and was branded around one harness. The remaining real work is
  generic: profile a harness, detect it, expose DontPanic's existing command/MCP
  surface to it, and keep human-required steps on the dashboard. Build the class,
  not the instance.
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

# Local harness adapter runtime

## Target

```yaml
target_env: dev
target_project: none
```

In-repo adapter layer. Installing/booting an actual harness (OpenClaw, Hermes) is
an OPERATOR ACTION (credentials, local install) surfaced via 2026-06-04-003, not a
feature here.

## Problem / Motivation

Local agent harnesses (OpenClaw, Hermes, …) need to *operate* DontPanic — run its
commands, read its guidance, invoke safe actions — without being granted arbitrary
shell or being mistaken for a worker executor. DontPanic already ships the surface
(`agent brief|commands|guide|status`, `command_guidance`, `mcp serve`, NotifyEvent
+ Discord sink). What's missing is a generic, profile-driven adapter so any such
harness can be wired in by declaration rather than bespoke glue, with human-required
actions routed to the dashboard.

## Proposed Approach

Declarative **harness profiles** (a class, not OpenClaw-specific) + detection +
a thin bridge that hands the shipped command/MCP surface to a detected harness +
a routing rule that sends approval/credential/deploy actions to dashboard
ActionItems (`requires_human=true`). The notification/inbound-command bridge is
demand-gated to a later increment.

## Scope (in)

- F001 Harness profile schema + registry (OpenClaw + Hermes starter profiles).
- F002 Harness detection (`dontpanic harness detect`, read-only).
- F003 Command-surface bridge: expose shipped `agent`/`mcp serve` surface to a
  detected harness via its profile (config generation; reuse, don't rebuild).
- F004 Human-required routing: harness-invoked actions needing approval/creds/
  deploy emit dashboard ActionItems (`requires_human=true`) instead of executing.

## Scope (out)

- F005 (DEFERRED, demand-gated): inbound notification-command bridge
  (Discord/Telegram → MCP), lifting `notify_discord` into a harness skill.
- Installing/hardening any specific harness (operator action, see 2026-06-04-003).
- Multi-operator / team semantics.

## Acceptance

A harness is wired by adding a profile (no core code change); `harness detect`
truthfully reports installed profiled harnesses; a detected harness can read the
DontPanic command/guide surface and invoke only allowlisted safe actions; any
approval/credential/deploy attempt routes to a dashboard ActionItem rather than
executing. Branding is DontPanic-generic (no OpenClaw/Axiom/Jarvis in the contract).
