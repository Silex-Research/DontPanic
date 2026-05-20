# F003 implementation notes — Cloud Functions for dashboard mutations

Plan 2026-05-09-004 F003. Target env=dev, target_project=(none) — code-only, no
real `firebase deploy` per parent_acceptance_item / D007.

## What landed

- `dashboard/functions/index.js` — v2 callables `kanbanMoveCallable`,
  `approveGateCallable`, `triggerDispatchCallable`, each wrapped with
  `onCall` and HTTPS-error translation.
- `dashboard/functions/lib/mcp-bridge.js` — JSON-RPC 2.0 `tools/call`
  client over the operator-side tunnel URL. Bearer-token auth.
  Enforces `confirm:true` for every mutation (D003).
- `dashboard/functions/lib/auth.js` — Operator / Observer role resolver.
  Allowlist via `DONTPANIC_OPERATOR_UIDS`, custom-claim fallback.
- `dashboard/functions/lib/column-mapping.js` — Kanban column →
  `set_plan_status` mapping with a v0 supported-transition allowlist;
  unsupported drops fail closed.
- `dashboard/functions/lib/callables.js` — Dependency-injected handlers
  exercised end-to-end by the smoke test.
- `dashboard/functions/RUNBOOK.md` — Tailscale Funnel walkthrough +
  alternative bridges + deploy procedure (operator-gated).
- `firebase.json` — `functions` block added pointing at the new source
  (`codebase: dashboard-mutations`, nodejs20).
- `dashboard/vitest.config.js` — include glob extended to pick up the
  `functions/tests/**` shard.

## Acceptance evidence

1. **Three callables defined + callable.** `index.js` exports
   `kanbanMoveCallable`, `approveGateCallable`, `triggerDispatchCallable`.
   `firebase.json` declares the source so `firebase deploy --only
   functions` will pick them up. Deploy itself is deferred — see RUNBOOK.
2. **MCP-only mutations.** Every callable routes through
   `createMcpBridge().call(toolName, args)`. The bridge boundary enforces
   `confirm: true`; nowhere in the call graph does any function touch
   Firestore directly. Test `mcp-bridge.test.js` "refuses to send
   mutations without confirm:true at the bridge boundary" guards this.
3. **Auth required.** `requireOperator()` rejects unauthenticated context
   with `unauthenticated` and observer role with `permission-denied`.
   Tests `auth.test.js` + `callables.test.js` exercise both paths.
4. **Smoke test against fixture plan.** `callables.test.js` invokes each
   of the three callables against a fake bridge and asserts the exact
   `(tool, arguments)` tuple posted, plus the response envelope handed
   back to the dashboard. End-to-end run against a real `<firebase-project-id>`
   project is the F005 deliverable per the plan's deferral matrix.

## Verification log

`F003-callables-tests.log` — `vitest run functions/tests/` output, 4 files
/ 39 tests passing in ~500ms. Full dashboard suite (`vitest run`) reports
395/395 passing — no regression of the F001 adapter or F002 sync-daemon
test surfaces.

## Commands run

  $ node_modules/.bin/vitest run functions/tests/
  $ node_modules/.bin/vitest run
