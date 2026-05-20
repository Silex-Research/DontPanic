---
id: 2026-05-19-002-feat-install-ux-hardening-v0
title: Install UX hardening v0 — doctor profiles + init + smoke test + HTML report
type: feat
tier: cross-cutting
status: draft
date: "2026-05-19"
goal_type: new_feature
surfaces:
  - infra
  - docs
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
  - 2026-05-19-003-fix-plan-schema-orchestration-fields
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  objective_contract: ./objective_contract.json
orchestration:
  parent_plan_id: 2026-05-11-001-infra-state-projection-adapters-meta
  spawn_reason: operator_manual
  depth_limit: 3
child_charter:
  kind: implementation
  parent_objective: "Fix first-user pain. New users hit three silent blockers in sequence (missing GitHub PAT, wrong Python version, missing codex CLI) — each discoverable only after failure. The doctor exists but doesn't probe these. Widen doctor into declarative probe registry with profile filtering + JSON output, add `dontpanic init` interactive installer, add a synthetic smoke test, and emit an HTML install report. Bound: F001 ships independently (operator pause point); F002-F004 layer on after."
  parent_acceptance_item: "Roadmap 2026-05-19 Plan 2: dontpanic doctor surfaces missing GitHub auth/Python version/codex CLI without dispatching a paid volley to discover them; new user runs `dontpanic doctor --profile=core --json` and gets accurate red/green in <=10s; `dontpanic init` walks a first-touch checklist; smoke test catches the three first-user blockers; HTML install report renders cleanly across browsers."
  allowed_paths:
    - "scripts/dontpanic_doctor.py"
    - "scripts/dontpanic_orchestrate/**"
    - "scripts/dontpanic_orchestrate/init/**"
    - "scripts/dontpanic_orchestrate/smoke/**"
    - "scripts/dontpanic_orchestrate/tests/**"
    - "docs/plans/2026-05-19-002-feat-install-ux-hardening-v0/**"
    - "README.md"
    - ".gitignore"
  forbidden_decisions:
    - "Do not auto-create GitHub PATs. Operator decision — too sensitive. PAT-creation is copy-paste only, never executed by init."
    - "Do not auto-generate Firebase SA keys for <firebase-project-id>. Existing bootstrap.sh handles that flow under explicit --create-key. Init may surface the gap with a fix_command pointer; it must not execute."
    - "Do not require Firebase auth or gcloud for --profile=core. Core profile is for any DontPanic user, not just the maintainer. Firebase gates are firebase-dashboard / openclaw / maintainer profiles only."
    - "Do not install dependencies outside safe scopes — no sudo, no system Python modifications, no pipx --force, no global brew package installs without --auto-fix-safe being explicit per probe."
    - "Do not add a `maintainer` profile in F001. Maintainer profile lands in a future plan (Roadmap Plan 5/7); F001 stays consumer-facing. Plan 2 ships core + discord + firebase-dashboard + openclaw + ci."
    - "Do not regress any existing test in the current sweep (2036 baseline post-Plan 4 F003+F005)."
    - "Do not break `dontpanic doctor` (no flags) backwards compatibility — existing exit-code matrix (0/1/2) preserved; new --profile flag opt-in."
    - "Do not target Windows in v0. macOS + Linux only. Document the gap; don't probe for it."
  return_condition_summary: "F001 ships an independently usable `dontpanic doctor --profile=<core|discord|firebase-dashboard|openclaw|ci> --json` with the declarative probe registry, accurate red/green in <=10s, structured JSON for agents. F002 ships `dontpanic init` interactive + --non-interactive installer (safe auto-fixes only). F003 ships `dontpanic smoke` synthetic dispatch (no paid API). F004 ships HTML install report (single-page, no JS framework, mobile-responsive, gitignored). Full sweep >=2036 green; sanitization clean."
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
description: |
  First real user hit three install blockers in sequence:
  1. GitHub PAT missing (silently, until first `git push`)
  2. Python version wrong (3.10+ required for `|` union types; firebase_admin warned of 3.10.13 deprecation)
  3. Codex CLI not installed (silent until first `--auditor codex` dispatch)

  Each blocker was *discoverable* only after a failure. The doctor exists
  but doesn't probe these three.

  Four features, F001 independently shippable + ship-first per roadmap:

  - **F001** — Declarative `PrereqProbe` dataclass + profile registry
    (core / discord / firebase-dashboard / openclaw / ci) + ~10 initial
    probes + `--profile=` and `--json` CLI flags + stable JSON schema.
    Network probes parallel + capped at 2s each. Default profile=core.
    Conditional GitHub auth language. Bounded preflight ≤10s.
    **Land + assess delta before committing to F002-F004.**
  - **F002** — `dontpanic init` interactive installer + --non-interactive
    mode. Idempotent re-runs.
  - **F003** — Smoke test harness: synthetic plan + mocked executors
    exercising `dispatch_volley` end-to-end without paid API calls.
  - **F004** — HTML install report (Thariq pattern). Single-page,
    self-contained, no JS framework, mobile-responsive, gitignored.

  All four features stay within `scripts/dontpanic_orchestrate/` (new
  init/ + smoke/ subpackages) + `scripts/dontpanic_doctor.py`.
