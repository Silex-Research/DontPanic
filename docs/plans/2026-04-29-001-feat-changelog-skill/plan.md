---
id: 2026-04-29-001-feat-changelog-skill
title: changelog skill — first supervised orchestrator dogfood
type: feat
tier: local
status: draft
date: "2026-04-29"
description: |
  Create `claude/skills/changelog/` — a deterministic, fixture-testable skill that summarizes a git revision range as operator-facing release notes. Mechanical task with a clear source-of-truth (git log + commit messages) and a deterministic output shape; the auditor's job is mechanical and the disagreement surface is narrow. Same shape as #692 (SKILL.md + Python module + tests + RESOLVER row), so any orchestrator behavior we observe during dispatch is signal about the orchestrator, not noise from the test subject.
motivation: |
  This is the first supervised orchestrator dogfood: dispatch via `jarvis orchestrate` (F004 + F005a volley + F006 + F007 + F008) on a non-trivial cross-cutting-shaped plan instead of running interactively. Goal is to measure, not just to ship the skill. The four signals to capture: (1) did INBOX gates pause cleanly at pre_impl and pre_merge, (2) did Claude+Codex audits converge or did disagreements get persisted, (3) did evidence land under audit/ and evidence/ correctly, (4) did the protected dirty files stay protected, and (5) did quota/cost telemetry remain interpretable. The skill itself is the test subject; the orchestrator is the system under test.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
quota_caps:
  claude: 2
  codex: 1
loop_caps:
  max_iterations: 1
  no_progress_threshold: 2
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/quota_check.py
  - scripts/maintainer/refresh-costs.sh
dependencies:
  - 2026-04-19-001-infra-cross-agent-orchestration
  - 2026-04-28-001-infra-financial-observability
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# changelog skill — first supervised orchestrator dogfood

## Thesis

Two goals, in order of priority:
1. **Stress-test `jarvis orchestrate`** on a real (non-trivial) plan with `pre_impl` and `pre_merge` gates, so we get telemetry on whether the supervisor + volley + INBOX work end-to-end under human-in-the-loop pacing.
2. **Ship `claude/skills/changelog/`** — a useful, deterministic skill.

Both goals are satisfied by the same artifact, which is exactly why this is the right first dogfood. Failure on goal 1 (orchestrator misbehaves) is informative regardless of whether goal 2 lands.

## Why changelog (not aso-audit, not #693)

