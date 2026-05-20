# Dashboard Cloud Functions — operator runbook

Plan 2026-05-09-004 F003. Three callables wrap the dashboard's mutation
surface and route every state change through the operator's locally-running
DontPanic MCP server. Direct Firestore writes for state-changing actions are
denied by the Firestore rules (F004); only the sync daemon (F002) writes the
projection, only Cloud Functions issue MCP mutations.

> **Deploy status:** code-only in this plan. Per parent_acceptance_item /
> plan D007, the actual `firebase deploy --only functions` step is deferred
> until the operator has the `<your-project-id>` service-account key wired up
> and the Tailscale Funnel target running. The smoke tests in
> `functions/tests/` exercise every callable against a stubbed MCP bridge
> so the code is verified locally before the credential gate clears.

---

## 1. Architecture

```
┌────────────┐  onCall  ┌──────────────┐  HTTPS  ┌──────────────────────┐  stdio  ┌────────┐
│  Browser   │ ───────▶ │ Cloud Funcs  │ ──────▶ │ operator HTTP↔stdio  │ ──────▶ │  MCP   │
│ (dashboard)│          │ kanbanMove…  │ bearer  │ bridge  (this repo)  │  pipe   │ subproc│
└────────────┘          └──────────────┘         └──────────────────────┘         └────────┘
                                │
                                │ Firebase Auth + Operator role
                                ▼
                         role allowlist
                       (env DONTPANIC_OPERATOR_UIDS)
```

The Cloud Function side runs in `us-central1` and only knows the public
tunnel URL + bearer token. The operator side runs a small Python HTTP
server, `scripts/firebase_adapter/mcp_http_bridge.py`, that owns a
long-lived `dontpanic mcp serve` subprocess and proxies JSON-RPC traffic
across it.

This indirection is necessary because `dontpanic mcp serve` is stdio-only
by design (plan 2026-05-03-003 D003 — `--bind`/`--host`/`--port` are
explicitly refused). The bridge is the only adapter-side process that
talks to MCP; the Tailscale Funnel / Cloudflare Tunnel / ngrok front-end
points at the bridge's loopback port. The Cloud Function POSTs JSON-RPC
2.0 `tools/call` payloads at the tunnel; the bridge forwards them as
single-line stdin writes and returns the subprocess's single-line stdout
response.

## 2. Required configuration

Env vars (set via `firebase functions:config:set` or the v2 parameterized
`firebase functions:secrets` workflow):

| Name | Type | Purpose |
| --- | --- | --- |
| `MCP_TUNNEL_URL` | string | HTTPS endpoint at which `dontpanic mcp serve` is reachable (e.g. `https://dontpanic.<your-ts-name>.ts.net/mcp`). |
| `MCP_TUNNEL_TOKEN` | secret | Bearer token; must match the value enforced by the tunnel front-end. |
| `DONTPANIC_OPERATOR_UIDS` | string | Semicolon-separated Firebase Auth UIDs allowed to fire mutations. Empty → no one (callables will all reject with `permission-denied`). |

Custom claims also work — set `dontpanic_role=operator` on the user's ID
token if you prefer managing roles via the Firebase admin SDK instead of an
env allowlist.

## 3. Recommended bridge: Tailscale Funnel

The operator stack is two processes:

1. **`dontpanic mcp serve`** — speaks JSON-RPC 2.0 over stdio, started
   *by the bridge* (not directly). DontPanic core stays stdio-only per
   plan 2026-05-03-003 D003; the bridge owns the subprocess.
2. **`scripts/firebase_adapter/mcp_http_bridge.py`** — listens on a
   loopback port, enforces `Authorization: Bearer …`, and forwards
   `tools/call` payloads to the subprocess.

Setup:

```bash
# 1. Install Tailscale + sign in with the operator account.
$ brew install tailscale && sudo tailscale up

# 2. Start the bridge. It auto-spawns `dontpanic mcp serve` as a
#    subprocess and shares the bearer token with the Cloud Function
#    side via the MCP_TUNNEL_TOKEN env var.
$ export DONTPANIC_MCP_TUNNEL_TOKEN="$(openssl rand -hex 32)"
$ python -m firebase_adapter.mcp_http_bridge serve \
      --bind 127.0.0.1:8765 \
      --token-env DONTPANIC_MCP_TUNNEL_TOKEN

# 3. Expose port 8765 via Tailscale Funnel.
$ tailscale funnel --bg --set-path /mcp 8765

# 4. Copy the printed `https://<name>.ts.net/mcp` URL into
#    MCP_TUNNEL_URL (Cloud Function side) and the same token into
#    MCP_TUNNEL_TOKEN (firebase functions:secrets:set).
```

### Alternatives

- **Cloudflare Tunnel**: `cloudflared tunnel --url http://localhost:8765`
  → use the printed `trycloudflare.com` URL (or a named tunnel under your
  Cloudflare zone).
- **ngrok** (paid required for static URLs):
  `ngrok http 8765` then set `MCP_TUNNEL_URL` to the assigned URL.

All three are operator's choice (D005). The bearer token check happens
at the bridge layer regardless of which tunnel front-end you pick.

### Bridge security surface

- The HTTP listener binds to `127.0.0.1` by default. Only loopback +
  the tunnel front-end can reach it.
- Only three JSON-RPC methods are accepted: `initialize`, `tools/list`,
  `tools/call`. Anything else (e.g. `shutdown`, `filesystem/*`) is refused
  with HTTP 403 before the subprocess sees the bytes.
- The MCP subprocess inherits the bridge's working directory. Run the
  bridge from inside the DontPanic repo (or pass `--mcp-command` with a
  fully-qualified path) so the projects-registry lookup works.

## 4. Deploy (operator-gated)

```bash
$ cd dashboard/functions && npm install                   # one-time
$ firebase functions:secrets:set MCP_TUNNEL_TOKEN          # paste token
$ firebase deploy --project <your-project-id> --only functions
```

Do not run this from CI in the current OSS layout — secrets need a manual
paste, and the operator is the only party that owns the tunnel.

## 5. Smoke test (post-deploy)

```bash
# 1. Tail Cloud Function logs in one terminal.
$ firebase functions:log --project <your-project-id> --only kanbanMoveCallable

# 2. Open the realtime dashboard and drag a fixture-plan card in Mission
#    Control from "todo" → "in_progress".

# 3. Watch logs for the bridge call:
#    tunnel POST https://...ts.net/mcp → 200 → tools/call dispatch
#
#    (kanban drag is restricted to todo → in_progress in v0 — that's
#    the only transition that maps onto an existing MCP tool. Other
#    column moves are rejected by column-mapping.js with
#    `transition-not-supported-v0`. For arbitrary status flips use the
#    modal's Dispatch/Approve buttons or the CLI.)
#
# 4. Confirm the local MCP server received the tools/call by tailing its
#    own stderr (the bridge forwards subprocess stderr to its own stderr).

# 5. The F002 sync daemon should reflect the new plan status back into
#    Firestore within ~10s, at which point the dashboard re-renders the
#    card under its new column.
```

The full end-to-end happy path (acceptance #4) is documented in plan F005;
this runbook only covers the F003 surface.

## 6. Test the code without deploying

```bash
$ cd dashboard
$ npm install
$ npx vitest run --config vitest.config.js functions/tests
```

The vitest suite covers:

- `mcp-bridge.test.js` — payload shape, lazy secret/config materialization,
  bearer auth, MCP-side error surfacing, network/timeout handling.
- `auth.test.js` — unauthenticated / observer / operator role resolution
  (allowlist + custom claim paths).
- `column-mapping.test.js` — supported/unsupported kanban transitions,
  status mapping, defensive input validation.
- `callables.test.js` — end-to-end harness for `kanbanMove`,
  `approveGate`, `triggerDispatch` against a fake bridge. Asserts that
  every callable issues the right MCP tool with `confirm: true` (D003)
  and rejects unauthenticated/observer callers (acceptance #3).
