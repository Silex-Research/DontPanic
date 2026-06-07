# F001 — build/state contract (fleet operator-triage emission)

## Finding
With multiple projects registered, `dontpanic dashboard build` defaults to fleet
("All Projects") mode, which emitted only `fleet-what-now.json` — **no fleet-level
`operator-triage.json`**. The triage-write block in `dashboard.build()` (single-project
path) was best-effort with a swallowed failure (`dashboard.py:891`) and never ran in fleet
mode. So the DEFAULT Cockpit (the All-Projects surface F002 mounts) had no operator-triage/v0
model to read. Per-project builds already emitted per-project triage with the new fields.

## Fix
1. `projects_dashboard.build_fleet_what_now` now writes a sibling fleet `operator-triage.json`
   (`FLEET_TRIAGE_FILENAME`) from the SAME `payload["items"]` via `write_triage_state(...,
   dedupe=False)` — REQUIRED (propagates failures), not swallowed (explicit failure mode).
2. `mirror_selection_into_state_dir` mirrors the fleet `operator-triage.json` into the served
   `state/` tree so serve returns the freshly-built model (serve-path pinned).
3. Architecture levels stay OUT of build (cache-only / deferred to plan 007) — no tracked repo
   working tree is modified by F001.

## Live proof (real `dontpanic dashboard build`)
- fleet `~/.dontpanic/dashboard/operator-triage.json`: schema=`operator-triage/v0`, **308 items**,
  ALL carry `resolution` + `asserted_at` + `freshness_basis` + `provenance_source`, `state_revision` present.

## Tests (real-surface, GENERATED file not fixtures)
- `test_fleet_triage_contract_f001.py` (4): fleet build emits sibling triage v0; generated items carry the
  4 fields; triage item-set == fleet-what-now item-set (one model, many renderers); mirror copies into served state/.
- Regression: 263 passed (projects_dashboard + operator_triage + dashboard + mirror), 0 failures.
