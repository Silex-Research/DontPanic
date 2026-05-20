---
id: 2026-05-19-005-feat-dogfood-showcase-artifacts-v0
title: Dogfood showcase artifacts v0 — visual architecture maps + plan validation + drift on our own repos
type: feat
tier: local
status: draft
date: "2026-05-19"
goal_type: new_feature
surfaces:
  - docs
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
  - 2026-05-19-004-feat-architecture-map-with-drift-v0
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
  parent_objective: "Dogfood as product demo: run Plan 4 architecture + Plan 3 strict-plan-validate FROM DontPanic against our own repos (DontPanic + agent-conventions + axiom + SpinDine|Glam) and publish artifacts under docs/showcase/. No subtree of runtime code into targets in v0; local integration deferred until a concrete trigger fires (committed architecture.json / target-repo CI drift / non-DontPanic contributors)."
  parent_acceptance_item: "Dogfood pivot: DontPanic generates a matrix of architecture HTML+JSON + strict-plan-validation summary + drift status summary (where applicable per repo) for 4 real repos (DontPanic + agent-conventions + axiom + one of SpinDine|Glam), commits the artifacts under docs/showcase/ with an index page + README pointer, sanitizes the output (no leaked absolute paths, no secrets, no external-repo audit/evidence content), documents the exact regen commands, and explicitly does NOT subtree DontPanic runtime code into any target repo."
  allowed_paths:
    - "scripts/dontpanic_orchestrate/**"
    - "scripts/dontpanic_orchestrate/showcase/**"
    - "scripts/dontpanic_orchestrate/tests/**"
    - "scripts/dontpanic_doctor.py"
    - "scripts/sanitization_check.py"
    - "scripts/showcase.sh"
    - "Makefile"
    - "docs/showcase/**"
    - "docs/plans/2026-05-19-005-feat-dogfood-showcase-artifacts-v0/**"
    - "README.md"
    - ".gitignore"
  forbidden_decisions:
    - "Do NOT subtree, vendor, or copy DontPanic runtime code (scripts/dontpanic_orchestrate/architecture*.py, doctor, supervisor, etc.) into target repos (agent-conventions, axiom, SpinDine, Glam, Jarvis). Showcase generator runs FROM DontPanic against external checkouts via existing `--repo-root` (architecture) + NEW `--plans-root` (validate-plans-strict) + NEW `--architecture-json` (drift) flag wire-through. Distributed integration is explicitly out of v0 scope."
    - "Do NOT commit local repo integration (committed architecture.json in target repos, target-repo CI drift checks, target-repo pre-commit hooks) until ONE of three concrete triggers fires: (a) a target repo's operator explicitly wants committed architecture.json for offline / contributor consumption; (b) a target repo wants drift checks wired into its own CI; (c) a target repo has active non-DontPanic contributors who need the map in-repo (not just generated from DontPanic). Until then, dogfood is showcase-only."
    - "Do NOT commit generated artifacts that contain leaked absolute paths (e.g. `/Users/<user>/Documents/GitHub/...`). Redactor scrubs paths to repo-relative form OR repo-name form OR redacts entirely BEFORE write. Sanitization_check scans docs/showcase/ on every sweep; CI blocks any leak."
    - "Do NOT commit generated artifacts that contain secrets (API keys, internal GCP project IDs not on a public allowlist, service-account emails, OAuth client IDs, refresh tokens, Discord webhook URLs, etc.). The existing sanitization_check.py allowlist gains docs/showcase/ as an allowed prefix; the existing secret-shape scan applies. Add showcase-specific patterns if new shapes appear in target-repo outputs."
    - "Do NOT include plan IDs, decision-log entries, audit JSONs, evidence files, or events.jsonl from TARGET repos in the showcase output. Architecture map shows modules + schemas + plan inventory at title+id+status level only — NOT the contents of audit/ or evidence/. Strict-plan-validation summary reports per-plan validation status (clean/warn/fail) + the validation error message — NOT the plan body. The Crawler already scopes correctly; redactor + sanitization are defense-in-depth."
    - "Do NOT auto-regenerate the showcase artifacts in supervisor, pre-commit hooks, or CI. Showcase regen is an explicit operator command (`dontpanic showcase regen` or `make showcase` / `scripts/showcase.sh`). Auto-regen would silently re-publish external-repo changes to DontPanic's surface — operator must opt in per regen."
    - "Do NOT include install report (Plan 2 F004), state projection sample (Plan 003), or work-request/intake (Plan 4.5) artifacts in v0 — those depend on plans that haven't shipped. Showcase index lists them as 'coming soon' with their owning plan IDs as forward references."
    - "Do NOT regress vs the lock-time test sweep baseline; do NOT hardcode a specific test count. Use 'no regressions vs lock-time baseline' phrasing."
    - "Do NOT block on missing target-repo checkouts. Showcase generator MUST degrade gracefully: when a target's repo_root doesn't exist locally, emit 'target not found at <path>; skipping' and continue with the targets that ARE present. Test fixture exercises the missing-target path."
    - "Do NOT generate strict-plan-validation summary for repos that don't have docs/plans/<plan-id>/ directories matching the v1.9 schema layout. Showcase config declares per-target which artifact types are supported (architecture always; validate-plans-strict only if `has_dontpanic_plans=True`; drift only if `has_committed_architecture_json=True`). Today: DontPanic supports all 3; SpinDine + Jarvis + agent-conventions support architecture + validate-plans-strict (if they have plan dirs); axiom + Glam are architecture-only."
    - "Do NOT include the showcase regen in any wall-clock-bounded sweep. The full showcase regen across 4 repos may take minutes (each architecture.regen crawls the target tree). Sweep budget remains the unit test sweep (≤43s); showcase regen is operator-explicit and untimed."
  return_condition_summary: "F001 ships `dontpanic showcase regen` CLI subcommand + showcase config + redactor + per-repo artifact matrix generator. Wires `--plans-root` flag through doctor's validate-plans-strict probe and `--architecture-json` flag through doctor's architecture-drift probe so external-repo invocation works without runtime-code copy. Sanitization_check extended to scan docs/showcase/. F002 ships docs/showcase/README.md index + repo README.md 'See DontPanic on real repos' section + scripts/showcase.sh wrapper + exact regen commands. v0 acceptance commits artifacts for 4 target repos (DontPanic + agent-conventions + axiom + one of {SpinDine, Glam}) with the artifact matrix appropriate to each (architecture HTML+JSON for all; validate-plans-strict summary for repos with plans; drift status for DontPanic only in v0). No DontPanic runtime code copied into any target repo. No leaked absolute paths or secrets in committed artifacts. Sanitization clean. No test regressions vs lock-time baseline."
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
description: |
  Plan 4 just shipped the architecture surface (CLI + crawler + JSON +
  HTML renderer + drift probe + supervisor regen hook + pre-commit
  hook). Plan 3 just shipped the strict-plan-validate probe. The
  natural follow-up isn't to subtree the code into every downstream
  repo — it's to **demonstrate** the platform by running both
  capabilities FROM DontPanic against our own repos and publishing the
  artifacts under `docs/showcase/`.

  Operator pivot (post-Plan 4 / post-Plan 3): use DontPanic's own
  repos as proof. v0 generates a matrix of artifacts across 4 target
  repos:

  | Target | Architecture HTML+JSON | Strict-plan-validation | Drift status |
  |---|---|---|---|
  | DontPanic | ✓ | ✓ | ✓ |
  | agent-conventions | ✓ | ✓ if plan dirs exist | — |
  | axiom | ✓ | — | — |
  | SpinDine OR Glam (operator picks one) | ✓ | ✓ if has plan dirs | — |

  Drift status only meaningful where architecture.json is committed —
  v0 = DontPanic only. Other repos gain drift coverage when (and if)
  they commit their own architecture.json — that's a follow-on plan
  per deferral triggers below.

  Two features:

  - **F001** — `dontpanic showcase regen` CLI subcommand at
    `scripts/dontpanic_orchestrate/showcase/__init__.py`. Reads a
    declarative showcase config (per-target {repo_key, label,
    repo_root, description, supported_artifacts}). For each target
    with an existing repo_root, invokes architecture.regen against
    --repo-root + (where supported) validate-plans-strict against
    --plans-root + (where supported) architecture-drift against
    --architecture-json. Redactor strips absolute paths; sanitization
    extension scans docs/showcase/. Missing-target degrades
    gracefully. Includes wire-through of `--plans-root` flag on
    doctor's validate-plans-strict probe + `--architecture-json` flag
    on architecture-drift probe (small CLI surface, ~30 lines each).
  - **F002** — `docs/showcase/README.md` index page listing each
    artifact with description + links + regen commands. Repo
    README.md gets 'See DontPanic on real repos' section. Wrapper
    `scripts/showcase.sh` (and Makefile `make showcase` target) for
    one-line operator invocation.

  Operator-codified deferral triggers for local integration (FUTURE):
  Local repo integration (committed architecture.json + CI drift
  checks + per-repo pre-commit hooks) is deferred until ONE of:
  (a) target repo wants committed architecture.json for offline
      / contributor consumption;
  (b) target repo wants drift checks wired into its OWN CI;
  (c) target repo has active non-DontPanic contributors who need the
      map in-repo (not just generated from DontPanic).
  Until one of those fires, the showcase artifact IS the product
  surface.
