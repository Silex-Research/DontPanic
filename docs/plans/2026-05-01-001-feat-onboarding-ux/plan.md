---
id: 2026-05-01-001-feat-onboarding-ux
title: Onboarding UX — README "Run your first volley" + dispatch-from-plan CLI subcommand
type: feat
tier: local
status: active
date: "2026-05-01"
description: |
  Close the gap between "I have an authored plan" and "the supervisor is running it." Two deliverables: (1) a README "Run your first volley" section that walks a new operator through `quota-caps init` → `calibrate-claude` → `python -m jarvis_orchestrate <plan-id> --volley` → INBOX → `approve`/`resume`, including `--mode`, `--max-iterations`, target_env semantics, and the post-run artifact map (audit/, signoff.json, transcript.md). Refresh the stale "Setup checklist" to reflect supervisor maturity (F004/F005a/F006/F008/F023 all green; vendor-native quota tracker shipped). (2) A `python -m jarvis_orchestrate dispatch-from-plan <plan-id>` subcommand that is strict dry-run unless `--confirm` is passed: prints a 10-field pre-flight context block (resolved plan path, feature, tier, target_env, target_project, implementer/auditor defaults, declared gates, max_iterations, quota readiness) and exits 0 without dispatching. With `--confirm` and quota readiness == ok, calls `supervisor.dispatch_volley` in-process — no subprocess shell-out, no interactive prompt. CLI-first so it is reusable by Discord (Plan B) or any future automation; a wrapper skill can layer on later. A future opt-in `--ask` flag for interactive y/N is recorded as deferred (D006).
motivation: |
  Surfaced 2026-05-01 by operator review after F007 closeout: README quickstart stops at "validate your first plan" and "run tests" — the actual dispatch command never appears. New users could clone, bootstrap, and run tests, but could not run their first volley from README alone. Knowledge lives in plan decision logs and code docstrings. Separately, the friction of remembering the full `python -m jarvis_orchestrate <plan-id> --volley --implementer claude --auditor codex --feature F001 --max-iterations 3` invocation each time encourages copy-paste errors and skips the pre-flight context an operator should see (quota readiness, declared gates, target env). A strict-dry-run `dispatch-from-plan` subcommand turns dispatch into "show what's about to happen, then add `--confirm` to go" — same primitive the future Discord trigger and any automation will reuse.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  no_progress_threshold: 2
  wall_clock_hours: 2
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

# Onboarding UX

## Thesis

Two surfaces close the same gap: README documents the manual volley loop end-to-end so a new operator can run their first dispatch without reading code, and `dispatch-from-plan` adds a one-command preflight that surfaces dispatch context before the operator authorizes it. CLI-first (not skill-first) because the executable primitive needs to work from terminal, Claude Code, Codex, future Discord webhook trigger, and any cron — all of which can shell a CLI but not all of which run inside a Claude Code session.

## Scope

In scope:
- README.md additions: "Run your first volley" section + refreshed Setup checklist + brief mention of INBOX.md + pointer to existing `quota-caps`, `calibrate-claude`, `approve`, `resume`, `ps` subcommands
- New CLI subcommand `dispatch-from-plan <plan-id>` with dry-run-by-default behavior
- Tests covering: dry-run output completeness, `--confirm` requirement, refusal on missing/invalid plan, propagation of `--mode`, `--feature`, `--max-iterations`, `--implementer`, `--auditor` flags through to the underlying dispatch path

Out of scope (explicit deferrals):
- Skill wrapper layer over `dispatch-from-plan` (deferred to a follow-up if/when in-CLI ergonomics warrant; CLI-first establishes the primitive)
- Auto-dispatch from plan-artifacts skill (different decision class — would couple authoring and dispatch authorization)
- README translations / multi-format docs
- CONTRIBUTING.md / CODE_OF_CONDUCT.md content beyond the minimal pointer (already covered by F022)
- Discord integration (Plan B)

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance summary

- Fresh-clone operator can read README and successfully invoke their first volley without consulting decisions.jsonl or source code
- `dispatch-from-plan <plan-id>` with no `--confirm` flag prints the full 10-field pre-flight context block and exits 0 without dispatching, regardless of TTY state
- `dispatch-from-plan <plan-id> --confirm` calls `supervisor.dispatch_volley` in-process (no subprocess shell-out) when quota readiness is `ok`; exits 3 with kind-specific remediation when blocked by `missing_state` / `CONFIG_REQUIRED` / `CALIBRATION_REQUIRED` / `UNIT_MISMATCH`
- F001 references `dispatch-from-plan` in the README walkthrough only after F002 lands (F001 depends_on F002)
- All existing orchestrate test modules stay green
