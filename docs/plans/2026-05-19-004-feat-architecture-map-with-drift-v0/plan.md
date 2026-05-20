---
id: 2026-05-19-004-feat-architecture-map-with-drift-v0
title: Architecture map with drift detection v0
type: feat
tier: local
status: active
date: "2026-05-19"
goal_type: infra
surfaces:
  - infra
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
dependencies:
  - 2026-05-12-002-fix-harness-frictions-v4-1
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
orchestration:
  parent_plan_id: 2026-05-11-001-infra-state-projection-adapters-meta
  spawn_reason: operator_manual
  depth_limit: 3
child_charter:
  kind: implementation
  parent_objective: "Build a self-healing architecture surface: a structured JSON + joyful HTML representation of the codebase that auto-detects drift when the user builds outside DontPanic and auto-regenerates (but never auto-commits) when DontPanic dispatches changes. This is also the first consumer-ready context source for Plan 4.5's dontpanic new intake primitive — but Plan 4.5 falls back gracefully when the map is absent or stale."
  parent_acceptance_item: "Roadmap 2026-05-19 Plan 4: dontpanic architecture CLI emits architecture.html + architecture.json; drift detection in doctor catches manual edits outside DontPanic; supervisor regen-to-working-tree (no auto-commit) on dispatched code changes; opt-in pre-commit hook defaults to warn-only; architecture.json tracked + architecture.html gitignored."
  allowed_paths:
    - "scripts/dontpanic_orchestrate/architecture.py"
    - "scripts/dontpanic_orchestrate/**"
    - "scripts/dontpanic_doctor.py"
    - "scripts/dontpanic_orchestrate/tests/**"
    - "docs/architecture/**"
    - ".gitignore"
    - "docs/plans/2026-05-19-004-feat-architecture-map-with-drift-v0/**"
  forbidden_decisions:
    - "Do not implement auto-commit of regenerated architecture map. Regen lands in working tree; INBOX event + doctor warning surfaces; explicit operator commit only (operator review)."
    - "Do not commit generated architecture.html (gitignored). Track architecture.json only."
    - "Do not write outside docs/architecture/ for v0 output (single-repo, single output dir)."
    - "Do not regress any existing test in the current sweep (1929 baseline)."
    - "Do not break existing supervisor.dispatch_volley invariants — F004 hook must be additive + skip cleanly when the regenerator is unavailable."
  return_condition_summary: "F001 CLI + crawler + JSON output land independently shippable; F002 HTML renderer consumes JSON; F003 doctor drift probe; F004 supervisor regen-to-working-tree (no auto-commit); F005 opt-in pre-commit hook (warn-only default). architecture.json tracked, architecture.html gitignored. Full sweep ≥1929 green."
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
description: |
  Persistent + drift-aware architecture surface for the DontPanic
  codebase. Crawls source + plans, emits a stable JSON (machine
  contract for downstream agents — first consumer is Plan 4.5
  dontpanic new with graceful fallback) plus a joyful HTML
  (Thariq pattern: navigable, SVG diagrams, mobile-responsive,
  not edited by humans).

  Critical design constraints from operator review (v1.1 roadmap):
  - architecture.json is TRACKED, architecture.html is GITIGNORED.
    Fresh clones get machine-readable context; humans regenerate
    HTML locally; PR review stays clean.
  - Auto-regen runs into the WORKING TREE, never commits.
    Supervisor regen-to-working-tree emits INBOX event + doctor
    warning; operator decides whether to commit, amend, or
    discard.
  - Pre-commit hook DEFAULT = warn-only. Detect stale + print
    exact regen command. `--auto-regen` is opt-in via
    `dontpanic init` flag during install.
  - Drift detection uses a source-tree fingerprint (sha256 of
    sorted file list + content hashes) stored in JSON header.
    Three states: fresh / stale_minor (<5% files changed) /
    stale_major (≥5%). Advisory by default.
  - Idempotent regen (same source → same output). Stable
    JSON key order. Deterministic SVG IDs.
