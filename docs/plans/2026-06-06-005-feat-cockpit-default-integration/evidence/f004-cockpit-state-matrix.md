# F004 — Cockpit state matrix

## What shipped
- `dashboard/lib/cockpit-state.js` — pure `classifyCockpitState({model,loading,errored,now})` → one of
  `loading | error | missing | stale | ready`, with deliberate precedence (loading needs no model;
  a failed load is error even over a lingering stale model; absence is missing; staleness demotes a
  present model). `STALE_AFTER_MS` aligned to freshness.js AGING_MAX (24h) so the classifier and the
  rendered `staleBanner` never disagree.
- `dashboard/pages/cockpit/cockpit-page.js` — rewritten as the 5-state machine: skeleton (loading),
  "run dashboard build" (missing), `staleBanner` OVER the demoted queue (stale), last-good UNDER an
  error banner + Retry (error), the queue (ready). Its own `refresh()` surfaces a failed fetch/parse
  as the error state over last-good — never a silent stale hold, never fake-fresh.
- `scripts/dontpanic_orchestrate/operator_triage.py` + `projects_dashboard.py` — `write_triage_state`
  gains an optional `generated_at`; the fleet build stamps it (`now_iso`) so the Cockpit has a real
  staleness reference. Added AFTER build_triage so it does NOT enter the content `state_revision`.
- `dashboard/components.css` — token-only surfaces for skeleton / stale banner / error banner + retry.

## Tests (Cockpit-only, per scope)
- `tests/unit/cockpit-state.test.js` (6): the pure classifier incl. precedence (error over stale).
- `tests/unit/cockpit-page.test.js` F004 block (4): loading→skeleton (never blank); stale→banner over
  a still-shown queue; error→last-good + error banner + retry; error→recover via Retry click.
- Live: real `dontpanic dashboard build` → fleet `operator-triage.json` carries `generated_at`
  (2026-06-07T22:46:01Z), `state_revision` unchanged (content-only).
- Full dashboard vitest 1149 passed; py regression 253 passed.
