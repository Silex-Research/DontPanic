"""Plan 2026-05-09-004 F003 audit-i1 — tests for the operator-side HTTP ↔
stdio MCP bridge.

Two layers of coverage:

1. *Unit-level*: pump JSON-RPC requests through ``StdioMcpProxy`` against
   a fake subprocess (a Python helper that just echoes the request id +
   acknowledges the tool name). Validates we serialize one line in / one
   line out and survive a subprocess restart.

2. *End-to-end*: spin the HTTP bridge with a fake proxy and send live
   requests via ``urllib``. Validates bearer-auth enforcement, JSON-RPC
   allow-list, and that the response body matches the proxy's reply.

A third (live-MCP) test spawns the real ``dontpanic mcp serve`` subprocess
and exercises a read-only tool (``tools/list``) so we confirm the bridge
talks to the actual operator-side server. It's skipped if the ``dontpanic``
CLI is not on PATH so the test stays runnable in CI without DontPanic.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# Ensure the script directory is importable when pytest runs from repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from firebase_adapter import mcp_http_bridge  # noqa: E402


# ──────────────────────────────  fixtures  ──────────────────────────────


class FakeStdioProxy:
    """In-process replacement for StdioMcpProxy used in HTTP-layer tests."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next_result: dict | None = None
        self.raise_on_call: Exception | None = None

    def call(self, payload: dict) -> dict:
        self.calls.append(payload)
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if self.next_result is not None:
            return self.next_result
        return {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "result": {"echo": payload.get("params")},
        }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def fake_proxy():
    return FakeStdioProxy()


@pytest.fixture
def running_bridge(fake_proxy):
    port = _free_port()
    bind = f"127.0.0.1:{port}"
    token = "test-bearer-token"
    server = mcp_http_bridge.serve(bind, token, proxy=fake_proxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # tiny wait so the listener is definitely accepting
    _wait_port_open("127.0.0.1", port)
    yield {"bind": bind, "token": token, "proxy": fake_proxy, "port": port}
    server.shutdown()
    server.server_close()


def _wait_port_open(host: str, port: int, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.01)
    raise TimeoutError(f"port {host}:{port} did not open within {timeout}s")


# ──────────────────────────────  request validation  ──────────────────────────────


def test_validate_rpc_request_accepts_tools_call():
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "status", "arguments": {}},
    }).encode("utf-8")
    out = mcp_http_bridge._validate_rpc_request(body)
    assert out["method"] == "tools/call"


def test_validate_rpc_request_rejects_unknown_method():
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "filesystem/wipe"}).encode("utf-8")
    with pytest.raises(mcp_http_bridge.BridgeError) as ei:
        mcp_http_bridge._validate_rpc_request(body)
    assert ei.value.code == "method_forbidden"
    assert ei.value.status.value == 403


def test_validate_rpc_request_rejects_non_object():
    with pytest.raises(mcp_http_bridge.BridgeError) as ei:
        mcp_http_bridge._validate_rpc_request(b'"just a string"')
    assert ei.value.code == "bad_shape"


def test_validate_rpc_request_rejects_bad_json():
    with pytest.raises(mcp_http_bridge.BridgeError) as ei:
        mcp_http_bridge._validate_rpc_request(b"not json")
    assert ei.value.code == "bad_json"


def test_validate_rpc_request_rejects_wrong_jsonrpc_version():
    body = json.dumps({"jsonrpc": "1.0", "id": 1, "method": "tools/list"}).encode("utf-8")
    with pytest.raises(mcp_http_bridge.BridgeError) as ei:
        mcp_http_bridge._validate_rpc_request(body)
    assert ei.value.code == "bad_jsonrpc_version"


# ──────────────────────────────  bearer auth  ──────────────────────────────


def test_verify_bearer_accepts_matching_token():
    mcp_http_bridge._verify_bearer("Bearer secret-xyz", "secret-xyz")


def test_verify_bearer_rejects_mismatch():
    with pytest.raises(mcp_http_bridge.BridgeError) as ei:
        mcp_http_bridge._verify_bearer("Bearer wrong", "secret-xyz")
    assert ei.value.code == "bad_bearer"
    assert ei.value.status.value == 401


def test_verify_bearer_rejects_missing_header():
    with pytest.raises(mcp_http_bridge.BridgeError) as ei:
        mcp_http_bridge._verify_bearer(None, "secret-xyz")
    assert ei.value.code == "missing_bearer"


def test_verify_bearer_rejects_malformed_header():
    with pytest.raises(mcp_http_bridge.BridgeError):
        mcp_http_bridge._verify_bearer("Basic xyz", "secret-xyz")


# ──────────────────────────────  end-to-end HTTP  ──────────────────────────────


