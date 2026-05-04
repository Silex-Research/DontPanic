"""Compatibility shim — re-exports from :mod:`dontpanic_orchestrate.nested_orchestration`.

The implementation lives at :mod:`dontpanic_orchestrate.nested_orchestration`. Importing
this module emits a one-shot ``DeprecationWarning`` per process via
:mod:`jarvis_orchestrate._deprecation`.

Plan: ``2026-05-04-001-refactor-canonical-dontpanic-module`` D002.
"""

from __future__ import annotations

from jarvis_orchestrate._deprecation import warn_once as _warn_once

_warn_once()

from dontpanic_orchestrate.nested_orchestration import *  # noqa: F401, F403, E402


def __getattr__(name: str):
    """Forward attribute lookups not covered by ``import *`` to canonical."""
    from dontpanic_orchestrate import nested_orchestration as _canonical

    try:
        return getattr(_canonical, name)
    except AttributeError as exc:
        raise AttributeError(
            f"module 'jarvis_orchestrate.nested_orchestration' has no attribute {name!r}"
        ) from exc
