# Plan 2026-05-02-003 F002 — Close-out Memo

**Status:** F002 closed (passes: true). F003 not yet started.
**Path:** Direct (no volley). Operator-approved with tight-boundary
directive: parsing/validation + signoff-time enforcement only; parent
pause/fan-in deferred to F003.

## Why direct

F002 is a bounded model + parsing + signoff-hook slice with deterministic
tests and minimal design ambiguity beyond what D003 (cross-field invariant)
and D004 (structured Return Condition section) already locked. A volley
would dogfood the surface but not against a real parent→child→close-out
flow, which is what F003 will provide. Direct now; volley once F003
exposes the full nested cycle.

## What shipped

### Models — `nested_orchestration.py` additions

- **`ChildCharter`** Pydantic model: `kind` (Literal["implementation"];
  governance_design rejected with deferral message), `parent_objective`
  (1–500 chars), `parent_acceptance_item` (≥1 char), `allowed_paths`
  (non-empty list of fnmatch globs), `forbidden_decisions` (list, default
  empty), `return_condition_summary` (≥1 char), `may_edit_product_code`
  (no default per D003 — must be explicit), `may_spawn_children`
  (default False; runtime grandchild guard wires alongside F003's
  parent-pause logic).
- **`CommitPolicy`** Pydantic model: `mode` (Literal["child_commit",
  "evidence_only"], default `evidence_only` per D003;
  parent_squash rejected with deferral message), `requires`
  (list of {"patch_completeness", "tests_pass", "evidence_packaged"}).
- **`validate_charter_policy_consistency(charter, policy)`** — D003
  cross-field invariant: `mode='child_commit'` requires
  `may_edit_product_code=True`; `mode='evidence_only'` requires
  `may_edit_product_code=False`. Called from plan_loader after both
  blocks parse independently.

### Return Condition parser (D004) — `parse_return_condition_section(memo_path)`

Heading-anchored markdown section parser. Heading must be exactly
`## Return Condition` (h2; case-sensitive on the words). Within the
section, finds the FIRST line matching
`^\s*status\s*:\s*<value>\s*$` (keyword + value case-insensitive).
Returns one of `Literal["satisfied", "blocked", "superseded"]`.

Raises `ReturnConditionError` on:
- missing memo file
- missing `## Return Condition` section
- missing `status:` line within the section
- illegal status value
- multiple `status:` lines (ambiguous)
- h3 (`### Return Condition`) does not count

### Signoff-time compliance — `check_child_charter_compliance(...)`

Three checks:

1. **Return Condition** (always): `parse_return_condition_section`
   against `<plan_dir>/evidence/closeout-memo.md`. Status `blocked`
   or `superseded` is *recorded*, not raised — F003 is what refuses
   parent re-entry on non-satisfied.
2. **Allowed paths** (mode=`child_commit` only): every modified file
   (passed in, or queried via `git diff --name-only HEAD`) must match
   at least one glob in `allowed_paths`. mode=`evidence_only` skips
   this check entirely (no git invocation).
3. **Requires** (per item):
   - `tests_pass` → `signoff_data['signoff']` must be True.
   - `patch_completeness` → `signoff_data['audits']` must be non-empty.
   - `evidence_packaged` → `<plan_dir>/evidence/` exists and is non-empty.

Raises `ChildCharterViolation` (or `ReturnConditionError`) on failure.
Returns a side-car compliance dict on success.

### Plan loader — `plan_loader.py`

- `LoadedPlan` gains optional `child_charter` and `commit_policy` fields.
- `load()` pops `child_charter` and `commit_policy` from frontmatter
  BEFORE `Plan.model_validate` (which has `extra='forbid'`) — same
  D006-style schema discipline as F001's orchestration block.
- Cross-validation:
  - charter without `orchestration.parent_plan_id` → ValueError
  - charter present + commit_policy absent → synthesize default
    `CommitPolicy(mode='evidence_only', requires=[])` per D003
  - charter + policy → `validate_charter_policy_consistency` (D003)

### Signoff writer — `signoff_writer.py`

- `write_signoff` gains optional `child_charter`, `commit_policy`, and
  `modified_files` kwargs.
