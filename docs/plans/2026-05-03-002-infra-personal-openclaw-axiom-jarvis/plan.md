---
id: 2026-05-03-002-infra-personal-openclaw-axiom-jarvis
title: Personal Axiom runtime — OpenClaw + DontPanic + dashboard + Discord
type: infra
tier: local
status: abandoned
date: "2026-05-03"
description: |
  Replace the current Axiom multi-tenant Cloudflare runtime direction with a
  personal, secure, local-first system. OpenClaw becomes the current upstream
  messaging and agent runtime. DontPanic remains the disciplined build
  orchestrator for plans, gates, audits, and evidence. The Axiom dashboard
  becomes the personal work console and shared progress surface. Discord is
  the primary collaboration app for joint development; Telegram remains the
  owner's private operator channel; WhatsApp is optional notifications only.
motivation: |
  The previous Axiom architecture optimized for a future shared SaaS-like
  multi-tenant product. That is now too much operational surface for the
  immediate goal: one personal system that builds real things on the user's
  laptop, coordinates with friends running their own local DontPanic instances,
  tracks work visually, and communicates safely. OpenClaw has caught up on
  runtime operations, channel support, dashboard, security audit, device
  pairing, and automation. DontPanic has the stronger build-governance model.
  This plan keeps the useful pieces and deletes the unnecessary tenant
  infrastructure for now.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
  - on_escalation
loop_caps:
  max_iterations: 2
  no_progress_threshold: 2
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
protected_paths:
  - ~/.dontpanic/
  - ~/.dontpanic/config.json
  - ~/.dontpanic/projects.json
  - ~/.dontpanic/agent-manifest.json
  - ~/.openclaw/openclaw.json
  - ~/.openclaw/.env
  - ~/.openclaw/credentials/
  - $HOME/Documents/GitHub/Jarvis/.secrets/
  - $HOME/Documents/GitHub/*/.dontpanic/dontpanic.json
  # Legacy DontPanic/Jarvis compatibility paths remain readable during migration.
  - ~/.jarvis/
  - $HOME/Documents/GitHub/*/.jarvis/jarvis.json
  - $HOME/Documents/GitHub/axiom/packages/workspace/SOUL.md
  - $HOME/Documents/GitHub/axiom/packages/workspace/AGENTS.md
dependencies:
  - 2026-05-03-001-feat-global-install-project-registry
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  inbox: ./INBOX.md
---

# Personal Axiom Runtime

## Target

```yaml
target_env: local
target_project: personal-axiom
primary_runtime: openclaw@2026.5.2
builder_orchestrator: dontpanic
dashboard: axiom-dashboard-personal
primary_collaboration_channel: discord
private_operator_channel: telegram
optional_notification_channel: whatsapp
```

## Architecture

```text
Owner / friends
   |
   +-- Discord project server  <--- shared coordination, deconfliction, status
   +-- Telegram private DM     <--- owner-only approvals and alerts
   +-- WhatsApp optional       <--- human notifications only
   |
OpenClaw local gateway on laptop
   - loopback or tailnet-only access
   - channel pairing / allowlists
   - security audit enabled
   - narrow DontPanic command wrapper
   |
DontPanic local orchestrator
   - project registry
   - `~/.dontpanic/config.json`
   - `~/.dontpanic/projects.json`
   - per-project `.dontpanic/dontpanic.json`
   - plans, gates, audits, evidence
   - implementer/auditor workflows
   - protected path and quota controls
   |
Axiom personal dashboard
   - Kanban / project progress
   - DontPanic active supervisors and gates
   - plan/evidence links
   - OpenClaw status summaries
   - security/approval queue
```

## Scope

### F001 — Install and harden current OpenClaw

Install `openclaw@2026.5.2` locally, create `~/.openclaw/openclaw.json`, and
run OpenClaw in a local-first posture:

- Gateway binds to loopback by default.
- Gateway auth token/password is generated and not committed.
- Control UI is not public.
- `openclaw security audit --deep` is part of acceptance.
- Telegram/Discord/WhatsApp are configured only after explicit human action
  supplies or confirms tokens and app credentials.

