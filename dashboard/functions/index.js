// ── DontPanic dashboard Cloud Functions — entry point ──
// Plan 2026-05-09-004 F003. Three v2 callables wrap dashboard mutations:
//   kanbanMove(planId, newColumn[, currentColumn]) → MCP set_plan_status
//   approveGate(planId, gateName)                  → MCP approve_gate
//   triggerDispatch(planId, featureId)             → MCP dispatch
//
// All three require Firebase Auth + the DontPanic Operator role (D003).
// Mutations always flow through the MCP tunnel (D005); this module never
// writes Firestore directly — that path is intentionally rejected by
// firestore.rules (F004). The sync daemon (F002) reflects the resulting
// state change back into Firestore for the dashboard to re-render.
//
// Deployment is operator-gated per parent_acceptance_item / D007 — the
// firebase deploy step lives in the operator's RUNBOOK (see ./RUNBOOK.md).

import { onCall, HttpsError } from 'firebase-functions/v2/https';
import { defineSecret, defineString } from 'firebase-functions/params';
import { setGlobalOptions } from 'firebase-functions/v2';

import { createLazyMcpBridge, McpBridgeError } from './lib/mcp-bridge.js';
import { parseOperatorAllowlist } from './lib/auth.js';
import {
  kanbanMove,
  approveGate,
  triggerDispatch,
  CallableError,
} from './lib/callables.js';

// Region pinned to us-central1 to match firebase.json hosting + Firestore
// defaults; override via `firebase deploy --only functions:<name>` and
// `setGlobalOptions` if the operator runs in another region.
setGlobalOptions({ region: 'us-central1', maxInstances: 5 });

const MCP_TUNNEL_URL = defineString('MCP_TUNNEL_URL', {
  description:
    'HTTPS URL of the operator-side MCP bridge (Tailscale Funnel / Cloudflare Tunnel / ngrok).',
});
const MCP_TUNNEL_TOKEN = defineSecret('MCP_TUNNEL_TOKEN');
const OPERATOR_UIDS = defineString('DONTPANIC_OPERATOR_UIDS', {
  description:
    'Semicolon-separated Firebase Auth UIDs allowed to fire state-changing callables.',
  default: '',
});

function buildDeps() {
  return {
    bridge: createLazyMcpBridge({
      configFactory: () => ({
        tunnelUrl: MCP_TUNNEL_URL.value(),
        tunnelToken: MCP_TUNNEL_TOKEN.value(),
      }),
    }),
    operatorUids: parseOperatorAllowlist(OPERATOR_UIDS.value()),
  };
}

function toHttpsError(err) {
  if (err instanceof CallableError) {
    return new HttpsError(mapErrorCode(err.code), err.message, err.details);
  }
  if (err instanceof McpBridgeError) {
    return new HttpsError('unavailable', err.message, {
      bridgeCode: err.code,
      ...(err.details || {}),
    });
  }
  return new HttpsError('internal', err && err.message ? err.message : 'internal error');
}

function mapErrorCode(code) {
  switch (code) {
    case 'unauthenticated':
      return 'unauthenticated';
    case 'permission-denied':
      return 'permission-denied';
    case 'invalid-argument':
    case 'invalid-plan-id':
    case 'invalid-column':
    case 'invalid-current-column':
    case 'current-column-required':
    case 'no-op':
    case 'transition-not-supported-v0':
      return 'invalid-argument';
    case 'mcp-bridge-failure':
      return 'unavailable';
    default:
      return 'internal';
  }
}

function wrapCallable(handler) {
  return async (request) => {
    const deps = buildDeps();
    try {
      return await handler({
        data: request.data || {},
        context: { auth: request.auth || null },
        deps,
      });
    } catch (err) {
      throw toHttpsError(err);
    }
  };
}

export const kanbanMoveCallable = onCall(
  { secrets: [MCP_TUNNEL_TOKEN] },
  wrapCallable(kanbanMove),
);

export const approveGateCallable = onCall(
  { secrets: [MCP_TUNNEL_TOKEN] },
  wrapCallable(approveGate),
);

export const triggerDispatchCallable = onCall(
  { secrets: [MCP_TUNNEL_TOKEN] },
  wrapCallable(triggerDispatch),
);
