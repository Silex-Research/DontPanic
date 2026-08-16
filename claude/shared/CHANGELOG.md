# agent-conventions changelog

This file tracks DontPanic's subtree mirror of `agent-conventions`. The upstream
canonical history lives in `agent-conventions` itself; entries here record what
landed in the DontPanic subtree first (and that the operator subsequently
pushed upstream out-of-band).

## 1.20.0 — 2026-08-16

### Added
- `claim.schema.json` + `models/claim_model.py`: verified-admission claim
  contract (`proposed|admitted|rejected|stale`). Admitted requires non-empty
  `evidence_refs` plus `admitted_by`/`admitted_at`. Reuses the features
  `evidence_ref` shape. `additionalProperties: false`.
- `decisions.schema.json` + `models/decisions_model.py`: one `decisions.jsonl`
  line. Accepts both DontPanic line shapes (question/answer/status and
  id/ts/by/title/body). `id` matches `^D\\d{3}$`.
- `behavior.schema.json` + `models/behavior_model.py`: hidden process-behavior
  verdicts (`owner_role` implementer|auditor|supervisor; `adherence`
  expected|n/a|violated). Violated requires evidence. Schema description
  states specs are hidden from worker prompts.
- Contract tests `scripts/test_{claim,decisions,behavior}_contract.py` plus
  fixtures under `tests/{claim,decisions,behavior}/`. JSON Schema and
  Pydantic agree on each fixture set.

## 1.17.0 — 2026-08-13

### Added
- `objective_contract.schema.json` + `models/objective_contract_model.py`: an
  OPTIONAL `proof` object on each `delivers[]` item — `metric` (>=10 chars),
  `method` (`walk` / `request` / `named_test` / `probe`), and an optional
  `surface` drawn from the plan-level surfaces enum. `proof` names the cheap
  first-principle measurement that would show a slice's capability is true;
  `proof_refs` (unchanged) points at the features that were built. The method
  enum is closed on purpose: a proof needing a warehouse, a dashboard, or a
  quarter of data is not cheap and does not belong in a lock.
- `objective_contract.schema.json` + model: an OPTIONAL contract-level
  `inherits` — the plan id this contract deltas from — so a child or fix plan
  carries ONE slice instead of restating the parent's outcome set. `delivers[]`
  stays required and non-empty at plan `schema_version` >= 1.1: a delta IS a
  `delivers[]`, and what `inherits` licenses is omitting the FULL set, not the
  block. `inherits` reuses the plan-id grammar of `proof_refs[].plan`, asserted
  identical by the test below. Whether the pointer resolves is a lock-time
  question, deliberately left to plan 2026-08-13-001 F002.
- `scripts/test_objective_contract_proof.py` + `tests/objective_contract_proof/`:
  the JSON Schema and the Pydantic model are independent implementations, so
  this asserts they cannot drift — ten fixtures produce identical verdicts from
  both validators, all four cheap methods are accepted by both, five null cases
  are rejected by both, and the 11-value `surfaces` enum is asserted identical
  across `objective_contract.schema.json`, `plan.schema.json` and the Pydantic
  `ProofSurface`. Wired into CI alongside the three existing contract tests.
- `scripts/test_objective_contract.py` cases 13-14 + two plan-dir fixtures
  (`_fixture_v11_proof_walk`, `_fixture_v11_inherits_delta`): the same two
  fields carried END-TO-END through `validate.py` on a real plan directory, not
  just through the schema. Case 14 is the load-bearing one — a fix plan with
  `inherits` and a ONE-ITEM delta `delivers[]` must still satisfy the v1.1
  non-empty rule, because `inherits` licenses omitting the parent's full set
  rather than the block itself.

### Backward compatibility
- Purely additive. Both `proof` and `inherits` are optional and no plan on disk
  carries either, so existing contracts validate untouched. Absence of `proof`
  stays valid at the schema layer by design — lock and close decide what a
  missing proof costs (plan 2026-08-13-001 F002), not the schema. Verified by
  running the validator across all 120 plan directories under `docs/plans` in
  DontPanic before and after the subtree pull: identical per-plan exit codes
  (97 pass / 23 pre-existing failures), no plan file modified.

