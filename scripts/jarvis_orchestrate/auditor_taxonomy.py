"""Compatibility shim — re-exports from :mod:`dontpanic_orchestrate.auditor_taxonomy`.

The implementation lives at :mod:`dontpanic_orchestrate.auditor_taxonomy`.
Importing this module emits a one-shot ``DeprecationWarning`` per process via
:mod:`jarvis_orchestrate._deprecation`.

Plan: ``2026-05-08-003-fix-harness-volley-frictions`` F003.
"""

from __future__ import annotations

from jarvis_orchestrate._deprecation import warn_once as _warn_once

_warn_once()

from dontpanic_orchestrate.auditor_taxonomy import *  # noqa: F401, F403, E402


def __getattr__(name: str):
    """Forward attribute lookups not covered by ``import *`` to canonical."""
    from dontpanic_orchestrate import auditor_taxonomy as _canonical

    try:
        return getattr(_canonical, name)
    except AttributeError as exc:
        raise AttributeError(
            f"module 'jarvis_orchestrate.auditor_taxonomy' has no attribute {name!r}"
        ) from exc
