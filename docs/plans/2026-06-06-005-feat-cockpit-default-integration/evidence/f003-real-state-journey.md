# F003 — real-state → real-shell journey

## What shipped
- `dashboard/tests/integration/cockpit-journey-f003.test.js` (3) — boots the REAL `createJarvis().init()`
  shell with the cockpit page module, against PRODUCER-generated triage state served via the fetch mock:
  - **lands on the Cockpit** (`J.currentPage === 'cockpit'`) rendering the real queue — hero count ==
    the producer's need-you count (6), NO raw JSON leak, resolution intents on the face (`[data-resolution]`),
    and render-truth honesty (NO `[data-filled="true"]` proven-live dot in v0).
  - **anti-synthetic negatives**: missing triage state (404) → honest build-prompt, never a fabricated
    queue; stale state (30h) → demoted under a stale banner, never rendered fresh.
- `dashboard/tests/fixtures/real-state/operator-triage.json` — NOT hand-authored: `write_triage_state()`
  run over the SAME producer-generated `fleet-what-now.json` items the existing dashboard journey guards.
- `scripts/dontpanic_orchestrate/tests/test_cockpit_fixture_contract_f003.py` (3) — re-derives the model
  from the live producer (`build_triage`) and asserts the fixture matches (item set + F001 fields + schema
  + generated_at + no item_probe), so the fixture cannot silently drift from what the real build emits.

## Why this is the operator-outcome test (not artifact-completion)
Per the QA-sufficiency contract: this ENTERS the real surface (boots the shell + Cockpit page over real
producer state), guarded by a Python↔producer contract so the fixture can't pre-bake the asserted shape.
The full path (producer → fleet operator-triage.json → real shell → default Cockpit) is exercised end to end.

## Verification
- JS journey 3 passed; py fixture contract 3 passed; full dashboard vitest green.
