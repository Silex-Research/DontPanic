"""Entry point for ``python -m jarvis_orchestrate`` (legacy alias).

Forwards to :func:`dontpanic_orchestrate.cli.main`. Emits the one-shot
``DeprecationWarning`` from :mod:`jarvis_orchestrate._deprecation`.
"""

from jarvis_orchestrate._deprecation import warn_once as _warn_once

_warn_once()

from dontpanic_orchestrate.cli import main  # noqa: E402

raise SystemExit(main())
