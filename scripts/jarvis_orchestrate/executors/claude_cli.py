"""Compatibility shim — re-exports from :mod:`dontpanic_orchestrate.executors.claude_cli`."""

from __future__ import annotations

from jarvis_orchestrate._deprecation import warn_once as _warn_once

_warn_once()

from dontpanic_orchestrate.executors.claude_cli import *  # noqa: F401, F403, E402


def __getattr__(name: str):
    from dontpanic_orchestrate.executors import claude_cli as _canonical

    try:
        return getattr(_canonical, name)
    except AttributeError as exc:
        raise AttributeError(
            f"module 'jarvis_orchestrate.executors.claude_cli' has no attribute {name!r}"
        ) from exc
