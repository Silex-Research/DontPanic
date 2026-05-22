# agent-conventions changelog

This file tracks DontPanic's subtree mirror of `agent-conventions`. The upstream
canonical history lives in `agent-conventions` itself; entries here record what
landed in the DontPanic subtree first (and that the operator subsequently
pushed upstream out-of-band).

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
