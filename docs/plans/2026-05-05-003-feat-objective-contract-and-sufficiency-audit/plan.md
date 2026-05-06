---
id: 2026-05-05-003-feat-objective-contract-and-sufficiency-audit
title: Plan F1 — Objective contract schema + pre-impl sufficiency audit + Spin & Dine / Glam dogfood
type: feat
tier: cross-cutting
status: completed
date: "2026-05-05"
description: |
  **Plan F1 of the Goal Governance V1 sequence** (per
  `docs/GOAL_GOVERNANCE_V1.md` §9). Ships the first half of
  goal-completion governance: an objective-contract schema in
  agent-conventions, a pre-impl sufficiency auditor in DontPanic
  that walks the contract against features.json, a plan-lock gate
  that refuses lock when sufficiency findings are blocking, and a
  gating dogfood against Spin & Dine parity + Glam Creator Hub.

  Five features split along independent verification and
  dependency boundaries (D001):

  - **F001** — agent-conventions schema/model/validator (cross-repo
    boundary, releasable independently as v1.4.0).
  - **F002** — DontPanic subtree-pull v1.4.0 (mechanical import
    boundary; isolates upstream consumption from local behavior
    changes).
  - **F003** — pre-impl sufficiency auditor module (text-only, no
    MCP; testable after F002).
  - **F004** — plan-lock sufficiency gate/check (lifecycle behavior
    depending on F003 outputs; applies to every lock path, not just
    draft → active).
  - **F005** — gating dogfood against Spin & Dine + Glam
    (operator-judged proof point; can fail without invalidating
    F001–F004 logic).

  No MCP dependency (Plan G ships those for F2 post-impl runtime
  evidence). No OpenClaw dependency (locked per Goal Governance V1
  §6.7). No dashboard work (Plan H).

motivation: |
  Spin & Dine and Glam (per Goal Governance V1 §2 motivating
  examples) demonstrated that feature-level audit verifies local
  patches but not goal satisfaction. F1 closes the *pre-impl* half
  of that gap: catch decomposition errors at plan-lock time —
  before any volley fires — by walking the goal against the
  proposed features.

  The dogfood (F005) is the load-bearing proof. F005 fails unless
  the sufficiency auditor surfaces at least one materially correct
  gap class for **each** of Spin & Dine (parity matrix
  incompleteness) **and** Glam (integrated Creator Hub journey-
  coverage gap). Synthetic test fixtures alone do not satisfy F1.

agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 1
  no_progress_threshold: 1
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
protected_paths:
  # Same protected set as Plans A–F0, with one explicit carve-out:
  # F002 modifies claude/shared/ via `git subtree pull` ONLY — no
  # free-form edits in the DontPanic working tree (mirrors Plan E
  # D010).
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/dontpanic_orchestrate/target_context_prelude.py
  # F1 does NOT modify the goal-gap config landed in F0; that
  # surface is sealed at aadb99e.
  - scripts/dontpanic_orchestrate/nested_orchestration.py
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit
  evidence_dir: ./evidence
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Five features with explicit dependency boundaries:

```
F001 (agent-conventions: schema + model + validator + tag v1.4.0)
   ↓
F002 (DontPanic: subtree-pull v1.4.0 + regression sweep)
   ↓
F003 (DontPanic: sufficiency_auditor.py + tests)
   ↓
F004 (DontPanic: plan-lock gate wiring; every lock path)
   ↓
F005 (DontPanic: dogfood — Spin & Dine + Glam objective contracts;
        operator-judged disposition required)
```

Each feature is **independently verifiable** (D001 — see decisions
register). F005 is the gating proof; if it fails, the sufficiency
prompt / schema / decomposition rules must be revised before F1
can close (D010).

### F001 — agent-conventions schema/model/validator

Adds (in `claude/shared/...` upstream):

- `schemas/v1.0/objective_contract.schema.json` — new JSON schema
  defining the objective contract block (goal_type, source_of_truth,
  user_journeys, required_evidence, non_goals, completion_test,
  cluster_overrides).
- `schemas/v1.0/models/objective_contract_model.py` — Pydantic model
  (generated via datamodel-codegen).
- Modifications to `schemas/v1.0/plan.schema.json`:
  - `goal_type` (top-level optional) — enum
    `{mechanical, infra, refactor, parity, new_feature, migration, incident}`.
  - `links.objective_contract` (path reference, optional). Per D002,
    objective contracts are referenced via `links`, not embedded
    inline in plan.md. The existing `Links` model already carries
    other path refs (features, decisions, etc.) — this slots in
    cleanly.
- Regenerated `schemas/v1.0/models/plan_model.py` adding
  `Plan.goal_type: GoalType | None` + `Links.objective_contract: str | None`.
