---
id: 2026-05-19-002-feat-install-ux-hardening-v0
title: Install UX hardening v0 — doctor profiles + init + smoke test + HTML report
type: feat
tier: cross-cutting
status: active
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
  parent_objective: "Fix first-user pain. Doctor is the first-touch authority; today it's silent on the items a new user actually needs. Widen it into a declarative probe registry with profile filtering + activation conditions + JSON output, add `dontpanic init` (strict argv-allowlist auto-fixes), add a synthetic mocked-supervisor smoke test, and emit an HTML install report. F001 ships independently."
  parent_acceptance_item: "Roadmap 2026-05-19 Plan 2: `dontpanic doctor --profile=core` surfaces blockers with conditional severity (Python <3.10 hard fail; gh auth warn when github remote exists; codex CLI advisory unless auditor_codex_selected); `dontpanic doctor` (no flags) keeps legacy behavior; new user runs profile-aware doctor in <=10s; `dontpanic init --profile=core` walks fix checklist via strict argv allowlist; `dontpanic smoke --mode=mocked` exercises NAMED supervisor surfaces (plan load, gate eval, mocked executor envelope write, audit persist, signoff, INBOX, cleanup) without real CLI or paid API; HTML install report renders cleanly."
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
    - "Do not break `dontpanic doctor` (no flags) backwards compatibility. Legacy path keeps existing CheckResult pipeline, existing probe set, existing 0/1/2 exit-code matrix. The new profile-aware behavior is gated entirely on the `--profile=<name>` flag being supplied. `dontpanic init` defaults to --profile=core (NOT doctor)."
    - "Do not introduce conditional-pseudo-profiles like `core-when-auditor-codex` or `openclaw-when-pushing`. Profiles are pure sets (frozenset[str] of probe names). Conditional severity lives on per-probe `activation_condition` field (enum: always | github_remote_present | auditor_codex_selected | dispatch_requires_push | firebase_target_set). Probe required_for_profiles + activation_condition together determine red/warn/advisory for that profile."
    - "Do not make codex CLI a blanket core blocker. Default: codex probe is advisory (warn) under --profile=core unless activation_condition.auditor_codex_selected resolves true (i.e. the operator's environments.json or invocation explicitly selects codex as auditor). Core is for any DontPanic user, not for the maintainer cross-vendor setup."
    - "Do not make gh auth a blanket core blocker. Default: gh auth probe is warn-only under --profile=core when a github remote is configured for the clone (activation_condition.github_remote_present); absent entirely from output when no github remote exists. PAT is required only for --profile=ci or workflows declaring scoped pushes."
    - "Do not auto-create GitHub PATs. Operator decision — too sensitive. PAT-creation is copy-paste only, never executed by init."
    - "Do not auto-generate Firebase SA keys for jarvis-a6ee1. Existing bootstrap.sh handles that flow under explicit --create-key. Init may surface the gap with a fix_command pointer; it must not execute."
    - "Do not require Firebase auth or gcloud for --profile=core. Firebase gates are firebase-dashboard profile only."
    - "Do not install dependencies outside safe scopes. No sudo, no system Python modifications, no pipx --force, no global brew package installs without per-probe auto_install_safe=true AND per-probe operator confirmation. No --auto-fix-safe-all batch flag in v0 default."
    - "Do not add a `maintainer` profile in v0. Maintainer profile lands in a future plan (Roadmap Plan 5/7); v0 ships core + discord + firebase-dashboard + openclaw + ci."
    - "Do not regress vs the lock-time test sweep baseline. Use 'no regressions vs lock-time baseline' phrasing — do not hardcode a specific count (e.g. 2036) that could rot if other plans land between draft and dispatch."
    - "Do not target Windows in v0. macOS + Linux only. Document the gap; don't probe for it."
    - "Do not depend on Plan 4's docs/architecture/architecture.json. Smoke fixtures are self-contained synthetic plans, not consumers of the architecture map. Install UX is independent of the architecture surface."
    - "Do not claim `dontpanic smoke` exercises every supervisor branch. Acceptance names exact surface set: plan load, gate evaluation, mocked executor envelope write, audit JSON persist, signoff envelope write, INBOX append, tmpdir cleanup. Real-CLI presence is validated by doctor profile probes, NOT by smoke (--mode=mocked is the v0 mode; --mode=live deferred)."
    - "Do not use shell strings in F002 auto-fix execution. Strict argv allowlist: subprocess.run(argv: list[str], shell=False). Each auto-fix-safe probe declares its command as list[str] in the registry; the runner never accepts free-form shell strings from probe output. Package-manager installs (brew, pip) ship OFF by default in v0 — opt-in per probe via auto_install_safe=true AND require per-probe operator confirmation in the interactive flow."
    - "Do not clash with Plan 3 F003's existing `--strict-codes`/`--validate-plans-strict` flags. The doctor's profile-aware blocker mode uses `--profile-strict` namespace (mirrors the `--validate-plans-strict` / `--architecture-drift-strict` precedent shipped at commits c104c22 + 6032046)."
    - "Do not formally bump agent-conventions schema for the `dontpanic doctor --json` envelope in v0. The envelope carries an inline `schema_version` string + local schema doc in this plan's evidence/; formal agent-conventions promotion is explicitly deferred to a future plan."
  return_condition_summary: "F001 ships independently: `dontpanic doctor --profile=<name>` works for {core, discord, firebase-dashboard, openclaw, ci}; pure-set profiles + per-probe activation_condition; no conditional pseudo-profiles; codex+gh auth follow conditional severity (not blanket core blockers); `dontpanic doctor` no-flag legacy path unchanged. F002 ships `dontpanic init --profile=core` (default) with strict argv-allowlist auto-fixes, per-probe operator confirmation, --non-interactive JSON mode. F003 ships `dontpanic smoke --mode=mocked` exercising NAMED supervisor surfaces without real CLI or paid API. F004 ships HTML install report. JSON envelope carries explicit schema_version. No regressions vs lock-time baseline; sanitization clean."
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
description: |
  First real user hit three install blockers in sequence:
  1. GitHub PAT missing (silently, until first `git push`)
  2. Python version wrong (3.10+ required for `|` union types)
  3. Codex CLI not installed (silent until first `--auditor codex` dispatch)

  Each blocker was *discoverable* only after a failure. The doctor exists
  but doesn't probe these. v0 widens it correctly:

  - Python <3.10 is the only hard blocker for everyone (core).
  - Missing claude CLI is a hard blocker for everyone (default executor).
  - GitHub auth is conditional: warn-only under core when a github
    remote exists; absent when no remote; required only for ci /
    push-required workflows.
  - Codex CLI is conditional: advisory under core unless
    activation_condition.auditor_codex_selected resolves true.

  Profile model is pure-sets-of-probe-names. Per-probe
  `activation_condition` field carries the conditional severity logic.
  This avoids the pseudo-profile trap (`core-when-auditor-codex` etc).

  Four features, F001 independently shippable + ship-first per roadmap:

  - **F001** — Declarative `PrereqProbe` dataclass + 5 pure-set profiles
    (core / discord / firebase-dashboard / openclaw / ci) + per-probe
    activation_condition + ~10 initial probes + `--profile=` and `--json`
    CLI flags + stable JSON envelope with schema_version. Network probes
    parallel + capped at 2s each. **`dontpanic doctor` (no flags) keeps
    legacy behavior unchanged**; profile-aware path activates only on
    `--profile=<name>`. Land + assess delta before F002-F004.
  - **F002** — `dontpanic init` (defaults to --profile=core) interactive
    installer + --non-interactive mode. Strict argv-allowlist auto-fixes
    with per-probe operator confirmation. Package-manager installs OFF
    by default. Idempotent re-runs.
  - **F003** — `dontpanic smoke --mode=mocked`: synthetic plan + mocked
    executors exercising NAMED supervisor surfaces (plan load, gate
    eval, executor envelope write, audit persist, signoff, INBOX,
    cleanup) without real CLI or paid API. Real-CLI validation lives in
    doctor profile probes, NOT in smoke.
  - **F004** — HTML install report (Thariq pattern). Single-page,
    self-contained, no JS framework, mobile-responsive, gitignored.

  All four features stay within `scripts/dontpanic_orchestrate/` (new
  init/ + smoke/ subpackages) + `scripts/dontpanic_doctor.py`.
