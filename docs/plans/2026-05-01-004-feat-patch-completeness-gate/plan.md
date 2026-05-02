---
id: 2026-05-01-004-feat-patch-completeness-gate
title: Patch-completeness gate — block signoff when committed/staged surface is incomplete
type: feat
tier: local
status: active
date: "2026-05-01"
description: |
  Close the "works locally but missing from commit" failure class by adding a
  platform-level gate that inspects git state at signoff time and blocks when the
  committed + staged surface is insufficient to make the plan's tests/imports
  resolve. The gate covers four failure modes: (1) test imports a source file
  that is untracked or modified-unstaged; (2) source imports a module file that
  is untracked or modified-unstaged; (3) test file itself is untracked/unstaged
  so it never runs in CI; (4) generated/cache artifact (e.g. `__pycache__/`,
  `*.pyc`, `.coverage`, `.DS_Store`) staged accidentally. Plus a "non-empty
  unstaged dirty state requires an operator note" rule so unrelated WIP can't
  silently ride along on a signoff.
motivation: |
  Surfaced 2026-05-01 by operator-authored "Jarvis Platform Gap" review after
  observing that audit envelopes routinely flip `passes:true` while the actual
  commit is missing newly-imported modules or test files. Concrete recent
  symptoms: F002 stop-rule commit could have shipped without the inventory
  evidence file because nothing required it staged; ad-hoc edits to test
  fixtures slipped past audits because the auditor sees the test file but not
  the fixture's tracked-vs-untracked state. This plan adds the smallest
  platform-level surface that closes the class: capture git state at signoff,
  cross-reference imports/tests against the committed-or-staged set, refuse
  signoff on incomplete patches, and require an explicit "intentionally not
  included" note when unrelated dirty state exists. This is a foundation for
  later platform work (EC5 platform-fix, delivery-profile classifier) but
  ships independent value: every plan that runs through Jarvis after this
  lands gets the same completeness check for free.
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
  - 2026-05-01-003-feat-security-baseline
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Patch-completeness gate

## Thesis

Audit envelopes today record what the implementer *says* they did. They do not
record whether the resulting commit-ready surface (committed files + staged
files) is actually sufficient to make the implementer's tests run and imports
resolve. That gap allowed F002's stop-rule inventory to be on local disk while
the commit shipped without it, and allows a routine "added a new module"
implementation to land green if the operator forgets `git add`.

Closing the gap requires four small things: (1) capture git state at signoff,
(2) cross-reference imports/tests against the committed-or-staged set,
(3) refuse signoff when a finding fires, and (4) require an operator note when
unrelated dirty state exists so the operator at least *sees* what they're
shipping past.

## Scope

In scope (3 features):

- **F001 git state capture** — supervisor captures `git status --porcelain`
  parsed into `{staged, unstaged_modified, untracked, deleted_staged,
  deleted_unstaged}` at audit-envelope-write time. Lands as a sidecar evidence
  file `evidence/git-state.json` per audit pass — schema bump deferred (D004).
  Zero behavior change in this feature; it's the data substrate for F002 + F003.

- **F002 patch-completeness analyzer** — pure-function module
  `scripts/jarvis_orchestrate/patch_completeness.py` that takes the git-state
  capture + repo path and returns findings for the four failure modes named in
  the description. No supervisor wiring; F002 is the analyzer + tests, callable
  standalone.

- **F003 block-on-fail integration** — wire the analyzer into the supervisor's
  pre-signoff hook. Findings → `PatchCompletenessError` → supervisor refuses to
  flip `passes:true`. Operator override: `jarvis dispatch ... --allow-incomplete-patch
  <reason>` (D002 — plan-locked override, not durable). Unrelated unstaged dirty
  state requires `--unrelated-dirty-state-note <reason>` to proceed (D003).
  Both reasons land verbatim in signoff.json.

Out of scope (recorded in decisions.jsonl):

- **Schema promotion of git_state to audit-record** — captures live as sidecar
  evidence in this plan; promoting to `audit.schema.json` v1.4.0 is a separate
  conventions-bump plan (D004).
- **Cross-language import detection** — F002 ships Python-import detection only.
  Bash/yaml/markdown reference detection (e.g. workflow `uses:` pinning a
  helper script that's untracked) is a follow-up. Documented as a known
  limitation (D005).
- **EC5 platform fix** — bundling target-context formatting fix with patch-
  completeness conflates two different surfaces. Stays in its own plan
  (`feat-target-context-platform-fix`).
- **Delivery-profile classifier** — patch-completeness is a *universal* gate;
  it runs on every plan regardless of profile. The classifier is later platform
  work and consumes this gate as one of its mandatory phases.
- **Generated-artifact deny-list expansion** — F002 ships a conservative
  starter set (`__pycache__/`, `*.pyc`, `*.pyo`, `.coverage`, `.DS_Store`,
  `.pytest_cache/`, `node_modules/`). Project-specific additions (e.g. build
  output dirs) deferred to operator config in a follow-up plan (D006).

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance summary

- **F001:** `evidence/git-state.json` lands per audit pass with parsed git
  state; supervisor captures it without raising; existing audit fields
  unchanged.
- **F002:** `patch_completeness.check(git_state, repo_path)` detects all four
  failure modes against synthetic fixtures; returns empty list on a clean
  patch; pure function, no I/O beyond reading the repo.
- **F003:** supervisor refuses signoff when `check(...)` returns non-empty;
  `--allow-incomplete-patch <reason>` flag works and reason is recorded in
  signoff.json under `patch_completeness.override_reason`; unrelated unstaged
  dirty state requires `--unrelated-dirty-state-note` and lands in
  signoff.json under `patch_completeness.unrelated_dirty_state_note`.
- All existing orchestrate test modules stay green.
- No CLI behavior change for plans that ship a clean patch (the gate is
  invisible in the happy path).