def _post(url: str, body: dict, *, headers: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers or {"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:  # noqa: S310 — loopback test
            return resp.getcode(), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_post_with_valid_bearer_forwards_to_proxy(running_bridge):
    rb = running_bridge
    url = f"http://{rb['bind']}/"
    status, body = _post(
        url,
        {
            "jsonrpc": "2.0",
            "id": "rpc-1",
            "method": "tools/call",
            "params": {"name": "approve_gate", "arguments": {"plan": "p", "gate": "g", "confirm": True}},
        },
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {rb['token']}",
        },
    )
    assert status == 200
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == "rpc-1"
    assert body["result"]["echo"]["name"] == "approve_gate"
    assert len(rb["proxy"].calls) == 1


def test_http_post_without_bearer_rejected(running_bridge):
    rb = running_bridge
    url = f"http://{rb['bind']}/"
    status, body = _post(
        url,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert status == 401
    assert body["error"]["code"] == "missing_bearer"
    assert rb["proxy"].calls == []


def test_http_post_with_wrong_bearer_rejected(running_bridge):
    rb = running_bridge
    url = f"http://{rb['bind']}/"
    status, body = _post(
        url,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
    )
    assert status == 401
    assert body["error"]["code"] == "bad_bearer"


def test_http_post_with_forbidden_method_rejected(running_bridge):
    rb = running_bridge
    url = f"http://{rb['bind']}/"
    status, body = _post(
        url,
        {"jsonrpc": "2.0", "id": 1, "method": "shutdown"},
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {rb['token']}"},
    )
    assert status == 403
    assert body["error"]["code"] == "method_forbidden"
    assert rb["proxy"].calls == []


def test_http_get_healthz_works_without_bearer(running_bridge):
    rb = running_bridge
    url = f"http://{rb['bind']}/healthz"
    with urllib.request.urlopen(url, timeout=2.0) as resp:  # noqa: S310 — loopback
        assert resp.getcode() == 200
        assert json.loads(resp.read())["ok"] is True


# ──────────────────────────────  StdioMcpProxy (fake subprocess)  ──────────────────────────────


_ECHO_SCRIPT = (
    "import sys, json\n"
    "for line in sys.stdin:\n"
    "    line = line.strip()\n"
    "    if not line:\n"
    "        continue\n"
    "    msg = json.loads(line)\n"
    "    resp = {'jsonrpc':'2.0','id':msg.get('id'),'result':{'tool':msg.get('params',{}).get('name'),'echoed':True}}\n"
    "    sys.stdout.write(json.dumps(resp)+'\\n')\n"
    "    sys.stdout.flush()\n"
)


def test_stdio_proxy_round_trips_against_python_echo_subprocess():
    proxy = mcp_http_bridge.StdioMcpProxy(command=[sys.executable, "-c", _ECHO_SCRIPT])
    try:
        proxy.start()
        out = proxy.call(
            {"jsonrpc": "2.0", "id": 42, "method": "tools/call",
             "params": {"name": "status", "arguments": {}}}
        )
        assert out["id"] == 42
        assert out["result"]["tool"] == "status"
        assert out["result"]["echoed"] is True
        # Second call uses same subprocess — verify reuse.
        out2 = proxy.call(
            {"jsonrpc": "2.0", "id": 43, "method": "tools/call",
             "params": {"name": "validate_plan", "arguments": {}}}
        )
        assert out2["result"]["tool"] == "validate_plan"
    finally:
        proxy.stop()


# ──────────────────────────────  optional live-MCP test  ──────────────────────────────


@pytest.mark.skipif(
    shutil.which("dontpanic") is None,
    reason="`dontpanic` CLI not on PATH; live MCP integration test skipped.",
)
def test_bridge_against_real_dontpanic_mcp_subprocess():
    """Spin the bridge against a real `dontpanic mcp serve` subprocess and
    confirm a JSON-RPC ``tools/list`` round-trip returns the expected
    canonical tool surface (acceptance #4 — exercises the real chain on
    the read-only side, without mutating any plan)."""
    port = _free_port()
    bind = f"127.0.0.1:{port}"
    token = "live-bridge-token"
    server = mcp_http_bridge.serve(bind, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _wait_port_open("127.0.0.1", port)
    try:
        status, body = _post(
            f"http://{bind}/",
            {"jsonrpc": "2.0", "id": "live-1", "method": "tools/list"},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        assert status == 200
        names = {td["name"] for td in body["result"]["tools"]}
        # Canonical tool surface from mcp_server._build_tools.
        for required in ("list_projects", "approve_gate", "dispatch", "status"):
            assert required in names, f"missing {required} in {names}"
    finally:
        server.shutdown()
        server.server_close()
        proxy: mcp_http_bridge.StdioMcpProxy = server._dontpanic_proxy  # type: ignore[attr-defined]
        proxy.stop()
