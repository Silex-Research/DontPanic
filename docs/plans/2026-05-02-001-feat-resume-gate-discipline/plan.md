---
id: 2026-05-02-001-feat-resume-gate-discipline
title: Resume CLI gate discipline — require explicit --gate or --all
type: feat
tier: local
status: completed
date: "2026-05-02"
description: |
  Tighten the `jarvis resume` CLI so it cannot silently bypass gates the
  operator explicitly chose to keep armed. Bare `resume <plan>` currently
  clears EVERY plan-declared gate plus active breakers + active defers in
  one shot, with no per-gate confirmation. Discovered during dogfood of
  patch-completeness F001 (plan 2026-05-01-004): operator chose
  "approve pre_impl only, keep pre_merge armed" → assistant correctly ran
  `approve pre_impl` but then ran `resume`, which destructively cleared
  pre_merge as well, violating operator intent. The fix: bare `resume`
  exits 2 with a usage message; `resume --gate <name>` clears one
  gate (parity with `approve <name>`); `resume --all` is the explicit
  bulk-clear (existing behavior, behind a required flag). INBOX templates
  recommend `approve <gate>` for partial clearance.
motivation: |
  Real platform finding from real dogfood. The current bulk-clear default
  is dangerous because (a) operators reach for `resume` expecting "continue
  the volley," not "clear all my gates"; (b) the command provides no per-
  gate confirmation prompt; (c) the bypass is silent — the only signal is
  the gate-state.json history, which the operator doesn't typically read
  before the next dispatch. The cost of the current behavior: one
  successful operator-intent bypass already (this dogfood), and the audit
  trail shows it landed cleanly with no warning. Changing the default to
  safe-by-default forces operators to declare bulk vs. partial intent.
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
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Resume CLI gate discipline

## Thesis

`jarvis resume` should not be a one-keystroke bulk-clear of every armed
gate. The fix is small: require explicit intent via `--gate <name>` for
single-gate clearance or `--all` for bulk. Bare `resume` becomes a usage
error.

## Scope

In scope (1 feature, deliberately tight):

- **F001 resume CLI hardening.** Bare `resume <plan>` exits 2 with a
  usage message that surfaces both new flags + recommends
  `approve <gate>` for the common partial-clearance case.
  `resume <plan> --gate <name>` clears one gate (functional parity with
  `approve <name>`, accepted for ergonomic consistency).
  `resume <plan> --all` performs the existing bulk-clear behavior under
  an explicit flag. INBOX `gate_hit` template updated to recommend
  `approve <gate>` over `resume` for partial clearance.

Out of scope (recorded in decisions.jsonl):

- **Renaming `resume`** — semantic confusion ("resume" sounding like
  "continue execution" when it's actually "clear gates") is real but a
  breaking rename has wider blast radius. Deferred.
- **Auto-continue after gate clearance** — current flow requires operator
  to re-run `dispatch-from-plan --confirm` after clearing the last gate.
  Auto-continue would be ergonomic but is too magical for v1 (operator
  may have other state to verify before re-dispatching). Deferred.
- **Migrating existing scripts/docs to the new syntax** — only the
  CONTRIBUTING.md "Dependency maintenance" section needs an update;
  larger documentation sweep is out of scope.

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance summary

- F001: bare `resume <plan>` exits 2 with usage; `resume --gate <name>`
  clears one gate (verified: gate-state.json's `cleared_gates` gains
  exactly that one entry, history records `action: approve`-equivalent);
  `resume --all` matches today's bulk-clear behavior; INBOX template
  surfaces `approve <gate>` as the preferred path.
- Tests cover all four CLI shapes (bare / --gate name / --gate unknown /
  --all) with assertions on gate-state.json content + exit code.
- Existing tests stay green.
- The originating finding's evidence (gate-state.json + INBOX from plan
  2026-05-01-004) lives under `evidence/finding/` for audit trail.