- **Mechanical source-of-truth.** `git log` output is deterministic; the auditor's job reduces to "does the rendered changelog faithfully represent the commit range?" That keeps disagreement narrow.
- **No external dependencies.** No API keys, no fixtures from another system (unlike aso-audit's App Store Connect surface).
- **Same shape as #692.** SKILL.md + module + tests + RESOLVER row. If the orchestrator works on this, it likely works on the other #695 skills.
- **Avoids debugging two layers at once.** #693 (managed-agents skill) changes how the orchestrator dispatches *to* skills. Mixing that with "first time we run a real volley" is the wrong combination.

## What the skill does

Reads a git revision range (`--from <ref> --to <ref>`, defaulting to last tag → HEAD) and renders a markdown changelog grouped by Conventional Commits prefix (feat / fix / refactor / docs / etc.), with a summary of files changed per group and a short blurb per commit. Output is written to `evidence/changelog/<run-id>/CHANGELOG-<from>..<to>.md` and a JSON sibling. Deterministic given the same inputs (no LLM calls — pure git parsing + template rendering). Fixture mode reads `tests/fixtures/<name>/git_log.txt` instead of running git.

## What this dogfood measures

These are the questions the orchestrator run is supposed to answer. They're explicit so failure is informative:

1. **INBOX gate pacing.** Does the supervisor pause cleanly at `pre_impl` (before any code is written) and at `pre_merge` (after impl, before features.json flip)? Does `jarvis approve <plan-id> pre_impl` resume cleanly? Does the gate-pause state file stay consistent across approve / re-trip?
2. **Volley convergence.** Claude implements; Codex audits. Do they converge in 1 iteration on this mechanical task, or does the audit kick back? If kickback, does the second iteration reflect the audit findings, and does the disagreement.jsonl artifact populate when they don't agree?
3. **Evidence integrity.** Does `audit/<iteration>/<agent>.json` land with the right shape? Does `signoff.json` get written at termination? Do timestamps line up?
4. **Protected-path discipline.** The five `protected_paths` listed in the frontmatter must remain unmodified across the whole run. The supervisor's `command_guard` (F023) should refuse any agent attempt to write them. Verified by `git diff --stat` of those paths post-run.
5. **Quota/cost telemetry.** `~/.jarvis/quota_state.json` should reflect the volley's consumption. Cost-guard (when invoked manually post-run with a real budget for "jarvis" app) should not breach. Costs.json staleness shouldn't generate false positives.

## Out of scope

- Hooking changelog into a CI workflow or release pipeline — that's a downstream task once the skill exists.
- LLM-based summarization of commits — start deterministic; LLM-rewrite is a follow-up if operators want prose-better output.
- SpinDine / Glam / AXIOM-specific commit conventions — generic Conventional Commits parsing only.
- Modifying the supervisor itself. If we find an orchestrator bug during this run, we record it in `decisions.jsonl` and open a separate plan — we do NOT fix it inline. That keeps this dogfood's blast radius tight.
- The 49 baseline resolver warnings (D007 amendment from #692). Untouched.

## Risks

- **First real volley.** F005a passed synthetic disagreement (F005a-6) but has not run a real Claude+Codex volley on a non-trivial plan. Likely findings: prompt-template edge cases, JSON parse failures, audit-shape mismatches. Mitigation: tier `local` (single iteration cap) + 4h wall-clock + INBOX gates default to pre_impl + pre_merge.
- **Quota burn during debug.** If the volley loops or the auditor keeps kicking back, we burn Claude tokens and Codex calls. Mitigation: `loop_caps.max_iterations: 1` (one volley round, no auto-retry), and `quota_caps` of 2/1 caps total spend.
- **Operator latency at gates.** INBOX pausing means the supervisor stops and waits for `jarvis approve`. If the operator (me, you) takes a day to clear, the wall-clock cap fires. That's a feature, not a bug — but worth flagging.
- **Cost-guard inert.** D004 — config/cost_budgets.json ships sentinel zeros. Cost-guard won't alert during this run unless the operator populates it with a real "jarvis" app budget pre-run. Recommendation: set `Jarvis.gcp_monthly_budget_usd` to a placeholder ($50) for the duration of the run so cost-guard has something to report against, then revert.

## Acceptance (this plan)

`signoff: true` only when:

- F001 `passes: true` (the changelog skill itself ships, tests green, registered in RESOLVER.md, no new resolver warnings).
- The five measurement questions above each have a recorded answer in `decisions.jsonl` (D003–D007 reserved for these).
- `audit/` contains entries from both Claude and Codex.
- `signoff.json` written and shape-validates against `claude/shared/schemas/v1.0/signoff.schema.json`.
- All five protected paths verified unchanged.
- `scripts/sanitization_check.py` + `scripts/jarvis_doctor.py --skip-auth` + resolver `validate.py` exit 0 (warnings-only baseline OK).
- This plan validates against v1.0 schemas after every edit.

## Open decisions

See `decisions.jsonl`.

- **D001:** Volley executor pairing. Default Claude=implementer, Codex=auditor. Reverse on retry? (Pending.)
- **D002:** Cost-guard activation for the run. Populate `config/cost_budgets.json` with placeholder Jarvis budget pre-run, revert post-run? (Pending — operator decision.)

## Target

```yaml
target_env: dev
target_project: jarvis-a6ee1
```

## Provenance

First supervised orchestrator dogfood. Selected over #693 (managed-agents skill) and #695-aso-audit on review feedback (2026-04-28): mechanical deterministic task minimizes auditor disagreement surface, keeps debugging surface to "is the orchestrator working" rather than "is the agent layer working." Sequencing per agreement: this run informs whether #693 is safe to dispatch next via the same path.
