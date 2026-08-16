# Promoting a failure into a corpus scenario

Plan 2026-08-09-004 F008. Referenced from the plan-artifacts skill.

A real failure becomes a scenario by adding a directory under
`scripts/dontpanic_orchestrate/smoke/scenarios/`. Do not edit the
orchestrator package.

## Three artifacts a failure must carry

1. **Trigger** — what input produced the failure (`source_incident` + `source_date`).
2. **Observed behavior** — what the system did (`expected_current_behavior`).
3. **Intended behavior** — what it should have done (`intended_behavior`).

Without all three the case is not promotable.

## Anti-pattern

Writing a scenario and its grader in the same sitting produces a test
that asserts the code does what the code does. The intended-behavior
field exists so a scenario may legitimately fail against today's
implementation (`expected_to_fail: true`).

## How to add one

1. Copy an existing scenario directory, or point `plan_fixture` at a
   sibling fixture.
2. Set `suite` to `regression` (must stay green) or `capability` (may fail).
3. Fill the three provenance fields.
4. Drop `scenario.json` under `smoke/scenarios/<id>/`.
5. `PYTHONPATH=scripts python -c "from dontpanic_orchestrate.smoke.corpus import run_corpus; print(run_corpus(execute=False).text)"`

The walker picks it up. No Python change.