- `schemas/v1.0/validate.py` rule: when
  `Plan.goal_type ∈ {parity, new_feature, migration, incident}`,
  the plan must declare `links.objective_contract` AND the file at
  that path must validate against `ObjectiveContract`.
- Tests under `tests/objective_contract/` covering 7 fixture cases.
- VERSION 1.3.1 → 1.4.0 (D004 — minor; additive functionality).
- Tag v1.4.0 (local-only, matches Plan E pattern).

### F002 — DontPanic subtree-pull v1.4.0

- `git subtree pull --prefix=claude/shared/ <local agent-conventions> v1.4.0 --squash`.
- Verify byte-equality with upstream.
- Run validator against existing plans (Plans A–E + F0 + this Plan
  F1 itself) — all must validate green. Backward compat is the test:
  none of them declare `goal_type`, so the new validator rule
  doesn't engage; their existing fields remain valid.
- Two-commit boundary preserved (D009).

### F003 — pre-impl sufficiency auditor

New module `scripts/dontpanic_orchestrate/sufficiency_auditor.py`:

- Pure text-only auditor (no MCP, no runtime evidence).
- Function shape:
  ```python
  def run_sufficiency_audit(plan_dir: Path) -> list[SufficiencyFinding]
  ```
- Reads `plan.md` frontmatter (gets `goal_type` + `links.objective_contract`).
- Loads the objective contract file via `links.objective_contract`.
- Loads `features.json`.
- Constructs a sufficiency prompt: walk objective_contract.user_journeys
  against features.json acceptance criteria, surface gaps.
- Resolves the auditor agent via `agent_manifest` per Goal Governance
  V1 §5 vendor policy (D006 — cross-vendor required by default; no
  hardcoded vendor).