motivation: |
  Doctor is the first-touch authority for a new user. Right now it's
  silent on the three pieces a new user actually needs. The user has to
  fail at git push, then fail at a paid volley, then read the codex
  setup docs in the wrong order to figure out what's missing.

  Plan 3 (schema mismatch fix) shipped first so this widening doesn't
  land on top of a known false-fail in strict mode. Plan 4 (architecture
  map with drift) shipped first so this plan can consume architecture.json
  as a context source for the smoke test fixtures.

  Plan 2's wins compound: F001 alone materially improves first-user
  pain (operator pause point); F002 turns "run a doctor + read the
  output" into a guided walkthrough; F003 catches the same three
  blockers in CI before they ship; F004 makes the report linkable +
  shareable for support / community help.

  Out of scope (per roadmap):
  - Auto-creating GitHub PATs (too sensitive)
  - Auto-generating Firebase SA keys (bootstrap.sh handles this)
  - Windows support (macOS + Linux only v0)
  - Reusable profile authoring UX (operator-defined custom profiles
    — v1 candidate)
  - `maintainer` profile (Roadmap Plan 5/7 — agent-conventions remote
    + maintainer-only probes)
---

# Install UX Hardening v0

## Thesis

Doctor is the first-touch authority for a new user. Right now it's
silent on the three pieces a first user actually needs. Widen it into
a declarative probe registry with profile filtering + JSON output
(F001, ship-fast), then layer `dontpanic init` (F002), a synthetic
smoke test (F003), and an HTML install report (F004) on top.

F001 ships independently and materially improves first-user pain on
its own. F002-F004 are sequenced after the operator assesses F001
delta.

## Scope

In scope:

- **F001** — Declarative `PrereqProbe` dataclass at
  `scripts/dontpanic_orchestrate/prereq_registry.py` + profile registry
  (core / discord / firebase-dashboard / openclaw / ci) + ~10 initial
  probes wired into `scripts/dontpanic_doctor.py`. New CLI flags:
  `--profile=<name>` (default `core`), `--json` already exists (extended
  with the prereq probe results in stable schema). Network probes
  parallel + 2s cap each. Full sweep ≤10s wall clock.
- **F002** — `dontpanic init` interactive installer at
  `scripts/dontpanic_orchestrate/init/__init__.py`. Walks the doctor
  output, presents checklist, executes safe auto-fixes
  (`brew install codex`, `pip install -e .`), prompts copy-paste for
  unsafe ones (token creation, SA key generation). `--non-interactive`
  mode for agent installers. Idempotent re-runs.
