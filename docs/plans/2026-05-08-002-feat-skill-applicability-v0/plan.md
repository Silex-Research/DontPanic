---
id: 2026-05-08-002-feat-skill-applicability-v0
title: Skill-applicability evidence sidecar — v0 (advisory, lock-time only)
type: feat
tier: local
status: active
date: "2026-05-08"
description: |
  Decentralized v0 of the skill-applicability layer. Two surgical features:
  (F001) add `surfaces: [...]` field to the plan schema and document
  `applies_to:` SKILL.md frontmatter; (F002) lock-time matcher emits
  `<plan_dir>/evidence/applicable-skills.json` listing matched skills with
  rationale. Advisory only — NO gate, NO blocking, NO scope-change re-probe.
  Closes the gap where UX/design/product-journey applicability is not
  systematically surfaced unless a plan has a goal-gated objective contract.
motivation: |
  Memory entry `project_skill_applicability_v0.md` captured the locked v0
  design after a multi-round volley: skills self-declare applicability via
  machine-readable frontmatter; a thin matcher reads plan metadata + skill
  manifests and emits an evidence sidecar. The user's framing: "UX/design/
  product-journey applicability is not systematically surfaced today unless
  a plan has a goal-gated objective contract. That's a platform gap, and
  v0 is deliberately low-risk." The gap is real but bounded — v0 ships
  advisory output, no enforcement. Operators who want signal use the
  sidecar; operators who don't can ignore it. Promotion to a gate is
  explicitly future work, contingent on false-positive data from real
  plans.

  Prereqs are met: patch-completeness gate (2026-05-01-004) and security
  baseline (2026-05-01-003 + follow-up 2026-05-08-001) all closed. Per
  memory's "no meta-systems mid-volley" rule, those had to land first.
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
goal_type: new_feature
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/maintainer/refresh-costs.sh
dependencies:
  - 2026-05-01-003-feat-security-baseline
  - 2026-05-01-004-feat-patch-completeness-gate
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Skill-applicability evidence sidecar — v0

## Thesis

Plans declare what surfaces they touch. Skills declare what surfaces they
apply to. A thin matcher reads both and emits an advisory sidecar saying
"these N skills *might* apply to this plan, here's why." That's all v0
does. No gate, no blocking, no escalation, no mid-volley re-probe. The
operator reads the sidecar and decides whether to invoke the matched
skills or ignore them.

This is intentionally narrower than the historical "skill applicability
layer" framing. Centralized routers go stale every time a skill is added
or changed. Self-declared applicability via skill frontmatter, read by a
dumb matcher, scales as skills evolve. The Claude Code harness already
follows this shape with SKILL.md trigger descriptions; v0 just makes the
match machine-readable.

## Scope

In scope (2 features):

- **F001 — Schema + metadata**.
  - Add `surfaces: list[str]` (optional) to `plan.schema.json` with
    enum: `["web", "ios", "android", "backend", "infra", "security",
    "data", "ux", "ml", "docs"]`. Bump agent-conventions to v1.5.0,
    subtree-pull into DontPanic, regenerate Pydantic model, wire loader.
    Field is OPTIONAL — backward-compatible with all existing plans.
  - Document `applies_to:` SKILL.md frontmatter shape: a dict with two
    keys, `surfaces: [...]` (subset of the same enum) and `goal_types:
    [...]` (subset of the existing plan `goal_type` enum). SKILL.md has
    no strict schema today; the matcher in F002 validates this block via
    Pydantic. The block may also include optional inert
    `external_cli:` metadata for skills backed by an external adapter:
    `provider`, `name`, `command`, and `version_pin`. v0 records this
    metadata in the advisory report; it never installs, invokes, or
    allowlists the CLI. Frontmatter parsers ignore unknown fields, so
    adding `applies_to:` is non-breaking for existing skills.
  - Backfill `surfaces:` on 3 representative existing plans (one per
    surface category) to demonstrate the field works end-to-end through
    the loader.
  - Backfill `applies_to:` on 5 representative existing skills covering
    distinct surfaces, including at least one `ux` match so the
    motivating UX/design/product-journey gap is exercised by v0 rather
    than only documented. Suggested set: `pr-reviewer` → backend/infra,
    `eval-harness` → ml/ux, `changelog` → docs, `cost-model` → infra,
    `browser-use` or `agent-browser` → web/ux. NOT all 30 skills —
    backfill is demonstrative, not exhaustive.

