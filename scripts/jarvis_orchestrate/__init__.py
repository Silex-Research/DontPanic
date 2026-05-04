"""Compatibility shim — redirects to canonical :mod:`dontpanic_orchestrate`.

The implementation lives at :mod:`dontpanic_orchestrate`. This package
re-exports the canonical module-level surface and emits one
:class:`DeprecationWarning` per process via
:mod:`jarvis_orchestrate._deprecation`.

Per-submodule re-export files exist for filesystem-discovery patterns
(mypy, IDE auto-import, ``python -m jarvis_orchestrate.X``); a
package-level :func:`__getattr__` proxies any submodule the explicit
files don't cover.

Plan authority: ``2026-05-04-001-refactor-canonical-dontpanic-module``
D001-D006.
"""

from __future__ import annotations

from jarvis_orchestrate._deprecation import warn_once as _warn_once

_warn_once()

from dontpanic_orchestrate import __version__  # noqa: F401, E402

__all__ = ["__version__"]


def __getattr__(name: str):
    """Lazy proxy: ``jarvis_orchestrate.X`` → ``dontpanic_orchestrate.X``."""
    import importlib

    try:
        return importlib.import_module(f"dontpanic_orchestrate.{name}")
    except ImportError as exc:
        raise AttributeError(f"module 'jarvis_orchestrate' has no attribute {name!r}") from exc
