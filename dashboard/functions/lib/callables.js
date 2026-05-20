// ── Dashboard mutation callables — pure, dependency-injected ──
// Plan 2026-05-09-004 F003. The three callables (kanbanMove, approveGate,
// triggerDispatch) translate dashboard UI actions into DontPanic MCP
// `tools/call` requests via the bridge. Auth + role gating happen before
// the bridge call (D003 — MCP is the ONLY mutation surface).
//
// Each callable is a plain async function taking `({data, context, deps})`
// — `deps` carries `bridge`, `operatorUids`. This lets the dashboard's
// vitest suite exercise the full handler path without firebase-functions,
// and lets index.js wrap each handler in onCall() at module load time.

import { requireOperator, AuthError } from './auth.js';
import { resolveKanbanMove, ColumnMappingError } from './column-mapping.js';
import { McpBridgeError } from './mcp-bridge.js';

export class CallableError extends Error {
  constructor(code, message, details = null) {
    super(message);
    this.name = 'CallableError';
    this.code = code;
    this.details = details;
  }
}

function asNonEmptyString(value, field) {
  if (typeof value !== 'string' || value.length === 0) {
    throw new CallableError('invalid-argument', `${field} must be a non-empty string`);
  }
  return value;
}

function wrapMcpCall(toolCall) {
  return (async () => {
    try {
      return await toolCall();
    } catch (err) {
      if (err instanceof McpBridgeError) {
        throw new CallableError('mcp-bridge-failure', err.message, {
          bridgeCode: err.code,
          ...(err.details || {}),
        });
      }
      throw err;
    }
  })();
}

function requireOperatorOrRethrow(context, operatorUids) {
  try {
    return requireOperator(context, operatorUids);
  } catch (err) {
    if (err instanceof AuthError) {
      throw new CallableError(err.code, err.message);
    }
    throw err;
  }
}

export async function kanbanMove({ data, context, deps }) {
  const { bridge, operatorUids } = deps;
  requireOperatorOrRethrow(context, operatorUids);
  const planId = asNonEmptyString(data && data.planId, 'planId');
  const newColumn = asNonEmptyString(data && data.newColumn, 'newColumn');
  const currentColumn = asNonEmptyString(
    data && data.currentColumn,
    'currentColumn',
  );
  const featureId = data && typeof data.featureId === 'string' && data.featureId.length > 0
    ? data.featureId
    : null;

  let resolved;
  try {
    resolved = resolveKanbanMove({ planId, currentColumn, newColumn, featureId });
  } catch (err) {
    if (err instanceof ColumnMappingError) {
      throw new CallableError(err.code, err.message, err.details);
    }
    throw err;
  }
  const mcpResult = await wrapMcpCall(() =>
    bridge.call(resolved.tool, resolved.arguments),
  );
  return {
    tool: resolved.tool,
    plan: planId,
    column: newColumn,
    result: mcpResult,
  };
}

export async function approveGate({ data, context, deps }) {
  const { bridge, operatorUids } = deps;
  requireOperatorOrRethrow(context, operatorUids);
  const planId = asNonEmptyString(data && data.planId, 'planId');
  const gateName = asNonEmptyString(data && data.gateName, 'gateName');

  const mcpResult = await wrapMcpCall(() =>
    bridge.call('approve_gate', {
      plan: planId,
      gate: gateName,
      confirm: true,
    }),
  );
  return {
    tool: 'approve_gate',
    plan: planId,
    gate: gateName,
    result: mcpResult,
  };
}

export async function triggerDispatch({ data, context, deps }) {
  const { bridge, operatorUids } = deps;
  requireOperatorOrRethrow(context, operatorUids);
  const planId = asNonEmptyString(data && data.planId, 'planId');
  const featureId = asNonEmptyString(data && data.featureId, 'featureId');

  const mcpResult = await wrapMcpCall(() =>
    bridge.call('dispatch', {
      plan: planId,
      feature: featureId,
      confirm: true,
    }),
  );
  return {
    tool: 'dispatch',
    plan: planId,
    feature: featureId,
    result: mcpResult,
  };
}
