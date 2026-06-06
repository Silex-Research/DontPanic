"""Serve port policy — stable default port + fail-loud on conflict (plan 2026-06-06-002).

`dontpanic dashboard serve` must land on a predictable URL and, when its port is
taken, refuse with the holder + remediation rather than drifting to a random port.
"""

from __future__ import annotations

import errno
import socket

import pytest

from dontpanic_orchestrate import dashboard as D


def _parse(argv):
    return D.build_parser().parse_args(argv)


def test_cli_default_port_is_stable_8787():
    assert D.DEFAULT_CLI_PORT == 8787
    assert _parse(["serve"]).port == 8787  # predictable URL by default


def test_cli_port_zero_still_accepted_for_ephemeral():
    # serve_start / tests rely on 0 = ephemeral; the CLI must still allow it.
    assert _parse(["serve", "--port", "0"]).port == 0


def test_port_conflict_message_names_port_and_remediation():
    msg = D.port_conflict_message(8787, None)
    assert "8787" in msg
    assert "in use" in msg
    assert "--port 8788" in msg  # offers the next port


def test_port_conflict_message_includes_holder_and_kill_hint():
    msg = D.port_conflict_message(8787, "pid 4821: python -m http.server")
    assert "pid 4821" in msg
    assert "kill 4821" in msg  # actionable: how to free it


def test_port_holder_returns_none_for_a_free_port():
    # grab then release a port so we know it's free
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    free_port = s.getsockname()[1]
    s.close()
    assert D._port_holder(free_port) is None  # noqa: SLF001


def test_serve_main_eaddrinuse_fails_loud_with_port(monkeypatch, capsys):
    def boom(**_kwargs):
        raise OSError(errno.EADDRINUSE, "address already in use")

    monkeypatch.setattr(D, "serve_start", boom)
    rc = D._serve_main(_parse(["serve", "--no-watch"]))  # noqa: SLF001
    assert rc == 2  # conflict is a usage refusal, not a generic failure
    err = capsys.readouterr().err
    assert "8787" in err and "in use" in err


def test_serve_main_generic_oserror_is_still_bind_failed(monkeypatch, capsys):
    def boom(**_kwargs):
        raise OSError(errno.EACCES, "permission denied")

    monkeypatch.setattr(D, "serve_start", boom)
    rc = D._serve_main(_parse(["serve", "--no-watch"]))  # noqa: SLF001
    assert rc == 1  # non-conflict OSError keeps the existing path
    assert "bind failed" in capsys.readouterr().err