## 1.16.0 — 2026-08-09

### Added
- `features.schema.json` + `models/features_model.py`: an OPTIONAL `user_impact`
  block on a feature (`audience` / `summary` / `surfaces` / `description_hash`),
  so the decision brief rendered at a human approval gate can lead with what an
  audience experiences rather than with plan mechanics. `audience: none` is a
  complete declaration on its own and must carry neither summary nor surfaces
  (D003); any other audience owes a summary of at least 10 characters, a
  non-empty `surfaces` array, and `description_hash` — a SHA-256 digest of the
  feature `description` the claim was written against, so a consuming brief can
  distinguish declared / possibly-stale / undeclared without inventing a fourth
  "digest unknown" state (D005).
- `scripts/test_user_impact_contract.py` + `tests/user_impact/`: the JSON Schema
  and the Pydantic model are independent implementations of those rules, so this
  asserts they cannot drift — six fixtures produce identical verdicts from both
  validators, four null cases are rejected by both, and the 11-value `surfaces`
  enum is asserted identical to the one in `plan.schema.json`. Wired into CI
  alongside the two existing contract tests.

### Backward compatibility
- Purely additive. `user_impact` is optional and every plan already on disk
  omits it, so existing `features.json` files validate untouched. Verified by
  running the validator across all 117 plan directories under `docs/plans` in
  DontPanic with no plan file modified.

## 1.15.0 — 2026-06-28

### Added
- `objective_contract.schema.json` + `models/objective_contract_model.py`: a
  typed `delivers[]` block (`audience` / `kind` / `capability` / `proof_refs`)
  encoding audience-first plan outcomes — *what becomes true, for whom, what
  kind of capability, and which features prove it*. `audience` and `kind` are
  closed enums; `proof_refs` are typed feature references (`{type:'feature',
  id:'F014'[, plan:'<plan-id>']}`) rather than overloaded path strings, so proof
  can't drift from `features.json`.
- `plan.schema.json` + `models/plan_model.py`: optional plan-authoring
  `schema_version` (`^\d+\.\d+$`), independent of this package VERSION. Absent /
  `1.0` = grandfathered.

### Changed
- `objective_contract` `goal_type` enum expanded from the original four
  (parity/new_feature/migration/incident) to the full Plan goal_type set
  (+ mechanical/infra/refactor), and `user_journeys` is now OPTIONAL — together
  these enable a "lite universal contract" (delivers-only, no journeys) for
  infra/refactor/mechanical plans.
- `validate.py`: at plan `schema_version >= 1.1`, a SUBSTANTIVE plan
  (tier != trivial) must declare an objective contract carrying a non-empty
  `delivers[]`; below 1.1 the check is advisory (inline ⚠, never a failure).
  Strictly additive — every plan that validated under 1.0 still validates, and
  no existing plan declares 1.1.

### Motivation
Plan reporting defaulted to internal topology (F-ids, phases, verdicts) instead
of answering the builder's first question: *after this succeeds, what can a
human or agent safely do that they couldn't before?* The reporting contract
(plan-artifacts SKILL.md) fixes the prose; `delivers[]` gives future plans an
outcome-bearing artifact so the summary can be a projection of the contract
rather than a parallel story that drifts.

## 1.14.0 — 2026-06-21

### Added
- `upgrade-releases.schema.json` + `models/upgrade_releases_model.py`
  (`UpgradeManifest`, `UpgradeRelease`, `UpgradeAction`, `UpgradeCommand`): the
  release-manifest contract for the upgrade-readiness layer in `dontpanic
  doctor` (plan `2026-06-21-001-feat-upgrade-readiness-doctor` F001). A manifest
  carries a top-level baseline (`baseline_release` + `baseline_date`, D018) and
  an ordered `releases[]` list. Each release declares required/advisory operator
  actions with closed enums (`kind`, `severity`, command `label`), an ORDERED
  `commands[]` checklist (preview→apply→verify→run, D017), and the
  UX-critical per-action fields (`applies_when`, `status_probe`,
  `success_message`, `failure_message`, `human_next_step`, `docs_url`,
  `introduced_commands`). The schema is closed (unknown keys/enums rejected).
