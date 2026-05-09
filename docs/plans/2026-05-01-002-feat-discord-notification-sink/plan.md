---
id: 2026-05-01-002-feat-discord-notification-sink
title: Discord notification sink — webhook output mirroring terminal-notifier shape
type: feat
tier: local
status: completed
date: "2026-05-01"
description: |
  Add a Discord webhook output sink alongside the existing macOS terminal-notifier sink so operators can monitor supervised dispatches from anywhere (mobile, away-from-keyboard, multi-machine). Three modules land together: (1) `notify_discord.py` mirroring the shape of `notify.py` — webhook URL loaded from `JARVIS_DISCORD_WEBHOOK_URL` env or `~/.jarvis/discord.json`, fail-soft when absent (returns False, never raises); (2) compact internal event envelope (`NotifyEvent` dataclass: kind, severity, plan_id, feature_id, body, action_link, timestamp) consumed by both `notify.py` and `notify_discord.py` so future sinks add without touching emit sites; (3) wire the four required emit points (volley_start, gate_paused, breaker_tripped per kind, signoff, calibration_required) using D059's level matrix — `JARVIS_NOTIFY_LEVEL=quiet|normal|verbose` with quiet=escalation only / normal=plan boundary + escalation / verbose=plan boundary + escalation + per-feature terminal. D059 requires @mention on escalation posts only (cap hit, quota >=90%, INBOX waiting); other posts are plain. Rate limiting and per-channel routing are explicit deferred decisions.
motivation: |
  Surfaced 2026-05-01 by operator review after F007 closeout: README documents that supervisor progress is observable via INBOX.md + terminal-notifier + stderr — but terminal-notifier is macOS-only and tied to the operator's local workstation. Cross-machine and mobile observability requires a webhook sink. D059 (parent plan 2026-04-19-001) recorded the design intent in 2026-04-25: scoped out of F022 OSS readiness deliberately, parked for a future sub-plan named `infra-notification-sinks` or `feat-operator-notifications`. With F006/F008 landed and the vendor-native quota tracker shipped (the prerequisites D059 cited), the prereq dependency is satisfied and the plan can run. Compact-envelope design avoids the trap of building channel routing on first pass before the emit-point inventory is real; rate-limiting + mentions stay deferred unless D059 already requires (it does not, except @mention on escalation).
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
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/maintainer/refresh-costs.sh
dependencies:
  - 2026-04-19-001-infra-cross-agent-orchestration
  - 2026-04-30-001-fix-quota-tracker-vendor-native
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Discord notification sink

## Thesis

Operators need cross-machine + mobile visibility into supervised dispatches without sitting at a Mac with terminal-notifier installed. A Discord webhook is the smallest workable second sink: standard HTTP POST, no auth dance, free for personal use, supports embeds + @mentions. The first cut wires only the emit points the parent plan's D059 already inventoried, with a compact event envelope so the next sink (Slack, email, push) adds without rewriting emit sites.

## Scope

In scope:
- `scripts/jarvis_orchestrate/notify_discord.py` — webhook sink, fail-soft when URL missing
- Compact `NotifyEvent` dataclass + a small dispatcher that fans an event to all configured sinks
- Wire emit points at: volley_start, gate_paused, breaker_tripped (per kind: budget_ceiling, calibration_required, unit_mismatch, config_required, diminishing_returns, no_progress, iteration_cap, wall_clock, convergence_collapse, global_circuit_breaker), signoff, calibration_required (existing F006b kind-specific path)
- Level matrix per D059: `JARVIS_NOTIFY_LEVEL` env (quiet|normal|verbose, default normal); webhook absent → silent regardless of level
- @mention on escalation only (cap hit / quota ≥90% / breaker tripped to INBOX waiting)
- Sanitization: webhook URL never appears in committed code or test fixtures; `~/.jarvis/discord.json` is operator-local
- Tests: synthetic events × 3 levels × {webhook present / absent / malformed} matrix; escalation posts include INBOX link; @mention only on escalation

Out of scope (explicit deferrals, recorded in decisions.jsonl):
- Rate limiting / debounce (D059 silent; defer until real-world traffic shows a problem)
- Per-channel routing by event kind (single webhook URL, single channel — observed need first)
- Bidirectional integration (slash commands FROM Discord triggering supervisor actions)
- Slack / email / push sinks (compact envelope makes them tractable later; not first-cut scope)
- Embed styling / colors / icons beyond a basic "Jarvis" username + role-routed embed color (kept minimal)
- Replay / backfill of past INBOX events

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance summary

- `JARVIS_DISCORD_WEBHOOK_URL=<url> python -m jarvis_orchestrate <plan-id> --volley` posts to Discord at the four emit points per the level matrix
- Webhook absent / malformed / unreachable → supervisor proceeds normally, exit code unchanged, INBOX.md still written
- @mention appears only on escalation posts, never on plan-boundary or per-feature-terminal posts
- All committed code passes `python3 scripts/sanitization_check.py` (no real webhook URLs, no Discord IDs)
- Synthetic-event test matrix covers 3 levels × 3 webhook states × 5 event kinds (45 cases); all green
- Existing notify.py terminal sink continues to work unchanged (regression coverage)
