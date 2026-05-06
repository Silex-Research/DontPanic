"""Plan G F006 / G0 — Minimum operator configuration surface.

The operator-facing config UX the runtime evidence adapters consume.
Two typed config blocks land here:

- :class:`RolesConfig` — global + per-project (D013): ``implementer``,
  ``auditor``, ``goal_auditor``. Layered with the legacy
  ``default_implementer`` / ``default_auditor`` (global) and
  ``implementer`` / ``auditor`` (project) fields, which remain readable
  for backward compatibility.
- :class:`RuntimeEvidenceConfig` — **per-project only** (D015). Global
  config never carries runtime target defaults (base URLs, simulator
  names, Android package IDs, backend provider IDs). Enforced both via
  the absence of a Pydantic field on :class:`global_config.GlobalConfig`
  and via a greppable test in
  ``test_f006_config_setup_surface.py``.

D014: credentials are pointers, never values. Pointer shapes accepted by
:func:`config.setup.is_credential_pointer`:

- ``adc`` — Application Default Credentials (gcloud) sentinel.
- path-only references (``./secrets/sa.json``, ``~/abs/path``,
  ``/abs/path``).
- ``env:NAME`` — operator-supplied env-var pointer.

This package's public surface is intentionally minimal; adapter
configurations land in their own plans (G2-G5 register per-source
doctor checks via :func:`doctor_registry.register_doctor_check`).
"""

from __future__ import annotations

from dontpanic_orchestrate.config.roles import RolesConfig
from dontpanic_orchestrate.config.runtime_evidence import (
    AndroidDefaults,
    BackendDefaults,
    IosDefaults,
    RuntimeEvidenceConfig,
    WebDefaults,
)

__all__ = [
    "AndroidDefaults",
    "BackendDefaults",
    "IosDefaults",
    "RolesConfig",
    "RuntimeEvidenceConfig",
    "WebDefaults",
]
