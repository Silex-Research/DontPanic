"""F008 Item 3 — terminal-notifier wrapper with graceful fallback.

Invokes the macOS `terminal-notifier` binary when present. Falls back to a
no-op (returning False) when the binary is missing or non-mac. Honors
`JARVIS_NOTIFY_DISABLE=1` to silence all notifications, useful in tests +
CI where the desktop notification UX is meaningless.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Mapping

NOTIFIER_BINARY = "terminal-notifier"
DISABLE_ENV = "JARVIS_NOTIFY_DISABLE"
DEFAULT_GROUP = "jarvis"


def _binary_path() -> str | None:
    return shutil.which(NOTIFIER_BINARY)


def is_available() -> bool:
    """True iff terminal-notifier is callable and notifications aren't disabled."""
    if os.environ.get(DISABLE_ENV, "").strip() in {"1", "true", "yes"}:
        return False
    return _binary_path() is not None


def notify(
    title: str,
    message: str,
    *,
    subtitle: str | None = None,
    group: str | None = DEFAULT_GROUP,
    env: Mapping[str, str] | None = None,
    timeout: float = 3.0,
) -> bool:
    """Fire a single terminal-notifier notification. Returns True on success.

    Never raises. When the binary is absent or notifications are disabled
    via JARVIS_NOTIFY_DISABLE, returns False and the caller continues
    normally — INBOX.md is the durable channel, notifications are advisory.
    """
    runtime_env = dict(env) if env is not None else dict(os.environ)
    if runtime_env.get(DISABLE_ENV, "").strip() in {"1", "true", "yes"}:
        return False
    binary = _binary_path()
    if binary is None:
        return False
    cmd = [binary, "-title", title, "-message", message]
    if subtitle:
        cmd += ["-subtitle", subtitle]
    if group:
        cmd += ["-group", group]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return proc.returncode == 0


__all__ = ["DEFAULT_GROUP", "DISABLE_ENV", "NOTIFIER_BINARY", "is_available", "notify"]
