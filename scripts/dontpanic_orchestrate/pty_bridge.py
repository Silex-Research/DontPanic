"""Embedded-terminal PTY↔WebSocket bridge (plan 2026-06-06-002).

A stdlib-only WebSocket server-side endpoint that pumps a real PTY (a login shell)
to/from the browser's xterm.js. This turns the local dashboard into a command
executor, so it is OFF BY DEFAULT and defended by three independent gates, checked
by the caller BEFORE this module ever spawns a shell:

  1. loopback-only bind (the serve already enforces this),
  2. an Origin header equal to the served origin (no cross-site WS),
  3. a single per-serve session token in the handshake query (no drive-by / other
     local process can open a shell).

There is NO command allowlist — a terminal is a full shell by definition; the three
gates above are the whole boundary. See the plan's threat model.

This module is pure protocol + os plumbing: handshake math and frame codec are
unit-testable without a socket; ``pump_pty`` does the live wiring.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import select
import struct
import subprocess

# RFC 6455 magic GUID for the Sec-WebSocket-Accept handshake.
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Opcodes we handle.
_OP_TEXT = 0x1
_OP_BINARY = 0x2
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA


def accept_key(client_key: str) -> str:
    """RFC 6455 Sec-WebSocket-Accept value for a client's Sec-WebSocket-Key."""
    digest = hashlib.sha1((client_key + _WS_GUID).encode("ascii")).digest()  # noqa: S324 (protocol-mandated)
    return base64.b64encode(digest).decode("ascii")


def handshake_response(client_key: str) -> bytes:
    """The full 101 Switching Protocols response bytes for a WS upgrade."""
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key(client_key)}\r\n"
        "\r\n"
    ).encode("ascii")


def encode_frame(payload: bytes, *, opcode: int = _OP_TEXT) -> bytes:
    """Encode a single (unmasked, server→client) WebSocket frame."""
    header = bytearray([0x80 | opcode])  # FIN + opcode
    n = len(payload)
    if n < 126:
        header.append(n)
    elif n < (1 << 16):
        header.append(126)
        header += struct.pack("!H", n)
    else:
        header.append(127)
        header += struct.pack("!Q", n)
    return bytes(header) + payload


def decode_frames(buf: bytearray) -> list[tuple[int, bytes]]:
    """Drain all COMPLETE client→server frames from ``buf`` (mutated in place).

    Returns a list of (opcode, payload). Client frames are always masked (RFC
    6455); we unmask. Partial trailing bytes stay in ``buf`` for the next read.
    """
    out: list[tuple[int, bytes]] = []
    while True:
        if len(buf) < 2:
            break
        b0, b1 = buf[0], buf[1]
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        idx = 2
        if length == 126:
            if len(buf) < idx + 2:
                break
            length = struct.unpack("!H", bytes(buf[idx:idx + 2]))[0]
            idx += 2
        elif length == 127:
            if len(buf) < idx + 8:
                break
            length = struct.unpack("!Q", bytes(buf[idx:idx + 8]))[0]
            idx += 8
        mask = b"\x00\x00\x00\x00"
        if masked:
            if len(buf) < idx + 4:
                break
            mask = bytes(buf[idx:idx + 4])
            idx += 4
        if len(buf) < idx + length:
            break
        raw = bytes(buf[idx:idx + length])
        if masked:
            raw = bytes(c ^ mask[i % 4] for i, c in enumerate(raw))
        out.append((opcode, raw))
        del buf[: idx + length]
    return out


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        import fcntl
        import termios

        winsize = struct.pack("HHHH", max(1, rows), max(1, cols), 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except Exception:  # noqa: BLE001 — resize is best-effort
        pass


def pump_pty(
    conn,
    *,
    shell: str | None = None,
    cwd: str | None = None,
    env: dict | None = None,
) -> None:
    """Spawn a login shell on a PTY and pump it to/from an already-upgraded
    WebSocket ``conn`` (a connected socket). Blocks until either side closes.

    Client→server TEXT frames are shell input, EXCEPT a JSON control frame
    ``{"resize":{"rows":R,"cols":C}}`` which resizes the PTY. Server→client
    output is sent as BINARY frames (raw bytes; xterm decodes UTF-8).
    """
    shell = shell or os.environ.get("SHELL") or "/bin/bash"
    master_fd, slave_fd = os.openpty()
    proc = subprocess.Popen(  # noqa: S603 — intentional: this IS the terminal
        [shell, "-l"],
        preexec_fn=os.setsid,  # noqa: PLW1509 — own session so signals/SIGWINCH scope to the shell
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=cwd or None,
        env=env or os.environ.copy(),
        close_fds=True,
    )
    os.close(slave_fd)
    inbuf = bytearray()
    try:
        conn.setblocking(False)
        while True:
            if proc.poll() is not None:
                break
            rlist, _, _ = select.select([conn, master_fd], [], [], 0.2)
            if master_fd in rlist:
                try:
                    data = os.read(master_fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                conn.sendall(encode_frame(data, opcode=_OP_BINARY))
            if conn in rlist:
                try:
                    chunk = conn.recv(65536)
                except (BlockingIOError, InterruptedError):
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                inbuf += chunk
                for opcode, payload in decode_frames(inbuf):
                    if opcode == _OP_CLOSE:
                        return
                    if opcode in (_OP_PING, _OP_PONG):
                        continue
                    if _maybe_resize(master_fd, payload):
                        continue
                    os.write(master_fd, payload)
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass


def _maybe_resize(master_fd: int, payload: bytes) -> bool:
    """If ``payload`` is a JSON resize control message, apply it and return True."""
    if not payload.startswith(b"{"):
        return False
    try:
        msg = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    rs = msg.get("resize") if isinstance(msg, dict) else None
    if isinstance(rs, dict) and "rows" in rs and "cols" in rs:
        _set_winsize(master_fd, int(rs["rows"]), int(rs["cols"]))
        return True
    return False
