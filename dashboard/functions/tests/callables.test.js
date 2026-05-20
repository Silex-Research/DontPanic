// Plan 2026-05-09-004 F003 — callables smoke tests.
//
// End-to-end harness for the three dashboard mutation callables. The MCP
// bridge is replaced by a fake that records every call, satisfying
// acceptance #2 (each function calls DontPanic MCP — no direct Firestore
// writes) and acceptance #4 (smoke test verifies the MCP tool was invoked).

import { describe, it, expect, vi } from 'vitest';
import {
  kanbanMove,
  approveGate,
  triggerDispatch,
  CallableError,
} from '../lib/callables.js';

function fakeBridge(stubResults = {}) {
  const calls = [];
  return {
    calls,
    async call(tool, args) {
      calls.push({ tool, args });
      if (stubResults[tool] instanceof Error) throw stubResults[tool];
      return stubResults[tool] || { ok: true };
    },
  };
}

function ctx(uid) {
  return { auth: uid ? { uid } : null };
}

const OPERATOR_UIDS = new Set(['uid-operator']);

describe('approveGate', () => {
  it('rejects unauthenticated calls', async () => {
    const bridge = fakeBridge();
    await expect(
      approveGate({
        data: { planId: 'p', gateName: 'pre_merge' },
        context: ctx(null),
        deps: { bridge, operatorUids: OPERATOR_UIDS },
      }),
    ).rejects.toMatchObject({ code: 'unauthenticated' });
    expect(bridge.calls).toEqual([]);
  });

  it('rejects observer (non-operator) UID', async () => {
    const bridge = fakeBridge();
    await expect(
      approveGate({
        data: { planId: 'p', gateName: 'pre_merge' },
        context: ctx('uid-observer'),
        deps: { bridge, operatorUids: OPERATOR_UIDS },
      }),
    ).rejects.toMatchObject({ code: 'permission-denied' });
    expect(bridge.calls).toEqual([]);
  });

  it('calls MCP approve_gate with confirm:true for operator', async () => {
    const bridge = fakeBridge({
      approve_gate: { cleared: true, gate: 'pre_merge' },
    });
    const res = await approveGate({
      data: { planId: 'plan-x', gateName: 'pre_merge' },
      context: ctx('uid-operator'),
      deps: { bridge, operatorUids: OPERATOR_UIDS },
    });
    expect(bridge.calls).toEqual([
      {
        tool: 'approve_gate',
        args: { plan: 'plan-x', gate: 'pre_merge', confirm: true },
      },
    ]);
    expect(res.tool).toBe('approve_gate');
    expect(res.plan).toBe('plan-x');
    expect(res.gate).toBe('pre_merge');
    expect(res.result.cleared).toBe(true);
  });

  it('rejects missing planId', async () => {
    const bridge = fakeBridge();
    await expect(
      approveGate({
        data: { gateName: 'pre_merge' },
        context: ctx('uid-operator'),
        deps: { bridge, operatorUids: OPERATOR_UIDS },
      }),
    ).rejects.toMatchObject({ code: 'invalid-argument' });
  });
});

describe('triggerDispatch', () => {
  it('calls MCP dispatch with confirm:true and feature id', async () => {
    const bridge = fakeBridge({
      dispatch: { volley_id: 'v1' },
    });
    const res = await triggerDispatch({
      data: { planId: 'plan-x', featureId: 'F001' },
      context: ctx('uid-operator'),
      deps: { bridge, operatorUids: OPERATOR_UIDS },
    });
    expect(bridge.calls).toEqual([
      {
        tool: 'dispatch',
        args: { plan: 'plan-x', feature: 'F001', confirm: true },
      },
    ]);
    expect(res.feature).toBe('F001');
    expect(res.result.volley_id).toBe('v1');
  });

  it('surfaces bridge errors as mcp-bridge-failure CallableError', async () => {
    class FakeBridgeError extends Error {
      constructor() {
        super('upstream MCP refused');
        this.name = 'McpBridgeError';
        this.code = 'mcp-error';
        this.details = { tool: 'dispatch' };
      }
    }
    // Import the real bridge error class so instanceof check inside the
    // callable identifies the failure category.
    const { McpBridgeError } = await import('../lib/mcp-bridge.js');
    const realErr = new McpBridgeError('mcp-error', 'upstream MCP refused', {});
    const bridge = {
      calls: [],
      async call(tool) {
        this.calls.push(tool);
        throw realErr;
      },
    };
    void FakeBridgeError; // silence linter on the placeholder class
    await expect(
      triggerDispatch({
        data: { planId: 'p', featureId: 'F001' },
        context: ctx('uid-operator'),
        deps: { bridge, operatorUids: OPERATOR_UIDS },
      }),
    ).rejects.toMatchObject({
      code: 'mcp-bridge-failure',
      details: { bridgeCode: 'mcp-error' },
    });
  });
});

