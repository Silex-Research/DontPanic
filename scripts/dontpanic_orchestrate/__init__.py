"""Forward-compatible public import alias for DontPanic.

The implementation still lives in :mod:`jarvis_orchestrate` during the
staged rename. Importing :mod:`dontpanic_orchestrate` gives new callers the
canonical product name without breaking existing integrations.
"""

from jarvis_orchestrate import __version__

__all__ = ["__version__"]
