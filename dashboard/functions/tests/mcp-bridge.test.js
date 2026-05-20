// Plan 2026-05-09-004 F003 — MCP bridge unit tests.
//
// Verifies the bridge builds a well-formed JSON-RPC `tools/call` envelope,
// enforces `confirm:true` for mutations (D003), and surfaces structured
// errors instead of leaking raw fetch exceptions.

import { describe, it, expect, vi } from 'vitest';
import {
  buildToolsCallPayload,
  createMcpBridge,
  createLazyMcpBridge,
  McpBridgeError,
} from '../lib/mcp-bridge.js';

function fakeFetchOk(result) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    async json() {
      return { jsonrpc: '2.0', id: 'fixed', result };
    },
  });
}

function fakeFetchHttp(status) {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    async json() {
      return {};
    },
  });
}

function fakeFetchRpcError(error) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    async json() {
      return { jsonrpc: '2.0', id: 'fixed', error };
    },
  });
}

describe('buildToolsCallPayload', () => {
  it('produces a JSON-RPC 2.0 tools/call envelope', () => {
    const payload = buildToolsCallPayload({
      id: 1,
      tool: 'approve_gate',
      args: { plan: 'p', gate: 'pre_merge', confirm: true },
    });
    expect(payload).toEqual({
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/call',
      params: {
        name: 'approve_gate',
        arguments: { plan: 'p', gate: 'pre_merge', confirm: true },
      },
    });
  });

  it('rejects mutations without confirm:true (D003)', () => {
    expect(() =>
      buildToolsCallPayload({ id: 1, tool: 'dispatch', args: { plan: 'p' } }),
    ).toThrowError(/confirm:true/);
  });

  it('rejects empty tool name', () => {
    expect(() =>
      buildToolsCallPayload({ id: 1, tool: '', args: { confirm: true } }),
    ).toThrowError(/non-empty/);
  });

  it('rejects null args', () => {
    expect(() =>
      buildToolsCallPayload({ id: 1, tool: 'dispatch', args: null }),
    ).toThrowError(/args must be an object/);
  });
});

describe('createMcpBridge', () => {
  it('refuses construction without tunnel URL', () => {
    expect(() =>
      createMcpBridge({ tunnelToken: 't', fetchImpl: vi.fn() }),
    ).toThrowError(McpBridgeError);
  });

  it('refuses construction without tunnel token', () => {
    expect(() =>
      createMcpBridge({ tunnelUrl: 'https://x', fetchImpl: vi.fn() }),
    ).toThrowError(McpBridgeError);
  });

  it('POSTs the tools/call payload with bearer auth + content-type', async () => {
    const fetchImpl = fakeFetchOk({ ok: true });
    const bridge = createMcpBridge({
      tunnelUrl: 'https://tunnel.local/mcp',
      tunnelToken: 'secret',
      fetchImpl,
      idFactory: () => 'fixed',
    });
    const result = await bridge.call('dispatch', {
      plan: 'p',
      feature: 'F001',
      confirm: true,
    });
    expect(result).toEqual({ ok: true });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('https://tunnel.local/mcp');
    expect(init.method).toBe('POST');
    expect(init.headers.authorization).toBe('Bearer secret');
    expect(init.headers['content-type']).toBe('application/json');
    expect(init.headers['x-dontpanic-rpc-id']).toBe('fixed');
    const body = JSON.parse(init.body);
    expect(body.method).toBe('tools/call');
    expect(body.params.name).toBe('dispatch');
    expect(body.params.arguments.confirm).toBe(true);
  });

  it('surfaces HTTP errors as tunnel-http-error', async () => {
    const bridge = createMcpBridge({
      tunnelUrl: 'https://tunnel.local/mcp',
      tunnelToken: 'secret',
      fetchImpl: fakeFetchHttp(502),
    });
    await expect(
      bridge.call('dispatch', { plan: 'p', feature: 'F001', confirm: true }),
    ).rejects.toMatchObject({
      name: 'McpBridgeError',
      code: 'tunnel-http-error',
    });
  });

  it('surfaces MCP-side errors as mcp-error with details', async () => {
    const bridge = createMcpBridge({
      tunnelUrl: 'https://tunnel.local/mcp',
      tunnelToken: 'secret',
      fetchImpl: fakeFetchRpcError({ code: -32602, message: 'bad plan' }),
    });
    await expect(
      bridge.call('dispatch', { plan: 'p', feature: 'F001', confirm: true }),
    ).rejects.toMatchObject({
      name: 'McpBridgeError',
      code: 'mcp-error',
      message: 'bad plan',
    });
  });

  it('surfaces network failures as tunnel-unreachable', async () => {
    const bridge = createMcpBridge({
      tunnelUrl: 'https://tunnel.local/mcp',
      tunnelToken: 'secret',
      fetchImpl: vi.fn().mockRejectedValue(new Error('ECONNREFUSED')),
    });
    await expect(
      bridge.call('dispatch', { plan: 'p', feature: 'F001', confirm: true }),
    ).rejects.toMatchObject({
      name: 'McpBridgeError',
      code: 'tunnel-unreachable',
    });
  });

  it('refuses to send mutations without confirm:true at the bridge boundary', async () => {
    const fetchImpl = vi.fn();
    const bridge = createMcpBridge({
      tunnelUrl: 'https://tunnel.local/mcp',
      tunnelToken: 'secret',
      fetchImpl,
    });
    await expect(
      bridge.call('dispatch', { plan: 'p', feature: 'F001' }),
    ).rejects.toMatchObject({ code: 'confirm-required' });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe('createLazyMcpBridge', () => {
  it('defers configFactory until the first MCP call', async () => {
    const fetchImpl = fakeFetchOk({ ok: true });
    const configFactory = vi.fn(() => ({
      tunnelUrl: 'https://tunnel.local/mcp',
      tunnelToken: 'secret',
      fetchImpl,
      idFactory: () => 'fixed',
    }));
    const bridge = createLazyMcpBridge({ configFactory });

    expect(configFactory).not.toHaveBeenCalled();

    await expect(
      bridge.call('dispatch', { plan: 'p', feature: 'F001', confirm: true }),
    ).resolves.toEqual({ ok: true });
    expect(configFactory).toHaveBeenCalledTimes(1);

    await bridge.call('dispatch', { plan: 'p', feature: 'F002', confirm: true });
    expect(configFactory).toHaveBeenCalledTimes(1);
  });
});
