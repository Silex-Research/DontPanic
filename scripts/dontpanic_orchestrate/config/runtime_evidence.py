"""Plan G F006 — ``RuntimeEvidenceConfig``: per-project runtime target
defaults that the G capture adapters consume.

**Project-scoped only (D015).** Global config never carries runtime
target defaults — base URLs, simulator names, Android package IDs, and
backend provider IDs are project-specific by definition.

Sub-models are deliberately permissive about which fields they accept
because each adapter (G1 web, G2 iOS, G3 android, G4 backend) decides
what it understands. ``extra='forbid'`` on each sub-model still rejects
typos at config-load time, but adapters pick fields they care about
from the resolved dict — the typed Pydantic shape is for
operator-friendly authoring, not for the adapter call surface.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WebDefaults(BaseModel):
    """G1 web-adapter runtime defaults."""

    model_config = ConfigDict(extra="forbid")

    base_url: str | None = None
    """Base URL the web adapter navigates from. Operator-supplied per
    project; no global default (D015)."""

    driver_options: dict[str, Any] | None = None
    """Pass-through dict the web driver receives (Playwright launch
    args, etc.). Adapter knows the shape; we don't validate it here."""


class IosDefaults(BaseModel):
    """G2 iOS-adapter runtime defaults."""

    model_config = ConfigDict(extra="forbid")

    scheme: str | None = None
    simulator: str | None = None
    app_bundle_id: str | None = None


class AndroidDefaults(BaseModel):
    """G3 Android-adapter runtime defaults."""

    model_config = ConfigDict(extra="forbid")

    package: str | None = None
    adb_device_serial: str | None = None


class BackendDefaults(BaseModel):
    """G4 backend-adapter runtime defaults.

    ``auth`` is a credential POINTER, never a value (D014). Allowed
    shapes — ``adc`` / ``env:NAME`` / path-only — are validated by
    :func:`config.setup.is_credential_pointer` at write time.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, description="firebase | supabase | generic")
    project: str | None = None
    auth: str | None = Field(
        default=None,
        description=(
            "Credential pointer (D014): 'adc', 'env:NAME', or path-only. Never a credential value."
        ),
    )


class RuntimeEvidenceConfig(BaseModel):
    """Per-project runtime evidence defaults. One sub-block per source
    surface."""

    model_config = ConfigDict(extra="forbid")

    web: WebDefaults | None = None
    ios: IosDefaults | None = None
    android: AndroidDefaults | None = None
    backend: BackendDefaults | None = None


__all__ = [
    "AndroidDefaults",
    "BackendDefaults",
    "IosDefaults",
    "RuntimeEvidenceConfig",
    "WebDefaults",
]
