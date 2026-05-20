// ── Dashboard realtime mutation actions ──
// Plan 2026-05-09-004 F003 audit-i1. Pure, dependency-injected wrappers
// around the three Cloud Functions callables exposed by
// `dashboard/functions/`: kanbanMoveCallable, approveGateCallable,
// triggerDispatchCallable.
//
// The browser side of the dashboard never writes to Firestore for
// state-changing actions (D003 — MCP is the only mutation surface).
// Every drag-flip / approve / dispatch click goes through these wrappers
// → httpsCallable → Cloud Function → operator-side MCP bridge.
//
// Design notes:
//
//  - `callableFactory` is injected so this module is unit-testable without
//    the Firebase SDK. In production (`config-firebase.js`) it's wired to
//    `httpsCallable(getFunctions(app), name)`.
//  - Every action returns `{ ok: true, data }` on success or
//    `{ ok: false, code, message }` on failure. The dashboard surfaces
//    `code`/`message` directly; we never throw across this boundary, so
//    drag-handlers in mission-control.js stay simple.

export const CALLABLE_NAMES = Object.freeze({
  kanbanMove: 'kanbanMoveCallable',
  approveGate: 'approveGateCallable',
  triggerDispatch: 'triggerDispatchCallable',
});

function normalizeError(err) {
  // Firebase HttpsCallableResult errors carry .code / .message / .details.
  // Network or transport errors land here as raw Error instances.
  return {
    ok: false,
    code: err && err.code ? String(err.code) : 'internal',
    message: err && err.message ? String(err.message) : 'mutation failed',
    details: err && err.details ? err.details : null,
  };
}

function asNonEmpty(value, field) {
  if (typeof value !== 'string' || value.length === 0) {
    const err = new Error(`${field} must be a non-empty string`);
    err.code = 'invalid-argument';
    throw err;
  }
  return value;
}

export function createRealtimeActions({ callableFactory } = {}) {
  if (typeof callableFactory !== 'function') {
    throw new Error('createRealtimeActions: callableFactory is required');
  }
  const kanbanMoveCallable = callableFactory(CALLABLE_NAMES.kanbanMove);
  const approveGateCallable = callableFactory(CALLABLE_NAMES.approveGate);
  const triggerDispatchCallable = callableFactory(CALLABLE_NAMES.triggerDispatch);

  async function safeInvoke(callable, args) {
    try {
      const result = await callable(args);
      // httpsCallable wraps the function's return under `.data`.
      // Tests inject either {data:...} or the raw payload — accept both.
      const payload = result && typeof result === 'object' && 'data' in result
        ? result.data
        : result;
      return { ok: true, data: payload };
    } catch (err) {
      return normalizeError(err);
    }
  }

  return {
    async kanbanMove({ planId, currentColumn, newColumn, featureId }) {
      try {
        asNonEmpty(planId, 'planId');
        asNonEmpty(currentColumn, 'currentColumn');
        asNonEmpty(newColumn, 'newColumn');
      } catch (err) {
        return normalizeError(err);
      }
      const args = { planId, currentColumn, newColumn };
      if (featureId) args.featureId = featureId;
      return safeInvoke(kanbanMoveCallable, args);
    },

    async approveGate({ planId, gateName }) {
      try {
        asNonEmpty(planId, 'planId');
        asNonEmpty(gateName, 'gateName');
      } catch (err) {
        return normalizeError(err);
      }
      return safeInvoke(approveGateCallable, { planId, gateName });
    },

    async triggerDispatch({ planId, featureId }) {
      try {
        asNonEmpty(planId, 'planId');
        asNonEmpty(featureId, 'featureId');
      } catch (err) {
        return normalizeError(err);
      }
      return safeInvoke(triggerDispatchCallable, { planId, featureId });
    },
  };
}

// Default httpsCallable adapter for the Firebase Web SDK. Operators wire
// this via `attachRealtimeActions({ jarvis, app })` in config-firebase.js;
// tests inject their own.
export async function defaultCallableFactory({ functionsLoader, app, region = 'us-central1' }) {
  const mod = functionsLoader
    ? await functionsLoader()
    : await import('https://www.gstatic.com/firebasejs/10.14.0/firebase-functions.js');
  const functions = mod.getFunctions(app, region);
  return (name) => {
    const callable = mod.httpsCallable(functions, name);
    return async (data) => callable(data);
  };
}
