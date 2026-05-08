---
id: 2026-05-08-001-feat-ruff-s-remediation
title: Ruff S baseline — remediate residual findings + enable in pyproject
type: feat
tier: local
status: completed
date: "2026-05-08"
description: |
  Bulk remediation of the Ruff S findings inventoried by
  `2026-05-01-003-feat-security-baseline` F002, which legitimately stop-ruled
  at 853 findings / 30 files and queued this follow-up. Two surgical slices:
  (F001) test-surface policy — add a targeted `tests/**` per-file-ignore for
  S101 only (assert is idiomatic test syntax, not runtime security posture);
  (F002) runtime S findings — remediate or justify the residual non-test
  findings one rule class at a time (S607, S108, S603, S310, S110, S104).
  Plan ends with `pyproject.toml` carrying `"S"` in `[tool.ruff.lint].select`
  and `ruff check --select S scripts/` exiting clean. Closes the bulk-
  remediation gap that keeps security-baseline F002 stop-ruled.
motivation: |
  Security-baseline F002 acceptance #2 explicitly states: when the first-wave
  inventory blows the stop-rule thresholds (>25 findings OR >8 files),
  F002 lands `passes: false` with `signoff_reason: scope_split_required`
  and a follow-up plan owns the bulk remediation as its own auditable scope.
  The first-wave inventory triggered both thresholds by 34× / 3.75×, and
  the inventory has since grown (current sweep: 2745 findings, dominated by
  S101 in test code). The stop rule did its job; this plan is the queued
  follow-up. Without this plan landing, security-baseline F002 stays blocked
  and the platform-integrity wave (patch-completeness gate already shipped)
  cannot close. The two-slice structure keeps test-policy and runtime-policy
  decisions auditable separately so the runtime slice never hides behind a
  blanket suppression.
agents_required:
  - claude
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
  - 2026-05-01-003-feat-security-baseline
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Ruff S baseline — remediation follow-up

## Thesis

Ruff S (bandit-port) is the right baseline security lint for this repo,
but enabling it correctly requires a one-time inventory pass to separate
**test-idiomatic patterns** (assert in test code) from **runtime
suppressions that warrant per-finding judgment** (subprocess shape, /tmp
usage, urlopen schemes). The locked stop-rule on security-baseline F002
forced that inventory; this plan does the actual remediation under a
discipline that prevents the very anti-pattern the stop rule was written
to guard against — a single sprawling commit full of blanket noqa.

## Scope

In scope (2 features):

- **F001 — Test-surface policy.** Add `"**/tests/**" = ["S101"]` (or the
  narrowest equivalent that covers the actual test directories) to
  `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml`. Pyproject
  comment cites the rationale: assert is idiomatic test syntax and not a
  runtime security posture concern. **No** broader test-tree ignores are
  added in this slice — only S101. F001 also lands the `"S"` rule
  enable in `[tool.ruff.lint].select`. After F001, `ruff check --select
  S scripts/` should drop from ~2745 findings to roughly the residual
  non-test set (~80–100 findings), inventoried for F002.

- **F002 — Runtime S findings remediation.** Walk the residual rule
  classes one at a time, in this order: S607 → S108 → S603 → S310 →
  S110 → S104. For each finding: (a) fix mechanically when correctness
  is improved, (b) add per-line `# noqa: SXXX  # <one-line rationale>`
  when the pattern is intentional and the rationale is real, (c) NEVER
  use blanket `# noqa: S` and NEVER add a per-file ignore for runtime
  code. After the walk, `ruff check --select S scripts/` exits clean
  (zero findings) — every residual finding is either fixed or carries an
  inline rationale. Per-rule-class evidence note records the count
  before/after and the disposition mix (fix / noqa / behavioral change).

Out of scope (deferred):

- **Adding S to non-script trees** (e.g. `claude/skills/`, `dashboard/`,
  Firebase functions). The locked AC walks `scripts/` only because that
  is what security-baseline F002's inventory covered; expanding the
  surface is its own future plan.
- **Behavioral refactors that change runtime semantics** beyond what a
  specific finding demands. If a fix would touch surfaces the finding
  doesn't directly cite, that work splits into its own commit /plan.
- **SAST coverage** (semgrep / CodeQL). Security-baseline D002 already
  framed Ruff S as baseline lint, NOT a SAST substitute. SAST stays
  deferred.
- **Re-running F001 on a non-`scripts/` tree.** F001 establishes the
  test-policy convention; reusing the same per-file-ignore in other
  trees lands when those trees are first S-checked.

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance summary

- **F001:** `pyproject.toml` `[tool.ruff.lint].select` includes `"S"`;
  `[tool.ruff.lint.per-file-ignores]` includes `"**/tests/**" = ["S101"]`
  with a comment citing why; `ruff check --select S scripts/` after F001
  drops to ≤ 100 residual non-test findings; inventory persisted at
  `evidence/f001/post-test-policy-inventory.txt`. F002 cannot land before
  F001.
- **F002:** Residual findings remediated rule-class-at-a-time. After the
  walk, `ruff check --select S scripts/` exits 0. Every `# noqa: SXXX`
  in `scripts/` (excluding `**/tests/**`) carries a one-line rationale on
  the same line. NO blanket `# noqa: S`. NO per-file ignore added for
  runtime code in this plan. Per-rule-class evidence note at
  `evidence/f002/<rule>-disposition.md` records before/after count + per-
  finding disposition.
- All existing orchestrate test modules stay green throughout.
- Closes security-baseline F002 by reference: a D-entry on this plan
  links the parent's F002 stop-rule outcome, and a D-entry on
  security-baseline records the resolution.