motivation: |
  Doctor is the first-touch authority for a new user. Right now it's
  silent on the pieces a new user actually needs. The user has to fail
  at git push, then fail at a paid volley, then read the codex setup
  docs in the wrong order to figure out what's missing.

  Plan 3 (schema mismatch fix) shipped first so this widening doesn't
  land on top of a known false-fail in strict mode. Plan 4 (architecture
  map with drift) shipped in parallel but Plan 2 is independent of it
  (Roadmap initially listed the dep; operator review removed it —
  install UX should not depend on the architecture map).

  Plan 2's wins compound: F001 alone materially improves first-user
  pain (operator pause point before F002-F004); F002 turns "run a
  doctor + read the output" into a guided walkthrough; F003 catches
  real supervisor-plumbing regressions in CI without paid calls; F004
  makes the report linkable + shareable for support / community help.

  Operator review (post-draft, pre-lock) sharpened the design:
  - Profiles are pure sets; conditional severity is a per-probe field
  - Codex + gh auth follow conditional severity, not blanket core
  - `dontpanic doctor` (no flags) keeps legacy behavior — only --profile
    activates the new path
  - Smoke validates supervisor plumbing only; real-CLI validation lives
    in doctor probes
  - Auto-fix execution uses strict argv allowlist; package installs OFF
    by default
  - No dep on architecture.json

  Out of scope (per roadmap + operator review):
  - Auto-creating GitHub PATs (too sensitive)
  - Auto-generating Firebase SA keys (bootstrap.sh handles this)
  - Windows support (macOS + Linux only v0)
  - Reusable profile authoring UX — v1 candidate
  - `maintainer` profile — Roadmap Plan 5/7
  - Formal agent-conventions schema bump for doctor --json envelope
    (inline schema_version + local doc; formal bump deferred)
