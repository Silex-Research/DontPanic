---
id: 2026-05-01-003-feat-security-baseline
title: Security baseline — secret-scan / CI hardening / SECURITY.md / key-age / Ruff S / actions pinning
type: feat
tier: local
status: active
date: "2026-05-01"
description: |
  Close the highest-risk-lowest-effort security gaps in the Jarvis platform itself (NOT project-level review — the existing `security-review` skill covers that). Three independently lockable features: F001 baseline hardening (sanitization_check.py secret-pattern expansion + CI workflow permissions + `SECURITY.md` stub + `jarvis_doctor` SA-key-age warning), F002 Ruff `S` ruleset as baseline security lint (explicitly NOT a SAST claim — coverage is bandit-style in-tree checks for subprocess/shell/eval/pickle/weak-crypto patterns; first-wave findings fixed or documented with targeted `# noqa: SXXX`), F003 SHA-pin GitHub Actions + add a Dependabot/Renovate updater policy (or document the absence and accept manual rotation). Each feature is small enough to land in one or two commits; bundling them into one plan prevents the "opportunistic patch" anti-pattern flagged in operator review.
motivation: |
  Surfaced 2026-05-01 by the security/infra research agent that audited the platform against industry baseline (10 dimensions). Three were absent (dependency security, SAST, supply-chain) and seven were partial. This plan closes the partial gaps that are 1-hour fixes each: secret regex coverage was 3 hardcoded strings (no AWS / GH / Anthropic / Slack / PEM / JWT shapes); CI workflow had no `permissions:` block (default token broad); no `SECURITY.md` so GitHub's Security tab shows no policy; SA keys live indefinitely with no operator nudge to rotate. The absent-class gaps (full SAST, supply-chain SLSA/Sigstore, dependency lockfile + audit) are NOT addressed here — they require larger plans with multi-contributor workflow changes and are explicitly deferred. Operator review note: "this is a small plan, not an opportunistic patch — touches release/security posture across the repo, deserves an audit pass."
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
  - 2026-05-01-001-feat-onboarding-ux
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Security baseline

## Thesis

Three small platform-level security wins, packaged together because individually they look opportunistic but together they form a coherent "baseline hardening" surface. Each feature lands independently with its own audit pass; the plan exists to keep their framing honest (Ruff S ≠ SAST; SHA-pin without updater ≠ pin maintenance solved) and to record the explicit deferrals so future operators don't relitigate.

## Scope

In scope (3 features):
- F001 baseline hardening: secret-pattern expansion in `sanitization_check.py`, CI workflow `permissions: contents: read`, `SECURITY.md` at repo root, `jarvis_doctor` warns on SA keys older than 90d
- F002 Ruff `S` (bandit) ruleset enabled as **baseline security lint** in `pyproject.toml`; first-wave findings fixed or documented with targeted `# noqa: SXXX` per occurrence
- F003 SHA-pin every `uses:` in `.github/workflows/*.yml` to commit hash + tag comment; add Dependabot OR Renovate config for the `github-actions` and `pip` ecosystems (pick one — D003 records the choice)

Out of scope (explicit deferrals, recorded in decisions.jsonl):
- `command_guard` wiring into executors — under-specified per operator review (D004); needs its own design spike before any implementation
- Audit-log redaction in `audit_writer.py` — false-positive redaction risks audit-integrity; needs its own plan with auditor review
- Full SAST (semgrep / CodeQL / repo-wide rule packs) — Ruff S is bandit-style in-tree checks, NOT a SAST substitute
- Dependency lockfile + `pip-audit` step — touches every contributor's workflow; separate plan
- Supply-chain (Sigstore / SLSA / SBOM) — multi-day infra slice; separate plan
- Network-egress controls (proxy / DNS deny-list for agent CLIs) — multi-day infra slice; separate plan

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance summary

- F001: `sanitization_check.py` covers AWS / GitHub / Anthropic / OpenAI / Slack / PEM / JWT shapes with source citations in code; CI workflow has `permissions: contents: read` at root; `SECURITY.md` present; `jarvis_doctor` warns on SA keys >90d
- F002: `[tool.ruff.lint].select` includes `"S"` baseline security lint; `ruff check scripts/` clean (every finding either fixed or documented with one-line `# noqa: SXXX` justification); `SECURITY.md` documents this is "baseline security lint" not SAST
- F003: every `uses: <action>@<tag>` in `.github/workflows/*.yml` is SHA-pinned with tag comment; Dependabot or Renovate config covers github-actions + pip ecosystems weekly; CONTRIBUTING.md (or `docs/maintenance.md`) names the bot and the manual update path
- All existing orchestrate test modules stay green
- No CLI behavior changes (no D007/D008/D009 work in this plan)