- When charter+policy are both passed, runs
  `check_child_charter_compliance` BEFORE persisting any artifact.
  ChildCharterViolation propagates and neither the signoff envelope
  nor the side-car is written (no-partial-artifact, mirrors plan 005
  F002 acceptance #5).
- On compliance pass: writes `audit/signoff-{plan_id}.json` AND
  `audit/charter-compliance-{plan_id}.json` (D008 — side-car
  pattern keeps Signoff schema unchanged).

### Supervisor — `supervisor.py`

- `dispatch_volley`'s signoff_writer.write_signoff call now passes
  `loaded.child_charter` + `loaded.commit_policy` (None for top-level
  plans).
- Catches both `signoff_writer.SignoffWriteError` and
  `nested_orchestration.ChildCharterViolation`, printing `"[volley]
  signoff_writer skipped: …"` so the operator sees why no envelope
  landed without the volley itself crashing.

### Tests — `test_child_charter.py` (new)

51 tests covering:

- **ChildCharter model** (9 tests): valid parse, governance_design
  rejected, unknown kinds rejected, missing-explicit
  may_edit_product_code rejected, may_spawn_children default False,
  empty allowed_paths rejected, parent_objective>500 rejected,
  empty return_condition_summary rejected, extra fields rejected.
- **CommitPolicy model** (7 tests): default mode=evidence_only, valid
  modes parse, parent_squash rejected with deferral, unknown modes
  rejected, valid requires items parse, invalid requires items
  rejected, extra fields rejected.
- **Cross-field invariant** (4 tests): all four combinations of
  (mode, may_edit_product_code).
- **`parse_return_condition_section`** (12 tests): three statuses,
  case-insensitive keyword + value, section-isolation when followed
  by another `##` heading, missing memo/section/status,
  illegal value, multiple status lines, h3 heading rejected.
- **`check_child_charter_compliance`** (11 tests): evidence_only +
  satisfied, blocked recorded without raise, superseded recorded
  without raise, missing section raises, child_commit with valid
  paths, child_commit with paths outside allowed_paths raises,
  evidence_only skips path check, requires=tests_pass satisfied,
  requires=tests_pass unsatisfied raises, requires=patch_completeness
  unsatisfied raises, requires=evidence_packaged satisfied.
- **plan_loader integration** (5 tests): top-level no-charter,
  child plan parses charter+policy, default policy synthesized when
  charter present + policy absent, charter-without-parent rejected,
  charter↔policy mismatch rejected at load.
- **signoff_writer integration** (3 tests): compliance pass writes
  signoff + side-car, violation blocks both writes, no-charter case
  skips compliance entirely (top-level plans unchanged).

## Schema discipline (D008)

The Signoff schema in agent-conventions/v1.0 uses `extra='forbid'`.
Embedding `return_condition_status` and `compliance_checks_satisfied`
inside the signoff envelope would require a schema bump + downstream
subtree pulls. F002 instead writes a side-car at
`audit/charter-compliance-{plan_id}.json` containing those fields.

This matches F001's pattern (orchestration block popped before
`Plan.model_validate`) — parser-level concerns live outside
agent-conventions schemas. F003's parent re-entry approve will read
the side-car at the child's `audit/charter-compliance-{child_id}.json`.
Recorded as D008.

## Test / lint / sanitization state

- **Targeted:** `pytest scripts/jarvis_orchestrate/tests/test_child_charter.py`
  → 51 passed.
- **Full orchestrate suite:** `pytest scripts/jarvis_orchestrate/tests/`
  → 541 passed, 6 skipped (was 490 + 6 skipped before this work; +51).
- **Ruff:** `ruff check` on the five changed/added files → all checks
  passed.
- **Sanitization:** `python scripts/sanitization_check.py` →
  `✓ no campaign IDs or secret shapes in sanitized surface (559 files
  scanned)`.

### Test state

| Surface | Before | After | Delta |
| --- | --- | --- | --- |
| F002 targeted | n/a | 51 passed | +51 |
| Full orchestrate suite | 490 + 6 skipped | 541 + 6 skipped | +51 |
| Ruff (changed files) | clean | clean | — |
| Sanitization | clean | clean | — |

## Files in this commit (scoped per operator directive)

- `scripts/jarvis_orchestrate/nested_orchestration.py` (extended)
- `scripts/jarvis_orchestrate/plan_loader.py` (charter/policy parse +
  cross-validation)
- `scripts/jarvis_orchestrate/signoff_writer.py` (compliance hook +
  side-car write)
- `scripts/jarvis_orchestrate/supervisor.py` (thread charter/policy
  through to write_signoff; catch ChildCharterViolation)
- `scripts/jarvis_orchestrate/tests/test_child_charter.py` (new, 51
  tests)
- `docs/plans/2026-05-02-003-feat-nested-orchestration-v1/decisions.jsonl`
  (D008 side-car deviation, D009 close-out)
- `docs/plans/2026-05-02-003-feat-nested-orchestration-v1/features.json`
  (F002 → passes: true with 7 evidence_refs)
- `docs/plans/2026-05-02-003-feat-nested-orchestration-v1/evidence/f002-closeout-memo.md`
  (this file)

F003 surfaces (parent pause/fan-in protocol, `pre_resume_after_child`
gate, INBOX nested_child_pending template, events.jsonl writer,
grandchild may_spawn_children dispatch refusal) are **not** touched.

## Plan 003 status after this commit

- F001: ✅ closed (parent/child metadata + depth/cycle/repeated-finding
  guards).
- F002: ✅ closed (child charter + commit policy + signoff-time
  compliance).
- F003: pending (parent pause/fan-in protocol — depends on F001 + F002).

Next: F003. Volley dispatch becomes more useful at F003 because the
full parent→child→close-out cycle exists to dogfood; will evaluate at
dispatch time.
