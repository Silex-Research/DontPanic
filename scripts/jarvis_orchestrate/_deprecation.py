"""One-shot deprecation guard for the `jarvis_orchestrate` compatibility shim.

The implementation lives at :mod:`dontpanic_orchestrate`. This module
emits exactly one :class:`DeprecationWarning` per process the first time
any shim module is imported. The shim is non-removing in v1 — see plan
``2026-05-04-001-refactor-canonical-dontpanic-module`` D006 for the
future-removal contract.
"""

from __future__ import annotations

import warnings

_warned: bool = False


def warn_once() -> None:
    """Emit a single ``DeprecationWarning`` per process. Idempotent."""
    global _warned
    if _warned:
        return
    _warned = True
    warnings.warn(
        "The `jarvis_orchestrate` package is a compatibility shim that "
        "re-exports from the canonical `dontpanic_orchestrate` package. "
        "Update your imports to `from dontpanic_orchestrate import ...` "
        "(plan 2026-05-04-001-refactor-canonical-dontpanic-module).",
        DeprecationWarning,
        stacklevel=3,
    )