describe('kanbanMove', () => {
  it('calls MCP dispatch for the only supported v0 transition (todo → in_progress)', async () => {
    const bridge = fakeBridge({
      dispatch: { volley_id: 'v-from-drag', dry_run: false },
    });
    const res = await kanbanMove({
      data: {
        planId: 'plan-x',
        currentColumn: 'todo',
        newColumn: 'in_progress',
      },
      context: ctx('uid-operator'),
      deps: { bridge, operatorUids: OPERATOR_UIDS },
    });
    expect(bridge.calls).toEqual([
      {
        tool: 'dispatch',
        args: { plan: 'plan-x', feature: 'F001', confirm: true },
      },
    ]);
    expect(res.column).toBe('in_progress');
    expect(res.tool).toBe('dispatch');
    expect(res.result.volley_id).toBe('v-from-drag');
  });

  it('threads explicit featureId through to dispatch', async () => {
    const bridge = fakeBridge({ dispatch: { ok: true } });
    await kanbanMove({
      data: {
        planId: 'plan-x',
        currentColumn: 'todo',
        newColumn: 'in_progress',
        featureId: 'F007',
      },
      context: ctx('uid-operator'),
      deps: { bridge, operatorUids: OPERATOR_UIDS },
    });
    expect(bridge.calls[0].args.feature).toBe('F007');
  });

  it('rejects unsupported transitions before reaching MCP', async () => {
    const bridge = fakeBridge();
    await expect(
      kanbanMove({
        data: { planId: 'p', currentColumn: 'review', newColumn: 'done' },
        context: ctx('uid-operator'),
        deps: { bridge, operatorUids: OPERATOR_UIDS },
      }),
    ).rejects.toMatchObject({ code: 'transition-not-supported-v0' });
    expect(bridge.calls).toEqual([]);
  });

  it('rejects unauthenticated kanban moves', async () => {
    const bridge = fakeBridge();
    await expect(
      kanbanMove({
        data: { planId: 'p', currentColumn: 'todo', newColumn: 'in_progress' },
        context: ctx(null),
        deps: { bridge, operatorUids: OPERATOR_UIDS },
      }),
    ).rejects.toMatchObject({ code: 'unauthenticated' });
    expect(bridge.calls).toEqual([]);
  });

  it('rejects missing currentColumn — UI must declare source column', async () => {
    const bridge = fakeBridge();
    await expect(
      kanbanMove({
        data: { planId: 'p', newColumn: 'in_progress' },
        context: ctx('uid-operator'),
        deps: { bridge, operatorUids: OPERATOR_UIDS },
      }),
    ).rejects.toMatchObject({ code: 'invalid-argument' });
    expect(bridge.calls).toEqual([]);
  });
});

describe('CallableError type guard', () => {
  it('is what handlers throw on input/auth failure', async () => {
    const bridge = fakeBridge();
    try {
      await approveGate({
        data: {},
        context: ctx('uid-operator'),
        deps: { bridge, operatorUids: OPERATOR_UIDS },
      });
      throw new Error('expected throw');
    } catch (err) {
      expect(err).toBeInstanceOf(CallableError);
      expect(err.code).toBe('invalid-argument');
    }
  });
});
