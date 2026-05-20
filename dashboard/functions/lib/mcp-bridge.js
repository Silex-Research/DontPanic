// ── DontPanic MCP bridge — Cloud-Function-side ──
// Plan 2026-05-09-004 F003. Translates a typed mutation request into a
// JSON-RPC 2.0 `tools/call` against the operator's locally-running
// DontPanic MCP server, exposed over a Tailscale Funnel / Cloudflare Tunnel /
// ngrok URL with a static bearer token (D003 — mutations ALWAYS go through
// MCP, never direct Firestore writes; D005 — operator picks the tunnel).
//
// The bridge is dependency-injected (`fetchImpl`) so tests run without a real
// HTTP stack. Production wires `globalThis.fetch` — Node 18+ ships it natively.
//
// Mutating MCP tools require `confirm: true` per the dontpanic mcp_server
// contract (D003). The bridge enforces that for every call — callers cannot
// dry-run a mutation through this surface.

const MCP_RPC_VERSION = '2.0';
const DEFAULT_TIMEOUT_MS = 20000;

export class McpBridgeError extends Error {
  constructor(code, message, details = null) {
    super(message);
    this.name = 'McpBridgeError';
    this.code = code;
    this.details = details;
  }
}

export function buildToolsCallPayload({ id, tool, args }) {
  if (typeof tool !== 'string' || tool.length === 0) {
    throw new McpBridgeError('invalid-tool', 'tool must be a non-empty string');
  }
  if (args == null || typeof args !== 'object') {
    throw new McpBridgeError('invalid-args', 'args must be an object');
  }
  if (args.confirm !== true) {
    throw new McpBridgeError(
      'confirm-required',
      `MCP tool ${tool} requires confirm:true for mutation`,
    );
  }
  return {
    jsonrpc: MCP_RPC_VERSION,
    id,
    method: 'tools/call',
    params: { name: tool, arguments: args },
  };
}

export function createMcpBridge({
  tunnelUrl,
  tunnelToken,
  fetchImpl,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  idFactory = defaultIdFactory,
} = {}) {
  if (!tunnelUrl) {
    throw new McpBridgeError('config-missing', 'MCP tunnel URL is not configured');
  }
  if (!tunnelToken) {
    throw new McpBridgeError('config-missing', 'MCP tunnel auth token is not configured');
  }
  const doFetch = fetchImpl || (typeof fetch === 'function' ? fetch : null);
  if (!doFetch) {
    throw new McpBridgeError('config-missing', 'no fetch implementation available');
  }

  return {
    async call(tool, args) {
      const id = idFactory();
      const payload = buildToolsCallPayload({ id, tool, args });
      const controller = createAbortController(timeoutMs);
      let response;
      try {
        response = await doFetch(tunnelUrl, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            authorization: `Bearer ${tunnelToken}`,
            'x-dontpanic-rpc-id': String(id),
          },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
      } catch (err) {
        throw new McpBridgeError(
          err && err.name === 'AbortError' ? 'tunnel-timeout' : 'tunnel-unreachable',
          `MCP tunnel fetch failed: ${err && err.message ? err.message : err}`,
          { tool, id },
        );
      } finally {
        controller.clear();
      }

      if (!response.ok) {
        throw new McpBridgeError(
          'tunnel-http-error',
          `MCP tunnel returned HTTP ${response.status}`,
          { tool, id, status: response.status },
        );
      }

      let body;
      try {
        body = await response.json();
      } catch (err) {
        throw new McpBridgeError(
          'tunnel-bad-json',
          `MCP tunnel returned malformed JSON: ${err && err.message ? err.message : err}`,
          { tool, id },
        );
      }
      if (body && body.error) {
        throw new McpBridgeError(
          'mcp-error',
          body.error.message || 'MCP returned an error',
          { tool, id, mcp: body.error },
        );
      }
      if (!body || body.result === undefined) {
        throw new McpBridgeError(
          'tunnel-bad-envelope',
          'MCP tunnel response missing result field',
          { tool, id },
        );
      }
      return body.result;
    },
  };
}

export function createLazyMcpBridge({ configFactory } = {}) {
  if (typeof configFactory !== 'function') {
    throw new McpBridgeError(
      'config-missing',
      'lazy MCP bridge requires a configFactory',
    );
  }
  let bridge = null;
  return {
    async call(tool, args) {
      if (!bridge) {
        bridge = createMcpBridge(configFactory());
      }
      return bridge.call(tool, args);
    },
  };
}

function defaultIdFactory() {
  return `df-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
}

function createAbortController(timeoutMs) {
  if (typeof AbortController === 'undefined') {
    return { signal: undefined, clear() {} };
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  return {
    signal: ctrl.signal,
    clear() { clearTimeout(timer); },
  };
}