### F002 — Port useful Axiom identity files into OpenClaw workspace

Create trimmed OpenClaw workspace bootstrap files from Axiom:

- `SOUL.md`: keep identity, epistemology, voice, security posture.
- `AGENTS.md`: keep action tiers, dashboard reporting, group chat behavior;
  remove Cloudflare/R2/container-specific assumptions.
- `TOOLS.md`: replace `/root/clawd`, R2, and `clawdbot` references with local
  OpenClaw/DontPanic/Axiom references.
- Add a small `DONTPANIC.md` or section in `TOOLS.md` describing allowed DontPanic
  commands and approval rules.
- Prefer canonical DontPanic paths and env vars: `~/.dontpanic`,
  `.dontpanic/dontpanic.json`, `DONTPANIC_HOME`, `DONTPANIC_*`.
- Treat `~/.jarvis`, `.jarvis/jarvis.json`, and `JARVIS_*` as readable legacy
  fallback only.

### F003 — DontPanic bridge for OpenClaw

Expose DontPanic through a narrow wrapper rather than free-form shell:

- status: `dontpanic ps`, quota/caps status, active gates.
- intake: create plan drafts from a brief.
- dispatch preview: dry-run `dispatch-from-plan`.
- dispatch confirm: requires human approval gate.
- approve/resume: owner-only via Telegram or direct Control UI, not group chat.
- discovery: use `~/.dontpanic/agent-manifest.json` when present.

The bridge must never allow arbitrary shell passthrough.

### F004 — Axiom dashboard becomes the personal command center

Retain Axiom's differentiated dashboard surfaces:

- Kanban board and task modal.
- Project and agent filters.
- DontPanic plan status, gates, audit/signoff links.
- OpenClaw channel/runtime health.
- Security alerts and approval queue.

Remove or archive for now:

- tenant provisioning
- KV tenant config
- Cloudflare router/canary shards
- per-tenant R2 snapshots
- multi-user Firebase onboarding
- tenant AI proxy/billing controls

### F005 — Discord collaboration and development deconfliction

Use Discord for joint app work:

- one Discord server for shared development
- category per app
- channel/thread per feature/bug
- one task = one GitHub issue + one DontPanic plan + one branch + one Discord thread
- each collaborator runs local DontPanic/OpenClaw
- dashboard aggregates shared progress from GitHub/DontPanic artifacts, not chat logs alone

## Security Baseline

OpenClaw is not the authority for broad laptop access. DontPanic is the authority
for build work, and human gates are the authority for risky action.

Required baseline:

- Gateway: loopback by default; tailnet or SSH tunnel for remote access.
- Channels: `dmPolicy: "pairing"` or strict allowlists.
- Groups: require mention, no broad automation tools.
- Tools: messaging profile by default; filesystem workspace-only where possible.
- Exec: deny or ask by default outside DontPanic-approved work.
- DontPanic: no destructive commands without plan/gate.
- Discord: project coordination only; no owner-only approvals in shared rooms.
- Telegram: owner-only approvals and high-signal alerts.
- WhatsApp: optional notify-only path.

## Implementation Order

1. Install OpenClaw and run first audit.
2. Create OpenClaw workspace bootstrap files from trimmed Axiom files.
3. Configure Discord first, then Telegram. Leave WhatsApp until needed.
4. Add DontPanic bridge wrapper and test read-only status calls.
5. Add dashboard ingestion for DontPanic plans/gates and OpenClaw health.
6. Add Discord/GitHub deconfliction conventions.
7. Archive Cloudflare multi-tenant runtime in Axiom docs.

## Acceptance Summary

- `openclaw --version` reports `2026.5.2`.
- `openclaw security audit --deep` has no critical findings for the intended local setup.
- OpenClaw Control UI works locally.
- Discord bot can post/read in a test project channel with allowlists.
- Telegram owner DM works for private alerts/approvals.
- DontPanic status can be requested through OpenClaw without arbitrary shell access.
- Axiom dashboard shows at least one DontPanic plan, one active/blocked gate state,
  and one Kanban item linked to a plan/branch/issue.
- No secrets are committed.
