"""Compatibility shim — re-exports from :mod:`dontpanic_orchestrate.executors`.

Per-submodule re-export files exist for filesystem-discovery patterns;
a package-level :func:`__getattr__` proxies anything they miss.

Plan: ``2026-05-04-001-refactor-canonical-dontpanic-module`` D002.
"""

from __future__ import annotations

from jarvis_orchestrate._deprecation import warn_once as _warn_once

_warn_once()

from dontpanic_orchestrate.executors import *  # noqa: F401, F403, E402


def __getattr__(name: str):
    """Lazy proxy: ``jarvis_orchestrate.executors.X`` → canonical."""
    import importlib

    try:
        return importlib.import_module(f"dontpanic_orchestrate.executors.{name}")
    except ImportError:
        from dontpanic_orchestrate import executors as _canonical

        try:
            return getattr(_canonical, name)
        except AttributeError as exc:
            raise AttributeError(
                f"module 'jarvis_orchestrate.executors' has no attribute {name!r}"
            ) from exc