- Cross-field invariants live in the Pydantic model (not expressible in plain
  JSON Schema): required-action probe (D021), required-command apply (D029),
  ordered apply+verify checklist (D036), id-uniqueness (D030), and non-blank
  command strings (D047).

### Motivation
The manifest — not the prose CHANGELOG, not the plan ledger (D002) — is the
single machine source of truth for upgrade intent. The consumer-side loader
(`dontpanic_orchestrate/release_manifest.py`) resolves
`docs/upgrade/releases.json` as a package-relative resource (D045) so it loads
outside the repo root and off-git.

## 1.12.0 — 2026-05-22

### Added
- `plan.schema.json`: optional `requires_capabilities[]` array on the plan
  frontmatter. Items are strings matching the capability id pattern
  `^[a-z0-9][a-z0-9-]*$` with `uniqueItems: true`. The field is NOT in the
  schema's `required` array — plans without it continue to validate
  unchanged.
- `models/plan_model.py`: matching `Plan.requires_capabilities: list[constr(...)] | None`
  field with the same pattern so the Pydantic mirror stays in lockstep.

### Motivation
DontPanic plan `2026-05-22-002-feat-capability-status-v0` F003 introduces a
lock-time advisory sidecar. `dontpanic plan lock` validates every
`requires_capabilities[]` entry against the manifest registry (unknown id
fails loud with a closest-match suggestion) and emits
`evidence/required-capabilities.json` summarizing per-capability readiness.
The sidecar is advisory — lock proceeds even when bound capabilities are
not ready, so a plan can ship the binding without gating implementation on
operator setup completion.

### Notes
- Strictly additive: every plan that validated under v1.11.0 continues to
  validate under v1.12.0.
- DontPanic-side change first. Operator cherry-picks into
  `agent-conventions`, tags `v1.12.0`, and pushes the subtree separately.

## 1.11.0 — 2026-05-22

### Added
- `capability.schema.json`: optional `setup_steps[]` array field on the
  capability manifest. Each entry is `{id, what, automatable,
  command_template?, verify_probe?, human_required_reason?}`. `id` follows
  the `^[a-z0-9][a-z0-9_-]*$` pattern; `command_template`, `verify_probe`,
  and `human_required_reason` accept `string | null`. The field is NOT in
  the schema's `required` array — manifests without it continue to validate
  unchanged.
- `capability.schema.json`: `setup_steps[]` declares a non-standard
  `uniqueBy: "id"` keyword in addition to standard `uniqueItems: true`. The
  reference loader (`dontpanic_orchestrate.capabilities`) registers a
  matching custom validator on `Draft202012Validator` so two entries
  sharing the same `id` (but differing in other fields, which `uniqueItems`
  does NOT catch) are rejected at the schema-validation step. Generic JSON
  Schema validators will ignore the keyword as an unknown annotation —
  consumers that need cross-item id-uniqueness must either reuse the
  reference loader or implement the same check.

### Motivation
DontPanic plan `2026-05-22-002-feat-capability-status-v0` F001 introduces a
machine-readable setup-step list so the forthcoming `dontpanic capabilities
status` CLI (F002) can render automatable vs. human-required next actions.
The change is strictly additive: the `schema_version` const stays `1.0.0`
because every manifest validated under v1.10.0 still validates under v1.11.0.

### Notes
- Backward compatible: existing four checked-in manifests (without
  `setup_steps`) continue to load with no test changes; `CapabilityManifest`
  defaults the field to an empty tuple.
- DontPanic-side change first. Operator cherry-picks into
  `agent-conventions`, tags `v1.11.0`, and pushes the subtree separately.

## 1.9.1 — 2026-05-19

