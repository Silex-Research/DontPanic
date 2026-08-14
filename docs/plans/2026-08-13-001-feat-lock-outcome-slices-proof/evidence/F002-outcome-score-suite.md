# F002 — outcome / slices / proofs at lock: acceptance → test map

Plan `2026-08-13-001-feat-lock-outcome-slices-proof`, feature F002 after the
D010 split (F004 owns slice identity, F005 owns sidecar durability).

Repo: DontPanic | Env: dev | Project: (none) | Date: 2026-08-14

Raw command output: [`F002-outcome-score-suite-run.txt`](./F002-outcome-score-suite-run.txt).

## The three routes to an outcome

Lock refuses on one thing only (D003, narrowed by D009): *no outcome is
reachable by any route*.

1. a `delivers[]` entry that actually states one (audience, kind, capability
   ≥10 chars, one `proof_refs` id) — `slice_defects()`;
2. a resolvable `inherits` pointing at a parent that carries an outcome by any
   of these three routes — `_resolve_inherits()`;
3. **a feature carrying its own proof** — `{metric ≥10 chars, method ∈
   walk|request|named_test|probe}`, both halves required — `proof_defects()` /
   `feature_proof_method()`. One such feature IS a slice (D009).

## Acceptance → test

| AC | Claim | Test |
|---|---|---|
| 1 | No delivers, no inherits, no proof-carrying feature → refuse naming `outcome`; status stays draft | `test_ac1_no_delivers_no_inherits_refuses_lock_naming_outcome`, `test_ac1_refusal_names_only_the_outcome_not_the_proofs`, `test_ac1_refusal_names_the_feature_route_as_a_way_out` |
| 2 | Inherits a parent + one delta slice → locks (`outcome: inherited`, `slices: single`) | `test_ac2_inherit_fix_with_one_delta_slice_locks`, `test_ac2_inherit_with_no_local_delta_still_locks` |
| 3 | Features each carry a proof, no `delivers[]` → LOCKS, one slice per proof-carrying feature | `test_ac3_features_carrying_proofs_lock_with_no_delivers` (3 features → 3 slices, `one-per-slice`), `test_ac3_one_proof_carrying_feature_clears_the_refusal_with_no_contract` |
| 4 | Feature-as-slice with no `user_impact` locks and records an accepted gap naming the absent audience | `test_ac4_feature_as_slice_without_user_impact_locks_and_records_the_gap` (exit 0; sidecar `audience_gap: true`) |
| 5 | Outcome + accepted missing proof → locks and the gap is recorded | `test_ac5_accepted_missing_proof_locks_and_records_the_gap` (sidecar `gap_accepted: true`, `method_checked_at_close: walk`) |
| 6 | Existing plans without proof still lock — inferred or accepted-gap, never a surprise refuse | `test_ac6_legacy_plan_without_contract_locks`, `test_ac6_trivial_tier_plan_is_not_refused`, `test_ac6_plan_with_outcome_but_no_proof_locks_as_inferred`, `test_ac6_a_feature_without_a_proof_is_not_a_slice` |
| 7 | The suite passes, evidenced with real output | `87 passed in 21.91s`, ruff clean — see the raw capture |

Not an F002 criterion after the split, kept as regression cover because it runs
through this module: the close-time obligation tests
(`test_close_fails_until_proof_runs_or_gap_is_deferred` and neighbours) and the
locked-obligation tests, which belong to F004/F005.

## AC6 checked against the real corpus, not only fixtures

`score_plan()` was run read-only over all 120 plan dirs in `docs/plans/`:

```
plans scored: 120
outcome: {'missing': 120}
plans with no declared proof on any slice: 120
would refuse a fresh lock: 0
```

Stated honestly: **zero** of the 120 would be refused, but that safety comes
from the applicability threshold, not from the routes. None of the 120 declares
`schema_version` in its frontmatter, so all parse as `(1, 0)` — below
`_DELIVERS_REQUIRED_FROM = (1, 1)` — and the missing outcome prints as an
advisory line instead of a refusal, mirroring
`validate.py._check_objective_contract`. The first plan authored at
`schema_version: "1.1"` is the first one the refusal can apply to, which is the
intended migration edge, not a regression.

## Not changed here

`close_obligations()` and `read_score_sidecar()` are untouched (F004/F005 own
the index-keying defect and the missing-vs-corrupt sidecar semantics the i2
auditor found). The i1 malformed-`delivers` bypass stays fixed: `delivers: [{}]`
scores zero slices and the refusal names every absent field.
