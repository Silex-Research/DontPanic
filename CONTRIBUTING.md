# Contributing to agent-conventions

`agent-conventions` is a public contract repository. Changes should be small,
versioned, and safe for downstream projects to pin by tag.

## Local Checks

Run before opening a PR:

```bash
python3 scripts/test_validator_dispatch.py
python3 scripts/test_objective_contract.py
python3 scripts/test_user_impact_contract.py
python3 scripts/test_objective_contract_proof.py
python3 scripts/test_claim_contract.py
python3 scripts/test_decisions_contract.py
python3 scripts/test_behavior_contract.py
```

CI runs the same list in `.github/workflows/validate.yml`; keep the two in step
when you add a check.

If you change a schema, update the matching generated Pydantic model in
`schemas/v1.0/models/` and add a changelog entry.

## Versioning Rules

- Additive schema changes get a new minor tag, for example `v1.11.0`.
- Bugfixes or documentation-only corrections can use a patch tag.
- Never ask downstream consumers to pull `master` directly. Consumers should
  subtree-pull a specific tag.

## Pull Request Expectations

- Explain which downstream artifact shape changes.
- Include validator or fixture coverage for behavior changes.
- Keep generated model diffs paired with their schema diffs.
- Do not mix unrelated convention, resolver, and schema changes in one PR.

## Ownership

Contract files are protected by CODEOWNERS. Maintainer review is required for
schema, model, resolver, workflow, and release-process changes.
