# F003 implementation notes — strict plan-schema validation probe

## Shipped

1. **`scripts/dontpanic_doctor.py`**: added `validate_plans_strict()` probe.
   - Walks `docs/plans/` for plans with locked status (`active`,
     `ready_for_audit`, `in_audit`, `completed`, `abandoned`, `blocked`).
   - Runs `jsonschema.Draft202012Validator` against
     `claude/shared/schemas/v1.0/plan.schema.json`.
   - Emits one `CheckResult` per failing plan (`validate-plans-strict:<plan_id>`)
     plus a summary entry; clean plans fold into the summary count.
   - Always runs (no opt-in flag). `--validate-plans-strict` promotes
     failures to FAIL (ok=False) and implicitly opts into the
     `--strict-codes` exit matrix so a strict-mode failure exits 2.
   - Default mode keeps failures as WARN (ok=True, warn=True), exit 0
     under the legacy contract.

2. **`scripts/dontpanic_orchestrate/tests/test_doctor_validate_plans_strict_f003.py`**:
   5 fixture tests covering F003 acceptance:
   - All live locked plans validate clean (the regression net).
   - Malformed `orchestration.depth_limit` (string vs integer) fails
     strict mode with per-field path in the message.
   - `--validate-plans-strict` CLI returns exit 2 on failure.
   - Advisory mode returns exit 0 on failure and emits WARN lines.
   - JSON output (`--json`) carries the per-plan detail array
     addressable by plan id.

3. **Schema patch: `title.maxLength` 120 → 200** (and matching
   `constr(max_length=200)` in the Pydantic mirror; VERSION bumped
   1.9.0 → 1.9.1; CHANGELOG entry added).
   - Surfaced by the new probe walking the live locked-plan set: one
     locked plan (`2026-05-09-001-fix-conftest-global-config-isolation`)
     carried a 137-char title.
   - Strictly additive (more strings accepted, no required-field
     changes). Completes F001's invariant that "every existing locked
     plan validates after the change."
   - Two test files in the orchestrate sweep had exact pins on
     `1.9.0` and were relaxed to accept any `1.9.x` (forward-compat
     while still guarding against rollback to 1.8.x).

## Verification

```
$ python3 scripts/dontpanic_doctor.py --skip-auth --validate-plans-strict --json | jq '.checks[] | select(.name | startswith("validate-plans-strict"))'
{
  "name": "validate-plans-strict",
  "ok": true,
  "message": "46 locked plan(s) under docs/plans validate clean against plan.schema.json",
  ...
}
```

```
$ PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/ -q
1978 passed, 7 skipped in 27.44s
```

## Acceptance map

- (1) `validate_plans_strict()` probe registered ✓
- (2) Default mode advisory; `--validate-plans-strict` blockers (exit 2) ✓
- (3) JSON output includes the probe + per-plan detail array ✓
- (4) Fixture test module covers ≥4 cases (shipped 5) ✓
- (5) `dontpanic doctor --validate-plans-strict` returns zero
      plan-validation failures across the live locked-plan set ✓
- (6) Full sweep ≥1929 green (1978 passed, 7 skipped) ✓
