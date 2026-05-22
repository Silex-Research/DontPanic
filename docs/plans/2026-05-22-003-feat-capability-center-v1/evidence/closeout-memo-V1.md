---
plan_id: 2026-05-22-003-feat-capability-center-v1
features: ["F001", "F002"]
closed_at: 2026-05-22T22:00:00Z
---

# V1 close-out — Capability Center static dashboard + read-only MCP projection

This memo summarises the V1 shipped surface and is the parent roadmap's
evidence anchor for promoting V1 to "implemented". Per-feature
close-outs live alongside it (`closeout-memo-F001.md`,
`closeout-memo-F002.md`).

## Shipped surface

### F001 — Static dashboard Capability Center (commit `16adf94`)

- New page module under `dashboard/pages/capabilities/` registered
  through the existing static dashboard router.
- Reads `dashboard/state/capabilities-status.json` when present and
  renders one card per capability with: status badge,
  `owner_boundary` chips, configured/missing lists, automatable next
  actions, human-required next actions with reason text, and pending
  probe advisories.
- Degrades to a useful empty state that points operators at
  `dontpanic capabilities status --format=json` when the JSON file is
  absent — no Firebase, Firestore, Cloud Functions, or external
  service required to render.
- Visually distinguishes the Firebase dashboard and Linear example
  manifests as setup/not-installed cases.

### F002 — Read-only MCP `capabilities.get_status` (commit `7facb7f`)

- New MCP tool registered in `scripts/dontpanic_orchestrate/mcp_server.py`
  that returns the same JSON envelope as
  `dontpanic capabilities status --format=json`.
- Supports optional `capability_id` (returns `unknown_capability` for
  unknown ids) and `profile` filtering, matching CLI semantics.
- Reuses the V0b status envelope schema — does not introduce a second
  shape.
- Read-only by construction: no setup/mutation surface, missing
  secret names only (never secret values) flow through the projection.

## Verification

- Local pytest sweeps on the writable dev host:
  - `test_capabilities_mcp_f002.py`, `test_f002_mcp_server.py`,
    `test_state_mcp_f005.py`: 116 passed.
  - `test_capabilities_status_cli_f002.py`,
    `test_capabilities_f001.py`: 28 passed.
- Dashboard target tests, full dashboard suite, and the
  `required-capabilities` Python test slice passed for F001 (see
  `closeout-memo-F001.md`).
- Plan validation passed for
  `2026-05-22-003-feat-capability-center-v1`.
- Sanitization clean (1631 files scanned).

## Operator review of the visual surface

The operator reviewed the static dashboard Capability Center rendering
before clearing the `pre_merge` gate on F001 (INBOX entry
`2026-05-22T21:03:13Z gate_cleared: pre_merge`). F003 only flips after
both F001 and F002 reach `passes:true` (already true in
`features.json`) and after that visual review.

## Boundary preserved

V2 (`docs/plans/2026-05-22-004-feat-capability-guided-setup-v2/`)
remains a separate child plan. V1 deliberately ships only:

- a visual, read-only static dashboard surface, and
- a read-only MCP projection.

Guided setup, mutation execution, and confirm-gated automation stay
out of scope for V1 and are not silently folded in here.

## Evidence references

- `evidence/closeout-memo-F001.md`
- `evidence/closeout-memo-F002.md`
- Commits: `16adf94` (F001), `3752dc2` (F001 close-out),
  `7facb7f` (F002), `032ee63` (F002 close-out).
- Parent roadmap D-entry: `D012` in
  `docs/plans/2026-05-22-001-infra-external-capability-operations-roadmap-v0/decisions.jsonl`.