motivation: |
  Plan 4 shipped a capability that demos itself. Plan 3 shipped a
  schema-strict probe that benefits from being demonstrated on real
  plan inventories. The fastest way to prove the platform is to run
  both on real code we own and publish the output. New users see the
  artifact before they read any docs.

  Why this is right NOW (not a future plan):
  - The architecture surface is complete + stable as of commit
    5e27286 (Plan 4 F001-F005 all `passes:true`)
  - The strict-plan-validate probe ships at commit c104c22 (Plan 3
    F003) and already accepts a different plans_root via the
    underlying function — only a small CLI flag wire-through needed
  - `architecture regen --repo-root <path>` already works against
    arbitrary checkouts (Plan 4 F001 supported this day 1)
  - No new runtime infrastructure required — the showcase generator
    is a thin orchestration layer + two small CLI flag wire-throughs

  Why agent-conventions is especially valuable:
  - It's a schema repo that feels abstract today
  - A generated module + schemas + validators + downstream-consumers
    view makes it legible in one page
  - It probably doesn't have full DontPanic-style plan dirs (TBD at
    F001 implementation time — config detects `has_dontpanic_plans`)

  Why operator pivot (not subtree-everywhere):
  - Distributed runtime integration is high-cost, high-blast-radius
  - The showcase generates artifacts FROM DontPanic; downstream repos
    stay untouched
  - We codify deferral triggers explicitly so the team has a clear
    signal for when local integration becomes load-bearing (not just
    a vague "if useful")

  Operator constraints baked in:
  - No subtree/vendor of DontPanic runtime into target repos in v0
  - No auto-regen — explicit operator command only
  - Sanitization is mandatory (absolute paths + secrets + no target-
    repo audit/evidence content)
  - Artifacts live under docs/showcase/ (clearly marked example area)
  - Document exact regen commands
  - Local integration deferral triggers codified in this plan's
    forbidden_decisions

  Plan 5 (agent-conventions GitHub remote) is NOT a dependency here —
  showcase generates artifacts FROM DontPanic against
  agent-conventions' LOCAL checkout. Plan 5 lands separately.
