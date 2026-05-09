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
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dontpanic_orchestrate.notify_event import NotifyEvent

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
        proc = subprocess.run(  # noqa: S603  # trusted argv + shell=False default per D001
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return proc.returncode == 0


def notify_event(event: "NotifyEvent") -> bool:
    """Plan 2026-05-01-002 F002 — project a NotifyEvent onto title/subtitle/
    message/group for the terminal-notifier sink.

    Title: ``Jarvis [{plan_id}]`` (operator scans by plan).
    Subtitle: ``{kind}`` (event kind verbatim, e.g. 'breaker_tripped').
    Message: first 140 chars of ``event.body`` (notification UX limit).
    Group: ``{plan_id}`` so a per-plan stack can be batch-cleared.

    Returns True iff the underlying notifier fired successfully.
    """
    message = event.body[:140] if event.body else ""
    return notify(
        f"Jarvis [{event.plan_id}]",
        message,
        subtitle=event.kind,
        group=event.plan_id,
    )


__all__ = [
    "DEFAULT_GROUP",
    "DISABLE_ENV",
    "NOTIFIER_BINARY",
    "is_available",
    "notify",
    "notify_event",
]
