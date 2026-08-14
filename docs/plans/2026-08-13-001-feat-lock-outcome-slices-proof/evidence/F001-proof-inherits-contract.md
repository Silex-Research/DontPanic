# F001 — optional `proof` + `inherits` on the outcome contract

Iteration 0. Repo: `agent-conventions` (source of truth) → subtree-pulled into
DontPanic `claude/shared/`. Env: dev. Project: none.

## What landed

`schemas/v1.0/objective_contract.schema.json` + `models/objective_contract_model.py`,
agent-conventions **v1.16.0 → v1.17.0**:

- **`delivers[].proof`** — optional `{metric, method, surface?}`.
  `metric` is a string of at least 10 characters; `method` is a closed enum
  `walk | request | named_test | probe`; `surface` (optional) reuses the
  11-value plan-level surfaces enum. `additionalProperties: false`.
  Distinct from `proof_refs`: those point at features that were built, `proof`
  names the measurement that would falsify delivery.
- **`inherits`** — optional contract-level plan id this contract deltas from,
  using the same plan-id grammar as `delivers[].proof_refs[].plan`.
  `additionalProperties: false` at the contract level too.

Both are optional and no plan on disk carries either, so the change is purely
additive.

### Reading of step 2 recorded explicitly

The step says a child/fix plan "may omit a full `delivers[]` when `inherits` is
set and a delta `delivers[]` is present". Since a delta *is* a `delivers[]`, the
v1.1 non-empty rule in `validate.py` still applies unchanged — what `inherits`
licenses is omitting the parent's **full** outcome set, not the block. The
validator therefore needed no relaxation; the semantics are documented in the
schema description, the Pydantic docstring, and asserted by dispatch case 14.

Per step 4, absence of `proof` stays valid at the schema layer. Whether a
missing proof is inferred, an accepted gap, or a close-time failure is F002's
call, not the schema's.

## Verification

### Schema ↔ Pydantic agreement — `scripts/test_objective_contract_proof.py`

New. Every fixture is validated **twice** (raw JSON Schema via `jsonschema`,
then the Pydantic `ObjectiveContract`) and the two verdicts must agree —
acceptance 2 names both validators, and they are independent implementations.

| fixture | expected |
|---|---|
| `proof-walk-valid` | accept — **acceptance 1** |
| `proof-method-unknown` (`kpi_warehouse`) | reject — **acceptance 2** |
| `proof-metric-too-short` | reject |
| `proof-missing-method` | reject |
| `proof-extra-key` | reject (`additionalProperties: false`) |
| `proof-surface-unknown` | reject |
| `inherits-delta-one-item` | accept — **acceptance 3** |
| `inherits-bad-plan-id` | reject |
| `no-proof-baseline` | accept — **acceptance 4**, schema layer |
| `contract-extra-key` | reject (contract-level `additionalProperties`) |

Plus: all four cheap methods accepted by both; five explicit-`null` cases
(`proof`, `metric`, `method`, `surface`, `inherits`) rejected by both; the
surfaces enum asserted identical across `objective_contract.schema.json`,
`plan.schema.json` and the Pydantic `ProofSurface`; and the `inherits` plan-id
pattern asserted identical to `proof_refs[].plan`.

```
PASS: 10 fixtures × 2 validators agree, 4 methods accepted by both,
5 null cases rejected by both, surface enum and plan-id grammar in lockstep
```

### End-to-end through `validate.py` — `scripts/test_objective_contract.py`

Acceptance 1 and 3 say "a fixture **plan**", so both fields are also carried
through the real validator path (`validate_plan_dir` → `_check_objective_contract`)
on minimal-but-real plan directories, not only through the schema in isolation:

- case 13 `_fixture_v11_proof_walk` → exit 0, `✓ objective_contract`
- case 14 `_fixture_v11_inherits_delta` → exit 0, `✓ objective_contract`
  (fix plan, `inherits` set, ONE-item delta `delivers[]`)

```
✓ all 14 dispatch cases pass   (12 pre-existing + 2 new)
```

### Acceptance 4 — existing plans keep their exit code

Every plan directory under `docs/plans/` validated before the change and again
after both subtree pulls, comparing per-plan exit codes:

```
120 plans — exit codes IDENTICAL (97 × 0, 23 × 1)
```

The 23 failures are pre-existing and unchanged. No plan file was modified.
Raw records: `F001-validation-exit-codes-before.txt` / `-after.txt`.

### Acceptance 5 — subtree matches agent-conventions

After `git subtree pull --prefix=claude/shared agent-conventions … --squash`:

- `schemas/` — identical (excluding untracked `__pycache__`)
- `scripts/` — identical
- `tests/` — 62 tracked files, lists and contents identical
- `VERSION` — `1.17.0` on both sides

All four contract tests re-run from the DontPanic copy:

```
test_validator_dispatch:        ✓ all 4 dispatch cases pass
test_objective_contract:        ✓ all 14 dispatch cases pass
test_user_impact_contract:      PASS: 6 fixtures × 2 validators agree, …
test_objective_contract_proof:  PASS: 10 fixtures × 2 validators agree, …
```

`scripts/test_objective_contract_proof.py` is wired into the agent-conventions
CI workflow alongside the three existing contract tests.

## Commands run

```
$ python3 claude/shared/schemas/v1.0/validate.py <each of 120 docs/plans/*/>   # before + after
$ python3 scripts/test_objective_contract_proof.py                             # agent-conventions
$ python3 scripts/test_objective_contract.py                                   # agent-conventions
$ python3 scripts/test_user_impact_contract.py                                 # agent-conventions
$ python3 scripts/test_validator_dispatch.py                                   # agent-conventions
$ git -C /Users/bayesian/Code/agent-conventions commit   (fa0f219, f21ad62)
$ git stash push / git stash pop --index                                       # DontPanic, twice
$ git fetch agent-conventions feat/user-impact-pr
$ git subtree pull --prefix=claude/shared agent-conventions feat/user-impact-pr --squash
```

## Not done (out of F001 scope)

- No existing plan migrated to carry `proof` or `inherits` (step 4).
- No lock/close scoring behaviour — that is F002. `validate.py`'s
  delivers-required rule is unchanged.
- agent-conventions commits are local; pushing upstream is the operator's
  out-of-band step, per the subtree CHANGELOG convention.