---

# Dogfood Showcase Artifacts v0

## Thesis

Plan 4 shipped the architecture surface; Plan 3 shipped the strict-
plan-validate probe. Run BOTH FROM DontPanic against our own repos
and publish the artifact matrix under `docs/showcase/`. v0 targets 4
repos (DontPanic + agent-conventions + axiom + one of
{SpinDine, Glam}) with per-target artifact selection (architecture
always; validate-plans-strict where plan dirs exist; drift where
architecture.json is committed). Local integration deferred until a
concrete trigger fires.

## Scope

In scope:

- **F001** — `dontpanic showcase regen` CLI subcommand at
  `scripts/dontpanic_orchestrate/showcase/__init__.py`. Declarative
  showcase config: list of per-target {repo_key (str), label (str),
  repo_root (path), description (str), supported_artifacts
  (frozenset[str] ⊆ {architecture, validate_plans_strict, drift})}.
  For each target with an existing repo_root:
    (1) `architecture` artifact: invoke `architecture.regen(repo_root,
        with_html=True)` and write to `docs/showcase/<repo_key>-
        architecture.{html,json}`;
    (2) `validate_plans_strict` artifact (when supported): invoke
        doctor's validate-plans-strict probe with NEW `--plans-root
        <repo_root>/docs/plans` flag wire-through; capture JSON
        summary to `docs/showcase/<repo_key>-validate-plans.json`;
    (3) `drift` artifact (when supported): invoke doctor's
        architecture-drift probe with NEW `--architecture-json
        <repo_root>/docs/architecture/architecture.json` flag wire-
        through; capture JSON summary to `docs/showcase/<repo_key>-
        drift.json`.
  Run redactor pass over every generated artifact (JSON + HTML) to
  scrub absolute paths to repo-relative form. Atomic writes. Update
  `scripts/sanitization_check.py` ALLOWED_PREFIXES to include
  `docs/showcase/`. Missing target_repo_root → emit `target not found
  at <path>; skipping` and continue.
- **F002** — Documentation + wrapper:
  - `docs/showcase/README.md` index page (joyful but text-only — HTML
    artifacts carry the visual joy). Per artifact: label +
    description + link to artifact + exact regen command.
    "Coming soon" section lists install report (Plan 2 F004),
    state projection sample (Plan 003), work-request/intake
    (Plan 4.5) as forward references.
  - `README.md` gains "See DontPanic on real repos" section linking
    `docs/showcase/README.md`.
  - `scripts/showcase.sh` (and Makefile `make showcase` target) — one-
    line wrapper invoking `python -m dontpanic_orchestrate showcase
    regen`.
  - Showcase deferral policy section (in docs/showcase/README.md):
    document the three concrete triggers for promoting a repo from
    showcase-only to local integration.

Out of scope:

- Subtreeing or copying DontPanic runtime code into target repos in
  v0 (deferred per the three concrete triggers codified in this plan)
- Auto-regen in supervisor, pre-commit hooks, or CI
- Install report sample (depends on Plan 2 F004)
- State projection sample (depends on Plan 003 close-out + export)
- Work-request / intake demo (depends on Plan 4.5)
- Targeting every owned repo — v0 acceptance requires exactly the 4
  named targets (one of SpinDine|Glam is operator's pick at
  generation time)
- Wiring agent-conventions remote (Plan 5 — separate; showcase uses
  local checkout)
- Embedding showcase index page in any live external site
- Per-target validate-plans-strict for repos that don't follow
  DontPanic-style plan dirs (the config flags this via
  `has_dontpanic_plans=False`)

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance Summary

- **F001**: `dontpanic showcase regen` runs end-to-end. Reads showcase
  config; for each target with existing repo_root + supported_artifact,
  generates the appropriate artifact under
  `docs/showcase/<repo_key>-<artifact>.{html,json}`; redactor strips
  absolute paths; sanitization_check passes. Missing target degrades
  with `target not found; skipping` and continues. v0 acceptance
  commits at least: dontpanic-architecture.{html,json},
  dontpanic-validate-plans.json, dontpanic-drift.json,
  agent-conventions-architecture.{html,json},
  axiom-architecture.{html,json}, and either spindine-* or glam-*
  (operator picks). NEW CLI flag wire-throughs: `--plans-root` on
  validate-plans-strict probe + `--architecture-json` on
  architecture-drift probe.
- **F002**: `docs/showcase/README.md` index lists every committed
  artifact with label + description + link + regen command. Repo
  README.md has "See DontPanic on real repos" section pointing at
  the showcase. `make showcase` (or `scripts/showcase.sh`) one-line
  regen wrapper present. Deferral-trigger documentation present in
  docs/showcase/README.md so the team has a clear signal for when
  local integration becomes load-bearing.

## Cross-feature invariants

1. **No runtime code copied into target repos.** Showcase generator
   runs FROM DontPanic against external checkouts via `--repo-root` +
   `--plans-root` + `--architecture-json` flags. No subtree, no
   vendor, no committed runtime code in any target repo.
2. **Deferral triggers codified.** Local integration is deferred
   until ONE of three concrete triggers fires (committed
   architecture.json in target / target-repo CI drift checks /
   non-DontPanic contributors needing in-repo map). Documented in
   plan forbidden_decisions + docs/showcase/README.md.
3. **Sanitization is mandatory.** Redactor strips absolute paths;
   sanitization_check.py extended to scan docs/showcase/; secret-
   shape scan applies. Target-repo audit/evidence content NEVER
   reaches the showcase output.
4. **Operator-explicit regen only.** No auto-regen in supervisor,
   pre-commit hooks, or CI. v0 ships `dontpanic showcase regen` +
   `make showcase` wrapper.
5. **Graceful missing-target handling.** Target checkout absent →
   skip with clear message, continue with remaining targets.
6. **Per-target supported_artifacts.** Config flags which artifact
   types each target supports; generator skips unsupported artifacts
   silently (no false-positive errors when validate-plans-strict
   isn't applicable to e.g. axiom).
7. **No regressions vs lock-time baseline.** Full sweep at or above
   lock-time test count.
8. **Artifacts under `docs/showcase/` only.** Clearly marked example
   area; not mixed with `docs/architecture/` (DontPanic's own
   canonical map) or `docs/plans/`.