- **F002 — Lock-time advisory sidecar**.
  - New module `scripts/dontpanic_orchestrate/skill_applicability.py`
    with `match(plan: LoadedPlan, skills_dir: Path) -> ApplicabilityReport`
    pure function. Reads each `SKILL.md` frontmatter, parses `applies_to`
    via Pydantic (skips skills without the field with a one-line "skill
    has no applies_to" rationale), matches against `plan.surfaces` and
    `plan.goal_type` via simple set intersection. Returns a
    `ApplicabilityReport(schema_version, plan_id, plan_surfaces,
    plan_goal_type, matches: list[Match], skipped: list[Skip])` envelope.
    Each `Match` carries `(skill_name, matched_surfaces, matched_goal_types,
    rationale, provenance, external_cli)`. `provenance` is `"internal"`
    when no external CLI metadata exists and `"external"` when the skill
    declares `applies_to.external_cli`. `external_cli` is copied as
    advisory metadata only. Each `Skip` carries `(skill_name, reason)`.
  - Wire the matcher into `dontpanic plan lock` (or the supervisor's
    pre-dispatch hook for plans without a lock command — TBD by F002
    investigation): on lock, emit `<plan_dir>/evidence/applicable-
    skills.json`. Advisory only — sidecar lands and operator-facing
    output is one line `[applicable-skills] N matches, M skips written
    to evidence/applicable-skills.json`. NO blocking, NO error path.
  - JSON round-trip test pins the report shape for future schema-
    promotion work (D004-style).
  - Tests: matcher purity (no I/O beyond reading SKILL.md files), match
    correctness across the surface enum, skip path for skills without
    `applies_to:`, empty-surfaces plan returns empty matches, JSON
    round-trip. NO supervisor-integration test in v0 — the matcher is
    testable in isolation; the wiring is exercised manually before flip.

Out of scope (deferred):

- **Scope-change re-probe**. Mid-volley re-evaluation when an audit
  finding expands surface scope is explicitly NOT in v0. Memory entry
  flagged this as separate work that gets its own plan only after v0
  produces real false-positive data.
- **Hard gating / blocking**. v0 emits advisory evidence. Promotion to
  a gate (refuse signoff if a required skill wasn't invoked) is future
  work contingent on operator-supplied data on false-positive rate.
- **Backfill across all 30 skills**. F001 backfills 5; the remaining 25
  opt in over time as their owners declare `applies_to`. The matcher
  silently skips skills without the field — no penalty for not opting
  in yet.
- **Cross-plan analysis**. Matcher operates on one plan at a time. Roll-
  up reporting (which surfaces have the thinnest skill coverage, which
  skills are over-broad) is a future tooling layer.
- **Plan classifier**. v0 requires the plan author to declare `surfaces:`
  manually. Auto-detecting surfaces from plan content (e.g., LLM-based
  classifier) is future work; for v0, manual declaration keeps the
  signal honest.
- **External CLI / Printing Press adapter execution**. v0 carries an
  inert metadata hook for externally-backed skills, but the matcher does
  not install, invoke, verify, allowlist, or score Printing Press-generated
  CLIs. External CLI provenance normalization, binary hash pinning, cache
  disposition, read-only policy, and adapter lifecycle belong in a
  separate adapter-governance plan.

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance summary

- **F001:** `plan.schema.json` (in agent-conventions, bumped to v1.5.0)
  carries `surfaces: list[str]` with the 10-value enum; subtree pulled
  into DontPanic; Pydantic model regenerated; plan_loader accepts the
  field; 3 plans backfilled with `surfaces:`; 5 skills backfilled with
  `applies_to:`. A new test asserts the schema bump version + the field
  is recognized end-to-end. Existing plans (without `surfaces:`) still
  validate.
- **F002:** `skill_applicability.py` matcher exists and is pure (no
  subprocess, no logging, only file I/O is reading SKILL.md frontmatter).
  `match(plan, skills_dir) -> ApplicabilityReport` returns matches +
  skips with rationale and provenance. External CLI metadata, when present,
  is copied into matches but never executed. `evidence/applicable-skills.json`
  sidecar lands at lock time on a real plan invocation. Tests cover purity,
  match correctness, skip path, empty-surfaces, external-provenance
  pass-through, JSON round-trip. NO gate behavior — sidecar is advisory only.
- All existing orchestrate test modules stay green throughout.
- D-entry on closure references the locked v0 design from
  `project_skill_applicability_v0.md` memory + records what got cut
  (scope-change re-probe, hard gating) for the v1 plan trigger.
