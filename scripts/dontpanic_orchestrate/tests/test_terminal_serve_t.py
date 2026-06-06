"""Embedded terminal — serve guard + governance tests (plan 2026-06-06-002).

The /pty + /terminal/session routes are the trust boundary. These assert every
gate the user required: off-by-default, loopback-only, Origin check, token
required, audit line, and no auto-enable from config.
"""

from __future__ import annotations

import base64
import http.client
import inspect
import json
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from dontpanic_orchestrate import dashboard as D


def _server(enable_terminal: bool, token: str = "TToken"):
    srv = D._make_server(host="127.0.0.1", port=0, directory=Path("dashboard"))  # noqa: SLF001
    srv.dp_enable_terminal = enable_terminal
    srv.dp_session_token = token if enable_terminal else ""
    srv.dp_terminal_cwd = str(Path.cwd())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.2)
    return srv, srv.server_address[1]


def _ws_get(port, path, origin):
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("GET", path, headers={
        "Upgrade": "websocket", "Connection": "Upgrade",
        "Sec-WebSocket-Key": base64.b64encode(os.urandom(16)).decode(),
        "Sec-WebSocket-Version": "13", "Origin": origin,
    })
    return c.getresponse()


def test_off_by_default_session_reports_disabled_and_pty_404():
    srv, port = _server(enable_terminal=False)
    try:
        j = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/terminal/session"))
        assert j["enabled"] is False and j["token"] == ""
        r = _ws_get(port, "/pty?token=anything", f"http://127.0.0.1:{port}")
        assert r.status == 404
    finally:
        srv.shutdown()


def test_token_required():
    srv, port = _server(enable_terminal=True, token="RIGHT")
    try:
        assert _ws_get(port, "/pty?token=WRONG", f"http://127.0.0.1:{port}").status == 403
        assert _ws_get(port, "/pty", f"http://127.0.0.1:{port}").status == 403  # no token
    finally:
        srv.shutdown()


def test_origin_check_rejects_foreign_origin():
    srv, port = _server(enable_terminal=True, token="RIGHT")
    try:
        r = _ws_get(port, "/pty?token=RIGHT", "http://evil.example.com")
        assert r.status == 403
    finally:
        srv.shutdown()


def test_good_token_and_origin_upgrades_and_runs_a_shell():
    srv, port = _server(enable_terminal=True, token="RIGHT")
    try:
        s = socket.create_connection(("127.0.0.1", port))
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((
            f"GET /pty?token=RIGHT HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Origin: http://127.0.0.1:{port}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        time.sleep(0.3)
        assert b"101 Switching Protocols" in s.recv(2048)
        cmd = b"echo SERVE_SHELL_OK\n"
        m = os.urandom(4)
        s.sendall(bytes([0x81, 0x80 | len(cmd)]) + m + bytes(c ^ m[i % 4] for i, c in enumerate(cmd)))
        time.sleep(0.5)
        s.setblocking(False)
        got = b""
        try:
            while True:
                got += s.recv(65536)
        except BlockingIOError:
            pass
        assert b"SERVE_SHELL_OK" in got  # raw bytes appear inside the WS frames
        s.close()
    finally:
        srv.shutdown()


def test_loopback_only_enforced_even_with_terminal():
    # serve_start refuses a non-loopback bind before doing any work.
    with pytest.raises(ValueError, match="loopback"):
        D.serve_start(host="0.0.0.0", allow_remote=False, enable_terminal=True)


def test_audit_line_names_the_boundary():
    line = D.terminal_audit_line("/repo/x")
    assert "TERMINAL ENABLED" in line
    assert "/repo/x" in line
    assert "unrestricted" in line


def test_no_auto_enable_from_config_or_build():
    # enable_terminal is OFF unless explicitly passed; never a config/build key.
    assert inspect.signature(D.serve_start).parameters["enable_terminal"].default is False
    assert "enable_terminal" not in inspect.signature(D.build).parameters
    # a freshly constructed server is disabled until serve_start opts in
    assert D._ReusableTCPServer.dp_enable_terminal is False  # noqa: SLF001
