"""Embedded terminal — PTY↔WebSocket bridge unit tests (plan 2026-06-06-002).

WebSocket handshake/framing + PTY lifecycle + resize. Pure protocol + os
plumbing; no HTTP server needed.
"""

from __future__ import annotations

import os
import socket
import struct
import threading
import time

from dontpanic_orchestrate import pty_bridge as pb


def _mask(payload: bytes, opcode: int = 0x1) -> bytes:
    m = os.urandom(4)
    masked = bytes(c ^ m[i % 4] for i, c in enumerate(payload))
    n = len(payload)
    header = bytearray([0x80 | opcode])
    if n < 126:
        header.append(0x80 | n)
    elif n < (1 << 16):
        header.append(0x80 | 126)
        header += struct.pack("!H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", n)
    return bytes(header) + m + masked


def test_handshake_accept_key_matches_rfc6455_vector():
    # The canonical example from RFC 6455 §1.3.
    assert pb.accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_handshake_response_is_a_101_upgrade():
    resp = pb.handshake_response("dGhlIHNhbXBsZSBub25jZQ==")
    assert resp.startswith(b"HTTP/1.1 101 Switching Protocols\r\n")
    assert b"Upgrade: websocket\r\n" in resp
    assert b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n" in resp


def test_frame_encode_decode_roundtrip_unicode():
    payload = "echo 🚀 done".encode("utf-8")
    # server-encoded binary frame is unmasked, FIN set
    enc = pb.encode_frame(payload, opcode=0x2)
    assert enc[0] == 0x82 and enc[1] == len(payload)
    # client→server frames are masked; decode unmasks
    out = pb.decode_frames(bytearray(_mask(payload)))
    assert out == [(0x1, payload)]


def test_decode_handles_partial_then_completes():
    full = _mask(b"hello")
    buf = bytearray(full[:3])  # only part of the frame arrived
    assert pb.decode_frames(buf) == []  # nothing complete yet
    buf += full[3:]
    assert pb.decode_frames(buf) == [(0x1, b"hello")]
    assert not buf  # fully drained


def test_decode_extended_length_126():
    payload = b"x" * 300
    out = pb.decode_frames(bytearray(_mask(payload)))
    assert out == [(0x1, payload)]


def test_resize_control_message_recognized_and_others_ignored():
    assert pb._maybe_resize(0, b'{"resize":{"rows":40,"cols":120}}') is True  # noqa: SLF001
    assert pb._maybe_resize(0, b"not json") is False  # noqa: SLF001
    assert pb._maybe_resize(0, b'{"other":1}') is False  # noqa: SLF001


def test_pty_lifecycle_runs_a_command_and_terminates():
    a, b = socket.socketpair()
    t = threading.Thread(target=pb.pump_pty, kwargs={"conn": b, "shell": "/bin/bash"}, daemon=True)
    t.start()
    time.sleep(0.4)
    a.sendall(_mask(b"echo PTY_LIFECYCLE_OK\n"))
    time.sleep(0.6)
    a.setblocking(False)
    got = b""
    try:
        while True:
            got += a.recv(65536)
    except BlockingIOError:
        pass
    # decode the server's (unmasked) frames
    dec, buf = b"", bytearray(got)
    while len(buf) >= 2:
        ln, idx = buf[1] & 0x7F, 2
        if ln == 126:
            ln, idx = struct.unpack("!H", bytes(buf[2:4]))[0], 4
        elif ln == 127:
            ln, idx = struct.unpack("!Q", bytes(buf[2:10]))[0], 10
        if len(buf) < idx + ln:
            break
        dec += bytes(buf[idx:idx + ln])
        del buf[: idx + ln]
    assert b"PTY_LIFECYCLE_OK" in dec
    # closing the client socket ends the pump + reaps the shell
    a.close()
    t.join(timeout=3)
    assert not t.is_alive()
    b.close()