- **F003** — Smoke test harness at
  `scripts/dontpanic_orchestrate/smoke/__init__.py`. Synthetic plan
  fixture + mocked claude/codex executors that exercise `dispatch_volley`
  end-to-end without paid API calls. Wired into `dontpanic init` as the
  final step + available standalone as `dontpanic smoke`.
- **F004** — HTML install report renderer at
  `scripts/dontpanic_orchestrate/init/report_html.py`. Pure transform
  from the JSON output of `dontpanic doctor --json` + `dontpanic smoke
  --json` into a single-page self-contained HTML document. Joyful
  design (per Thariq), mobile-responsive, no JS framework, no external
  CSS, copy-paste friendly. Output is gitignored; operator regens on
  demand via `dontpanic init --report` or `dontpanic doctor --report`.

Out of scope:

- Auto-creating GitHub PATs (operator decision — too sensitive)
- Auto-generating SA keys for <firebase-project-id> (existing bootstrap.sh
  handles this flow under explicit --create-key)
- Installing dependencies outside safe scopes (no sudo, no system
  Python modifications, no pipx --force, no global brew without
  per-probe auto_install_safe=true)
- Windows support (macOS + Linux only for v0; document the gap, don't
  probe for it)
- Reusable profile authoring UX (operator-defined custom profiles) — v1
- `maintainer` profile (Roadmap Plan 5/7 — agent-conventions remote)
- README rewrite for first-time visitor (Roadmap defers to after F001
  delta assessment)

## Target

```yaml
target_env: dev
target_project: none
```

## Sequencing within Plan 2

**F001 ships independently and is the first material improvement to
first-user pain.** Operator can pause after F001 to assess actual
delta before committing tokens to F002-F004. F002-F004 are sequenced
after F001 closes.

## Acceptance Summary

- **F001**: `dontpanic doctor --profile=core --json` returns accurate
  red/green for the three first-user blockers (GitHub auth, Python
  ≥3.10, codex CLI) in ≤10s wall clock. JSON output is stable schema.
  Default profile = core. `--profile=firebase-dashboard` adds Firebase
  + gcloud + SA key probes. **`--profile=core` never tells a user to
  install Firebase or clone agent-conventions.**
- **F002**: `dontpanic init` runs doctor, presents checklist, executes
  safe auto-fixes, prompts for unsafe. `--non-interactive` flag for
  agent installers errors with structured output instead of prompting.
  Re-runnable mid-install (idempotent). Honors `--profile=` flag.
- **F003**: `dontpanic smoke` runs a synthetic plan through
  `dispatch_volley` with mocked executors. Catches the three first-user
  blockers by failing fast with a clear error when any dependency is
  missing. No paid API calls. Bounded ≤30s wall clock.
- **F004**: `dontpanic init --report` and `dontpanic doctor --report`
  emit a single-page HTML at `docs/install-report.html` (gitignored).
  Renders cleanly in Chrome/Safari/Firefox on macOS + Linux. Mobile-
  responsive. Self-contained (no JS framework, no external CSS, no
  external fonts).

## Cross-feature invariants

1. **Backwards-compatible doctor.** `dontpanic doctor` with no flags
   keeps its existing exit-code matrix (0=pass, 1=warn, 2=fail) and
   existing probe set. New profile-aware probes are additive; default
   profile=core filters them down to a sensible-for-everyone set.
2. **No silent failures.** Every probe has a `fix_url` AND `fix_command`
   (or escalation message). Doctor exits with structured "what to do
   next" if anything is red.
3. **Network-bounded preflight.** Network probes (anthropic API
   reachability, openrouter ping, etc.) run in parallel with a 2s cap
   each. Full sweep ≤10s wall clock.
4. **Dual-channel output.** Pretty terminal output for humans
   (red/green checkboxes, copy-paste commands), structured JSON for
   agents. Exit code unchanged.
5. **Safe-by-default auto-install.** `auto_install_safe=true` is opt-in
   per probe. Default behavior is print-and-prompt, never execute.