### Changed
- `plan.schema.json`: `title.maxLength` 120 → 200. Surfaced by Roadmap Plan 3
  F003's `dontpanic doctor --validate-plans-strict` probe walking every locked
  plan: one locked plan (`2026-05-09-001-fix-conftest-global-config-isolation`)
  carried a 137-char title that violated the v1.8.0-era cap. Loosening the cap
  is strictly additive (existing titles still validate) and completes F001's
  invariant that "every existing locked plan validates after the change."
- `models/plan_model.py`: matching `constr(max_length=200)` bump on the
  `Plan.title` field to keep the Pydantic mirror in lockstep.

### Notes
- Strictly additive: every plan that validated under v1.9.0 still validates.

## 1.9.0 — 2026-05-19

### Added
- `plan.schema.json`: `orchestration`, `child_charter`, and `commit_policy`
  are now declared root properties on the Plan schema (strictly additive; no
  new required fields). Each carries a `description` with concrete shape
  examples lifted from v4.1 plan `2026-05-12-002`. Enum contract matches the
  plan-3 acceptance text literally — `spawn_reason ∈ {operator_manual,
  auto, test}`, `child_charter.kind ∈ {implementation, investigation,
  migration}`, `commit_policy.mode ∈ {child_commit, parent_commit, manual}`,
  and `commit_policy.requires` is `array of strings` (the runtime narrows
  the vocabulary, the schema does not — so the runtime can extend without
  a future schema bump).
- `models/plan_model.py`: matching `Optional[Orchestration]`,
  `Optional[ChildCharter]`, and `Optional[CommitPolicy]` sub-models with
  field-level docstrings. Enums (`SpawnReason`, `ChildCharterKind`,
  `CommitPolicyMode`) mirror the JSON schema literal-for-literal.

### Motivation
Every locked plan since DontPanic v3 declared `orchestration`,
`child_charter`, and `commit_policy` keys in its plan.md frontmatter. The
runtime (`plan_loader`) pops these blocks before calling
`Plan.model_validate`, so dispatch worked — but a direct
`jsonschema.validate` against `plan.schema.json` failed every locked plan
with `Additional properties are not allowed`. This was a quiet timebomb:
DontPanic Roadmap Plan 2 was about to harden doctor validation, which would
have broken all locked plans. Roadmap Plan 3 (this fix) is sequenced first
per operator review, so Plan 2 can land on a self-consistent schema.

### Notes
- Strictly additive: no new required root-level fields, existing root
  properties unchanged. Every locked plan continues to validate.
- Backward compatible: validators that accept the old (v1.8.0) schema will
  treat the new blocks as `additionalProperties`-rejected when given a
  v1.9-shaped plan; v1.9-pinned validators accept them.
- DontPanic-side change only. Operator cherry-picks into `agent-conventions`,
  tags `v1.9.0`, and pushes the subtree separately (per plan D003 / F002).

## 1.8.0 — 2026-05-12

### Added
- `audit.schema.json`: `parsing` added as a 10th value to the
  `finding.category` enum. Strictly additive; the existing nine values
  (`correctness`, `security`, `performance`, `architecture`, `style`,
  `currency`, `redaction`, `test_coverage`, `documentation`) are unchanged.
- `models/audit_model.py`: `Category` enum gains `parsing = 'parsing'` to
  mirror the JSON schema.

### Motivation
DontPanic plan `2026-05-12-001-fix-harness-frictions-v4` F003 emitted advisory
findings for shlex parse failures inside `commands_run`. The F003 spec text
called for `severity=advisory category=parsing`, but the v1.7.0 enum did not
include `parsing`, so the F003 implementer fell back to `correctness` and
v4 D008 documented the deviation as a spec_ambiguity. v4.1 F001
(plan `2026-05-12-002-fix-harness-frictions-v4-1`) closes that gap by making
the new enum value real.

### Notes
- Backward compatible: validators that accept the old 9-value enum will fail
  closed on a `parsing` finding (the desired strict behavior); validators
  pinned to v1.8.0 schemas accept it.
- DontPanic-side change only. The operator cherry-picks this into
  `agent-conventions`, tags `v1.8.0`, and pushes the subtree separately
  (per plan D003).
