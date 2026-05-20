// Plan 2026-05-09-004 F003 audit-i1 — realtime-actions unit tests.
//
// The realtime-actions module is the client-side wrapper that mission
// control / security pages call into. It hides httpsCallable behind a
// stable `{ ok, data | code, message }` envelope and validates input
// locally before paying for the round-trip.

import { describe, it, expect, vi } from 'vitest';
import { createRealtimeActions, CALLABLE_NAMES } from '../../lib/realtime-actions.js';

function makeFactory(stubs = {}) {
  const calls = {};
  const factory = (name) => {
    calls[name] = [];
    return async (data) => {
      calls[name].push(data);
      const stub = stubs[name];
      if (!stub) return { data: { ok: true, tool: name, echoed: data } };
      if (stub instanceof Error) throw stub;
      if (typeof stub === 'function') return await stub(data);
      return stub;
    };
  };
  return { factory, calls };
}

describe('createRealtimeActions', () => {
  it('exposes the three documented callable names', () => {
    expect(CALLABLE_NAMES.kanbanMove).toBe('kanbanMoveCallable');
    expect(CALLABLE_NAMES.approveGate).toBe('approveGateCallable');
    expect(CALLABLE_NAMES.triggerDispatch).toBe('triggerDispatchCallable');
  });

  it('throws if callableFactory is missing', () => {
    expect(() => createRealtimeActions({})).toThrow(/callableFactory is required/);
  });

  it('kanbanMove forwards plan/column args + returns ok envelope', async () => {
    const { factory, calls } = makeFactory({
      kanbanMoveCallable: { data: { tool: 'dispatch', plan: 'p', column: 'in_progress' } },
    });
    const actions = createRealtimeActions({ callableFactory: factory });
    const out = await actions.kanbanMove({
      planId: 'p',
      currentColumn: 'todo',
      newColumn: 'in_progress',
    });
    expect(out.ok).toBe(true);
    expect(out.data.tool).toBe('dispatch');
    expect(calls.kanbanMoveCallable).toEqual([
      { planId: 'p', currentColumn: 'todo', newColumn: 'in_progress' },
    ]);
  });

  it('kanbanMove rejects missing planId locally', async () => {
    const { factory, calls } = makeFactory();
    const actions = createRealtimeActions({ callableFactory: factory });
    const out = await actions.kanbanMove({ currentColumn: 'todo', newColumn: 'in_progress' });
    expect(out.ok).toBe(false);
    expect(out.code).toBe('invalid-argument');
    // No round-trip to the callable.
    expect(calls.kanbanMoveCallable).toEqual([]);
  });

  it('kanbanMove threads featureId through when provided', async () => {
    const { factory, calls } = makeFactory({
      kanbanMoveCallable: { data: { ok: true } },
    });
    const actions = createRealtimeActions({ callableFactory: factory });
    await actions.kanbanMove({
      planId: 'p', currentColumn: 'todo', newColumn: 'in_progress', featureId: 'F042',
    });
    expect(calls.kanbanMoveCallable[0].featureId).toBe('F042');
  });

  it('approveGate forwards plan + gateName', async () => {
    const { factory, calls } = makeFactory({
      approveGateCallable: { data: { cleared: true } },
    });
    const actions = createRealtimeActions({ callableFactory: factory });
    const out = await actions.approveGate({ planId: 'p', gateName: 'pre_merge' });
    expect(out.ok).toBe(true);
    expect(calls.approveGateCallable).toEqual([{ planId: 'p', gateName: 'pre_merge' }]);
  });

  it('triggerDispatch forwards plan + featureId', async () => {
    const { factory, calls } = makeFactory({
      triggerDispatchCallable: { data: { volley_id: 'v1' } },
    });
    const actions = createRealtimeActions({ callableFactory: factory });
    const out = await actions.triggerDispatch({ planId: 'p', featureId: 'F001' });
    expect(out.ok).toBe(true);
    expect(calls.triggerDispatchCallable).toEqual([{ planId: 'p', featureId: 'F001' }]);
  });

  it('normalizes thrown Firebase HttpsError shape into ok:false envelope', async () => {
    class FakeHttpsError extends Error {
      constructor() {
        super('permission denied');
        this.code = 'permission-denied';
        this.details = { reason: 'observer' };
      }
    }
    const { factory } = makeFactory({
      approveGateCallable: new FakeHttpsError(),
    });
    const actions = createRealtimeActions({ callableFactory: factory });
    const out = await actions.approveGate({ planId: 'p', gateName: 'g' });
    expect(out.ok).toBe(false);
    expect(out.code).toBe('permission-denied');
    expect(out.message).toBe('permission denied');
    expect(out.details.reason).toBe('observer');
  });
});
