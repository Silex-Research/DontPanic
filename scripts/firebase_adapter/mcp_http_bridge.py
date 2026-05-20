"""Plan 2026-05-09-004 F003 — operator-side HTTP ↔ stdio MCP bridge.

The Cloud Function side (`dashboard/functions/lib/mcp-bridge.js`) issues
JSON-RPC 2.0 ``tools/call`` requests over HTTPS. The DontPanic MCP server
(`scripts/dontpanic_orchestrate/mcp_server.py`) only speaks stdio — its
``serve`` command explicitly refuses ``--bind`` / ``--host`` / ``--port``
flags per the F002 phase-B local-only invariant.

This module bridges the two: a small HTTP server that

  - listens on a loopback port (defaults to ``127.0.0.1:8765``),
  - requires ``Authorization: Bearer <token>`` matching the bearer the
    operator paired with their tunnel front-end,
  - serializes JSON-RPC requests over a single long-lived
    ``dontpanic mcp serve`` subprocess (one line in → one line out),
  - returns the subprocess's JSON-RPC response as the HTTP response body.

The operator runs THIS module on their workstation and then points a
Tailscale Funnel / Cloudflare Tunnel / ngrok at the loopback port. The
``MCP_TUNNEL_URL`` configured on the Cloud Function side resolves to the
public tunnel URL; the bearer header is forwarded end-to-end. The bridge
does NOT touch DontPanic core — it shells out via the supported
``dontpanic mcp serve`` CLI per plan D001 (adapter only).

Only the ``tools/call``, ``tools/list``, and ``initialize`` JSON-RPC
methods are exposed. Anything else is refused at the HTTP layer.

Run::

    $ python -m firebase_adapter.mcp_http_bridge serve \\
        --bind 127.0.0.1:8765 \\
        --token-env DONTPANIC_MCP_TUNNEL_TOKEN

The bridge logs every accepted request to stderr (method + JSON-RPC id).
The MCP server's own stderr is forwarded transparently. Stdout is reserved
for the JSON-RPC protocol stream between bridge and subprocess — never
mixed with HTTP body bytes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Iterable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_LOG = logging.getLogger("firebase_adapter.mcp_http_bridge")

# JSON-RPC methods the bridge will forward. ``initialize`` lets MCP clients
# probe the underlying server's protocol version + tool surface;
# ``tools/list`` introspects the canonical 8-tool surface; ``tools/call``
# is the only mutating path.
ALLOWED_RPC_METHODS = frozenset(("initialize", "tools/list", "tools/call"))

# Default loopback bind. Operators that need to expose the bridge to a
# different interface (e.g. Tailscale's tailnet IP) pass --bind explicitly.
DEFAULT_BIND = "127.0.0.1:8765"

# Default subprocess command. The bridge speaks to whatever CLI the
# operator configures; the default matches the canonical
# ``dontpanic mcp serve`` invocation registered with the user's
# environment.
DEFAULT_MCP_COMMAND: tuple[str, ...] = ("dontpanic", "mcp", "serve")


class BridgeError(Exception):
    """Structured error surfaced as an HTTP error response."""

    def __init__(self, status: HTTPStatus, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code or message


class StdioMcpProxy:
    """Owns a single ``dontpanic mcp serve`` subprocess and serializes
    JSON-RPC traffic across it.

    The subprocess speaks line-delimited JSON-RPC 2.0 on stdio (one
    request per line, one response per line). We hold a lock around every
    request/response pair so concurrent HTTP callers don't interleave
    each other's bytes. Stdio is by-design single-stream — if more
    parallelism is ever needed, the right answer is multiple subprocesses,
    not pipelining."""

    def __init__(
        self,
        command: Iterable[str] = DEFAULT_MCP_COMMAND,
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self._command = tuple(command)
        self._env = env
        self._cwd = cwd
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn the MCP subprocess. Safe to call before any request."""
        if self._proc is not None and self._proc.poll() is None:
            return
        _LOG.info("spawning MCP subprocess: %s", " ".join(self._command))
        self._proc = subprocess.Popen(  # noqa: S603 — command is operator-supplied
            list(self._command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            env=self._env if self._env is not None else os.environ.copy(),
            cwd=self._cwd,
            bufsize=1,  # line-buffered
            text=True,
            encoding="utf-8",
        )

    def stop(self) -> None:
        """Terminate the subprocess. Safe to call multiple times."""
        with self._lock:
            proc = self._proc
            self._proc = None
            if proc is None:
                return
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass

    # ── request/response ───────────────────────────────────────────────

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send one JSON-RPC request and return the parsed response."""
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                # Subprocess died or was never started — restart so we
                # don't permanently break after a single crash.
                self._proc = None
                self.start()
                proc = self._proc
            assert proc is not None and proc.stdin is not None and proc.stdout is not None
            try:
                proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise BridgeError(
                    HTTPStatus.BAD_GATEWAY,
                    f"MCP subprocess stdin closed: {exc}",
                    code="mcp_subprocess_dead",
                ) from exc

            line = proc.stdout.readline()
            if not line:
                raise BridgeError(
                    HTTPStatus.BAD_GATEWAY,
                    "MCP subprocess closed stdout before responding",
                    code="mcp_subprocess_eof",
                )
            try:
                return json.loads(line)
            except json.JSONDecodeError as exc:
                raise BridgeError(
                    HTTPStatus.BAD_GATEWAY,
                    f"MCP subprocess returned non-JSON: {exc}",
                    code="mcp_subprocess_garbage",
                ) from exc


def _verify_bearer(actual_header: str | None, expected_token: str) -> None:
    """Constant-time-ish bearer-token check. The check itself uses the
    plain `secrets.compare_digest` so we don't leak length via timing."""
    import secrets as _secrets

    if not actual_header or not actual_header.lower().startswith("bearer "):
        raise BridgeError(
            HTTPStatus.UNAUTHORIZED,
            "missing or malformed Authorization header",
            code="missing_bearer",
        )
    provided = actual_header.split(" ", 1)[1].strip()
    if not _secrets.compare_digest(provided, expected_token):
        raise BridgeError(
            HTTPStatus.UNAUTHORIZED,
            "bearer token does not match operator-configured value",
            code="bad_bearer",
        )


def _validate_rpc_request(body: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            HTTPStatus.BAD_REQUEST,
            f"body is not valid JSON: {exc}",
            code="bad_json",
        ) from exc
    if not isinstance(decoded, dict):
        raise BridgeError(
            HTTPStatus.BAD_REQUEST,
            "JSON-RPC request must be an object",
            code="bad_shape",
        )
    method = decoded.get("method")
    if not isinstance(method, str) or method not in ALLOWED_RPC_METHODS:
        raise BridgeError(
            HTTPStatus.FORBIDDEN,
            f"method {method!r} not allowed; permitted: {sorted(ALLOWED_RPC_METHODS)}",
            code="method_forbidden",
        )
    if decoded.get("jsonrpc") != "2.0":
        raise BridgeError(
            HTTPStatus.BAD_REQUEST,
            "JSON-RPC version must be 2.0",
            code="bad_jsonrpc_version",
        )
    return decoded


def make_handler(proxy: StdioMcpProxy, expected_token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        # Silence default stderr noise; bridge logs through `_LOG`.
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ARG002
            _LOG.debug("[http] " + format, *args)

        def _respond_error(self, err: BridgeError) -> None:
            payload = json.dumps(
                {"error": {"code": err.code, "message": err.message}}
            ).encode("utf-8")
            self.send_response(err.status.value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:  # noqa: N802 — http.server protocol
            try:
                _verify_bearer(self.headers.get("Authorization"), expected_token)
                length = int(self.headers.get("Content-Length") or "0")
                if length <= 0:
                    raise BridgeError(
                        HTTPStatus.BAD_REQUEST,
                        "POST body required",
                        code="empty_body",
                    )
                body = self.rfile.read(length)
                rpc_request = _validate_rpc_request(body)
                _LOG.info(
                    "forwarding %s id=%r",
                    rpc_request.get("method"),
                    rpc_request.get("id"),
                )
                rpc_response = proxy.call(rpc_request)
            except BridgeError as err:
                self._respond_error(err)
                return
            except Exception as exc:  # noqa: BLE001
                _LOG.exception("unhandled error in HTTP handler")
                self._respond_error(
                    BridgeError(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        f"internal bridge error: {exc}",
                        code="bridge_internal",
                    )
                )
                return

            body_bytes = json.dumps(rpc_response, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)

        def do_GET(self) -> None:  # noqa: N802 — http.server protocol
            # Tiny healthcheck without auth — useful for tunnel front-ends
            # to probe liveness without leaking the bearer token.
            if self.path == "/healthz":
                body = b'{"ok":true}'
                self.send_response(HTTPStatus.OK.value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._respond_error(
                BridgeError(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    "use POST for JSON-RPC; GET /healthz for liveness",
                    code="method_not_allowed",
                )
            )

    return Handler


def serve(
    bind: str,
    token: str,
    *,
    mcp_command: Iterable[str] = DEFAULT_MCP_COMMAND,
    proxy: StdioMcpProxy | None = None,
) -> ThreadingHTTPServer:
    """Start the HTTP server on ``bind`` (``host:port``). Returns the
    server instance; caller controls the lifecycle.

    For tests, inject ``proxy`` so the subprocess can be replaced with an
    in-process stub."""
    host, _, port_str = bind.partition(":")
    if not host or not port_str:
        raise ValueError(f"--bind must be host:port, got {bind!r}")
    port = int(port_str)
    if proxy is None:
        proxy = StdioMcpProxy(mcp_command)
        proxy.start()
    handler_cls = make_handler(proxy, token)
    server = ThreadingHTTPServer((host, port), handler_cls)
    server._dontpanic_proxy = proxy  # type: ignore[attr-defined]  # for clean shutdown
    return server


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="firebase_adapter.mcp_http_bridge",
        description=(
            "Operator-side HTTP ↔ stdio MCP bridge. Listens on a loopback "
            "port and forwards JSON-RPC tools/call payloads to a local "
            "`dontpanic mcp serve` subprocess. Expose via Tailscale Funnel "
            "/ Cloudflare Tunnel / ngrok for the Cloud Function side."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve", help="Run the HTTP bridge in the foreground.")
    sv.add_argument(
        "--bind",
        default=DEFAULT_BIND,
        help=f"host:port to listen on (default: {DEFAULT_BIND}).",
    )
    sv.add_argument(
        "--token-env",
        default="DONTPANIC_MCP_TUNNEL_TOKEN",
        help=(
            "Environment variable holding the shared bearer token. The "
            "same value must be configured on the Cloud Function side "
            "as MCP_TUNNEL_TOKEN."
        ),
    )
    sv.add_argument(
        "--mcp-command",
        nargs="+",
        default=list(DEFAULT_MCP_COMMAND),
        help="Override the subprocess command (default: dontpanic mcp serve).",
    )
    sv.add_argument(
        "--verbose",
        action="store_true",
        help="DEBUG-level logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        stream=sys.stderr,
        format="[%(asctime)s] %(name)s %(levelname)s %(message)s",
    )
    if args.cmd != "serve":  # pragma: no cover — argparse already enforces it
        print(f"unknown subcommand: {args.cmd!r}", file=sys.stderr)
        return 2
    token = os.environ.get(args.token_env)
    if not token:
        print(
            f"error: environment variable {args.token_env} must be set "
            "(operator's shared bearer token).",
            file=sys.stderr,
        )
        return 2
    server = serve(args.bind, token, mcp_command=args.mcp_command)
    _LOG.info("bridge listening on http://%s", args.bind)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _LOG.info("interrupted; shutting down")
    finally:
        server.shutdown()
        proxy: StdioMcpProxy = server._dontpanic_proxy  # type: ignore[attr-defined]
        proxy.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