---

# Install UX Hardening v0

## Thesis

Doctor is the first-touch authority. Today it's silent on the items a
new user actually needs. Widen it into a declarative probe registry
with profile filtering (pure sets) + per-probe activation_condition
(for conditional severity) + JSON output with schema_version. Keep
`dontpanic doctor` no-flag legacy behavior unchanged; new path
activates on `--profile=<name>`. Then layer `dontpanic init` (F002,
strict argv allowlist), a synthetic mocked-supervisor smoke test
(F003), and an HTML install report (F004).

F001 ships independently and materially improves first-user pain on
its own. F002-F004 are sequenced after the operator assesses F001
delta.

## Scope

In scope:

- **F001** — Declarative `PrereqProbe` dataclass at
  `scripts/dontpanic_orchestrate/prereq_registry.py` + 5 pure-set
  profiles + per-probe `activation_condition` + ~10 initial probes
  wired into `scripts/dontpanic_doctor.py`. New CLI flags:
  `--profile=<name>` (NO default — `dontpanic doctor` with no flags
  keeps legacy path); `--json` extended with a stable envelope
  carrying explicit `schema_version`. New `--profile-strict` flag
  (NOT `--strict` — avoids clash with Plan 3 F003's
  `--validate-plans-strict` / Plan 4 F003's `--architecture-drift-strict`).
  Network probes parallel + 2s cap each. Full sweep ≤10s wall clock.
- **F002** — `dontpanic init` at
  `scripts/dontpanic_orchestrate/init/__init__.py`. Defaults to
  `--profile=core`. Strict argv-allowlist auto-fixes via
  `subprocess.run(argv, shell=False)`. Per-probe operator confirmation
  required (no `--auto-fix-safe-all` batch flag in v0). Package-manager
  installs OFF by default; opt-in per probe.
- **F003** — `dontpanic smoke --mode=mocked` at
  `scripts/dontpanic_orchestrate/smoke/__init__.py`. Synthetic plan +
  mocked executors exercise NAMED supervisor surfaces without real
  CLI or paid API. Acceptance lists exact set: plan load, gate
  evaluation, mocked executor envelope write, audit JSON persist,
  signoff envelope write, INBOX append, tmpdir cleanup.
- **F004** — HTML install report at
  `scripts/dontpanic_orchestrate/init/report_html.py`. Pure transform
  from `dontpanic doctor --json` + `dontpanic smoke --json` payloads
  to a self-contained HTML5 document. Mirror Plan 4 F002's
  architecture_html.py style baseline. gitignored output.

Out of scope:

- Auto-creating GitHub PATs (operator decision — too sensitive)
- Auto-generating SA keys for jarvis-a6ee1 (existing bootstrap.sh
  handles this flow under explicit --create-key)
- Installing dependencies outside safe scopes (no sudo, no system
  Python modifications, no pipx --force, no global brew without
  per-probe auto_install_safe=true AND operator confirmation)
- Windows support (macOS + Linux only for v0)
- Reusable profile authoring UX (operator-defined custom profiles) — v1
- `maintainer` profile (Roadmap Plan 5/7)
- README rewrite for first-time visitor (Roadmap defers to after F001
  delta assessment)
- Plan 4 architecture.json consumption — install UX is independent of
  the architecture map
- Formal agent-conventions schema bump for doctor --json envelope —
  inline schema_version + local schema doc only; formal bump deferred
- `--auto-fix-safe-all` batch flag — per-probe operator confirmation
  is the v0 contract
- `dontpanic smoke --mode=live` (real CLI integration smoke) —
  --mode=mocked is the v0 scope

## Target

```yaml
target_env: dev
target_project: none
```

## Sequencing within Plan 2

F001 ships independently — operator can pause after F001 to assess
actual delta before committing tokens to F002-F004. F002-F004 are
sequenced after F001 closes.

## Acceptance Summary

- **F001**: `dontpanic doctor --profile=core --json` returns accurate
  per-probe severity (Python <3.10 fail; missing claude CLI fail; gh
  auth warn-only when github remote present, absent when none; codex
  CLI advisory unless activation_condition.auditor_codex_selected)
  in ≤10s wall clock. JSON envelope carries explicit `schema_version`.
  `dontpanic doctor` (no flags) keeps legacy CheckResult pipeline +
  0/1/2 exit-code matrix unchanged. `--profile=firebase-dashboard`
  adds Firebase + gcloud + SA key probes. **`--profile=core` never
  tells a user to install Firebase or clone agent-conventions.**
- **F002**: `dontpanic init` defaults to --profile=core. Strict
  argv-allowlist auto-fixes via subprocess.run(argv, shell=False).
  Per-probe operator confirmation. Package-manager installs OFF by
  default. `--non-interactive` flag exits with structured output.
  Re-runnable mid-install (idempotent).
- **F003**: `dontpanic smoke --mode=mocked` runs a synthetic plan
  through `supervisor.dispatch_volley` with mocked executors in <=30s
  wall clock. No real CLI required. No paid API. Acceptance names
  exact supervisor surfaces exercised: plan load, gate evaluation,
  mocked executor envelope write, audit JSON persist, signoff
  envelope write, INBOX append, tmpdir cleanup. Does NOT claim every
  branch.
- **F004**: `dontpanic init --report` and `dontpanic doctor --report`
  emit a single-page HTML at `docs/install-report.html` (gitignored).
  Renders cleanly in Chrome/Safari/Firefox on macOS + Linux. Mobile-
  responsive. Self-contained.

## Cross-feature invariants

1. **Backwards-compatible doctor.** `dontpanic doctor` with NO flags
   keeps its existing CheckResult pipeline, existing probe set, and
   existing 0/1/2 exit-code matrix. The new profile-aware behavior
   activates ONLY on `--profile=<name>`. `dontpanic init` defaults to
   --profile=core.
2. **Pure-set profiles + per-probe activation_condition.** Profiles
   are frozenset[str] of probe names. Conditional severity lives on
   per-probe `activation_condition` (enum: always |
   github_remote_present | auditor_codex_selected |
   dispatch_requires_push | firebase_target_set). Probe
   required_for_profiles + activation_condition together determine
   red/warn/advisory for that profile. NO conditional pseudo-profiles.
3. **No silent failures.** Every probe has a `fix_url` AND
   `fix_command` (or escalation message). Doctor exits with structured
   "what to do next" if anything is red.
4. **Network-bounded preflight.** Network probes (anthropic API
   reachability) run in parallel with a 2s cap each. Full sweep ≤10s
   wall clock.
5. **Dual-channel output.** Pretty terminal output for humans
   (red/warn/advisory chips, copy-paste commands), structured JSON
   for agents with explicit schema_version.
6. **Strict argv allowlist for auto-fix.** F002 auto-fix execution
   uses subprocess.run(argv: list[str], shell=False). Each
   auto-install-safe probe declares its command as list[str]. NEVER
   accepts shell strings. NEVER package-manager installs by default.
7. **Smoke validates supervisor plumbing only.** F003 --mode=mocked
   does NOT require real CLI. Real-CLI presence validated by doctor
   profile probes, not smoke. Named surfaces only — no "every branch"
   claims.
8. **No regressions vs lock-time baseline.** Full sweep at or above
   the test count at lock time. Do NOT hardcode a specific count.
9. **JSON envelope versioned.** `dontpanic doctor --json` envelope
   carries top-level `schema_version` string. Local schema doc in
   this plan's evidence/. Formal agent-conventions schema bump
   deferred to a future plan.
10. **No architecture.json dependency.** Install UX is independent of
    Plan 4's architecture map. Smoke fixtures are self-contained
    synthetic plans.