- Writes findings to
  `evidence/goal-governance/pre_impl/sufficiency-findings.json`
  (matches F0's evidence path convention).
- Tests cover: finding-extraction logic with mocked agent response,
  unknown goal_type handling, missing objective_contract handling,
  malformed contract handling, the agent_manifest vendor resolution.

### F004 — plan-lock sufficiency gate

Wires F003 into **every plan-lock path** — not just draft → active
flip (D011). Lock paths to gate:

- CLI: `dontpanic plan lock <plan-dir>`.
- Manual: editing `plan.md` status field directly (validator
  catches at next plan-validation run).
- MCP: any future programmatic lock path through the MCP server.

Gate behavior:

- If `goal_type ∉ {parity, new_feature, migration, incident}`: no
  sufficiency check, lock proceeds normally.
- If gated: run `run_sufficiency_audit()`. If any finding has
  severity ≥ blocking, refuse the lock with a structured error
  pointing at the findings file.
- Operator override: `--ignore-sufficiency-findings <reason>` flag
  (text reason required, recorded in evidence). Override is
  human-in-the-loop; no auto-override.

### F005 — gating dogfood (curated examples)

The proof point. Per D010 + D013 (project-agnostic invariant):
**Spin & Dine and Glam are dogfood examples only — not product
integrations.** The fixtures live plan-local under
`evidence/dogfood/{spin-and-dine,glam}/` and are static curated
representations, not live repo pulls. DontPanic code must remain
project-agnostic; project names appear only in fixture paths /
content / close-out evidence (D013).

- Author static, curated objective_contract files inside this
  plan's evidence dir:
  - **`evidence/dogfood/spin-and-dine/objective_contract.json`** —
    based on prior Spin & Dine Android parity work but treated as
    a generic parity-goal example. user_journeys cover
    onboarding, restaurant voting, saved lists, subscription UX.
    source_of_truth references a curated iOS-style reference (NOT
    a live pull from the Spin & Dine repo). completion_test:
    "Android matches iOS for the four flows including state,
    wiring, and edge cases."
  - **`evidence/dogfood/glam/objective_contract.json`** — based on
    prior Glam Creator Hub work but treated as a generic
    integration-goal example. user_journeys cover create / edit /
    preview / publish / analytics / profile. source_of_truth
    references a curated PRD-style fixture. completion_test:
    "Creator Hub works as a unified product surface, not a
    feature collection."
- Companion synthetic plan dirs at `evidence/dogfood/spin-and-dine/`
  and `evidence/dogfood/glam/` carry a static `plan.md` +
  `features.json` representing what those projects' real plans
  *might* have looked like. Realistic enough to prove the auditor
  catches gaps; **not coupled to external repo state**. The
  fixtures are reproducible artifacts inside F1 evidence.
- Run `run_sufficiency_audit()` against each fixture plan dir.
- Operator review of findings — written disposition required for
  **each plan**:
  - Did the auditor identify ≥1 materially correct gap class?
  - For Spin & Dine: parity matrix incompleteness (any Android-vs-iOS
    coverage gap not represented as a feature).
  - For Glam: integrated Creator Hub journey-coverage (cross-feature
    integration concern, not just per-feature completeness).
- F005 close-out memo includes both written dispositions plus the
  raw sufficiency-findings.json files as evidence.

**Gating wording per D010:**

> F1 close-out fails unless the sufficiency auditor surfaces at least
> one materially correct gap class for Spin & Dine **and** at least
> one materially correct gap class for Glam. If either dogfood case
> fails, the sufficiency prompt, objective-contract schema, or
> decomposition rules must be revised before F1 can close.

## Out of scope (deliberate)

- **Post-impl completion audit.** Plan F2.
- **MCP integration prerequisites.** Plan G.
- **Visibility surface (dashboard).** Plan H.
- **Goal-gap classifier or child-plan spawning.** Already shipped
  in F0; F1 does not modify `nested_orchestration.py` (protected
  per `protected_paths`).
- **Modifying audit envelope schema** (`audit.schema.json`,
  `signoff.schema.json`). F1 only adds `objective_contract.schema.json`
  + extends `plan.schema.json`. The audit/signoff envelopes are
  unchanged.
- **OpenClaw integration.** Locked per Goal Governance V1 §6.7.
- **Cross-instance coordination.** Plan H scope or follow-on Plan I.
- **Auto-spawning child plans on sufficiency findings.** Findings are
  surfaced; operator decides what to do (inline fix vs split into
  features vs reject the plan vs etc.). Auto-spawning is goal-
  governance F2 territory at earliest.

## Locked decisions (operator-supplied at F1 lock turn)

1. **Feature boundaries are determined by independent verification
   and dependency boundaries**, not file count or perceived size.
   D001.
2. **`goal_type` is top-level Plan field; objective_contract is
   referenced via `links.objective_contract`** (path reference, not
   inline embedding). D002.
3. **F1 does NOT declare its own `goal_type`** — bootstrap covered
   by backward-compat (default-None on existing plans). D003.
4. **agent-conventions semver = v1.4.0** (MINOR, additive). D004.
5. **F005 dogfood "materially correct" judgment is operator-reviewed**
   with written disposition per plan. D005.
6. **Cross-vendor goal auditor by default; resolve via
   agent_manifest/config; no hardcoded vendor.** D006.
7. **F005 direct path** — interpretive judgment, not volley-able.
   D007.
8. **F005 stays in F1.** Splitting would let F1 ship without proving
   the failure mode it exists to address. D008.
9. **Cross-repo two-commit boundary** mirroring Plan E. F001 in
   agent-conventions, F002 subtree-pull in DontPanic, F003/F004/F005
   in DontPanic. Separate close-out evidence per feature. D009.
10. **F1 close-out gate strengthened**: fails if either Spin & Dine
    OR Glam dogfood case fails. D010.
11. **F004 sufficiency gate applies to every plan-lock path**, not
    just CLI draft → active. D011.
12. **Project-agnostic invariant.** Spin & Dine and Glam are F1
    dogfood examples only — not product-specific integrations.
    F005 uses static, plan-local fixtures under F1 evidence.
    DontPanic code must remain project-agnostic; project names
    may appear only in dogfood fixture paths / content and
    close-out evidence. D013.

## Execution path

| Feature | Path | Rationale |
|---|---|---|
| F001 | direct | Mechanical schema + model + validator work; greppable acceptance |
| F002 | direct | Subtree pull mechanics; byte-equality verification |
| F003 | direct | Module implementation + tests; deterministic acceptance |
| F004 | direct | Lifecycle wiring; covered by tests |
| F005 | direct | Operator-judged dogfood; volley would produce noise (D007) |

All five direct. Same logic as Plans A, C-F001/F002, D, E, F0.

## Acceptance summary

Binding contract is in `features.json` per feature. Highlights:

- **F001:** v1.4.0 tagged in agent-conventions; objective_contract
  schema + model + Plan model extension + validator rule;
  7-fixture test suite green.
- **F002:** `claude/shared/VERSION` = 1.4.0; subtree byte-equal to
  upstream; existing plans (A–E + F0 + F1) all validate green
  (backward compat).
- **F003:** `sufficiency_auditor.py` exists with the documented
  function shape; tests cover finding extraction + manifest vendor
  resolution + edge cases (unknown goal_type, missing contract,
  malformed contract).
- **F004:** Plan-lock CLI refuses lock on blocking findings;
  `--ignore-sufficiency-findings <reason>` override works; reason
  recorded in evidence; **applies to every lock path** per D011.
- **F005:** Spin & Dine + Glam objective contracts authored;
  sufficiency audit run; operator written disposition for each;
  ≥1 materially correct gap surfaced per plan; close-out memo
  records both dispositions + evidence files.
- **No regressions** in Plan F0 close-out baseline (997 passed, 6
  skipped, per aadb99e).
- Ruff clean. Sanitization clean.
