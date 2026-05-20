# agent-conventions changelog

This file tracks DontPanic's subtree mirror of `agent-conventions`. The upstream
canonical history lives in `agent-conventions` itself; entries here record what
landed in the DontPanic subtree first (and that the operator subsequently
pushed upstream out-of-band).

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