motivation: |
  Two pressures motivate this work:

  1. **Drift visibility.** Today there's no signal when the user
     edits files outside DontPanic (a quick fix in a different
     editor, a tooling change, a merge from an external branch).
     The codebase silently diverges from any cached understanding.

  2. **Context for downstream agents.** Plan 4.5's `dontpanic
     new` intake primitive needs a structured snapshot of the
     codebase to gather context efficiently without re-reading
     50+ files every time. architecture.json is that snapshot.
     But it must degrade gracefully — Plan 4.5 falls back to
     bounded ad-hoc reads when the map is missing or stale.

  Plus Thariq's HTML-effectiveness thesis: HTML is a richer
  artifact than markdown for a "single-page understanding" of
  the codebase. Worth validating with a real internal use case
  before betting on HTML for other outputs (install reports,
  audit summaries, etc.).
---

# Architecture Map with Drift Detection

## Thesis

A structured + stable JSON snapshot of the codebase + plans that
auto-regenerates (but never auto-commits) on DontPanic-driven
changes, warns on drift from manual edits, and renders to a
joyful HTML companion (gitignored, regen locally). First consumer
is Plan 4.5; future consumers will include audit summaries,
install reports, and the dontpanic new context gatherer.

## Scope

In scope (5 features):

- **F001** — `dontpanic architecture` CLI with subcommands
  `regen` (default), `status` (drift state), `diff` (compare
  source to stored fingerprint). Crawler walks
  `scripts/dontpanic_orchestrate/`, `claude/shared/`,
  `docs/plans/`. Emits `docs/architecture/architecture.json`
  with stable schema (version-stamped) + source fingerprint
  header. **Independently shippable.**

- **F002** — HTML renderer. Consumes `architecture.json`, emits
  `docs/architecture/architecture.html`. Joyful design per
  Thariq: navigable structure (tabs/anchors), SVG diagrams
  (module map, plan lifecycle, supervisor state machine),
  syntax-highlighted code snippets, mobile-responsive. HTML is
  gitignored.

- **F003** — `architecture_drift` probe in doctor. Reads
  stored fingerprint from `architecture.json` header, computes
  current source-tree hash, classifies as fresh / stale_minor
  / stale_major. Advisory by default; blocker via `--strict`.

- **F004** — Supervisor regen-to-working-tree hook. After
  `dispatch_volley` commits, inspect just-committed diff. If
  any file matches architecture-relevant globs, run
  `dontpanic architecture regen` into the working tree. Emit
  INBOX `architecture_regenerated` event. **Do NOT commit the
  regenerated map.** Operator sees changed file in `git
  status` and decides.

- **F005** — Opt-in pre-commit hook. Default behavior on
  staged source files: detect stale fingerprint → print
  exact regen command + warning → do NOT block, do NOT
  mutate. Opt-in `--auto-regen` mode (set via `dontpanic
  init` flag) regenerates + stages the JSON + prints what
  changed.

Out of scope:

- Real-time architecture-map streaming (changes pushed to a
  server). Local-file artifact only.
- Cross-repo architecture maps. Single-repo for v0.
- Diff visualization (snapshot-to-snapshot). v1 candidate.
- Architecture-map as audit envelope evidence. v1 candidate.
- Auto-committing the regenerated map. Operator-explicit
  commit only.

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance Summary

- F001 alone: `dontpanic architecture regen` from a clean
  clone produces valid `architecture.json` in ≤5s
- F002: HTML renders cleanly in Chrome/Safari/Firefox; SVG
  diagrams scale on mobile; gitignored entry verified
- F003: drift correctly classifies after manual edits
- F004: supervisor regen fires only on architecture-relevant
  diffs; lands in working tree; **never auto-commits**
- F005: pre-commit hook (warn-default) prints regen command
  but does NOT block or mutate; `--auto-regen` mode opt-in
- `architecture.json` is git-tracked; `architecture.html` is
  gitignored
- Full sweep ≥1929 green
