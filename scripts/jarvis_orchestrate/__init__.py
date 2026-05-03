"""DontPanic cross-agent orchestration runtime.

Exposes ``__version__`` as the single source of truth consumed by
``pyproject.toml`` (via ``[tool.setuptools.dynamic]``) and surfaced by
the ``dontpanic --version`` console script.
"""

__version__ = "0.1.0"
