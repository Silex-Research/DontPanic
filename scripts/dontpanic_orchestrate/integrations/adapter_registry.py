"""Plan 2026-05-20-001 F002 — operator-bootstrap adapter resolver.

The category-adapter bridge needs an :class:`AdapterResolver` instance
populated with one wrapper per PM-tool URI scheme the operator has
configured. This module is the CLI's bootstrap seam: ``default_resolver()``
walks ``~/.dontpanic/adapters/`` and registers a wrapper for every
mapping JSON it finds.

For v0 only the Linear wrapper is wired (per F001). Adding a second PM
tool means writing a sibling mapping JSON + a wrapper module — the
resolver picks both up automatically.

The CLI imports this lazily so missing optional dependencies (e.g. a PP
binary not installed) never block ``dontpanic plan lock`` for a plan
with NO external_refs. Lock-time validation calls into the resolver
ONLY when the plan declares external_refs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from dontpanic_orchestrate.external_refs_sync import AdapterResolver
from dontpanic_orchestrate.integrations.pm_tool_mapping import (
    PMToolMappingConfig,
    load_mapping_config,
)

if TYPE_CHECKING:
    from dontpanic_orchestrate.capabilities import CapabilityIndex

logger = logging.getLogger(__name__)

DEFAULT_ADAPTERS_DIR: Path = Path.home() / ".dontpanic" / "adapters"

# Adapter kinds map to the manifest ``category`` value they require when a
# registry record declares a ``capability_id``. v0 only ships the PM-tool
# adapter family; adding a second adapter kind (e.g. notification-sink for
# Discord) means extending this table, not editing the validator.
ADAPTER_KIND_CATEGORY: dict[str, str] = {
    "pm-tool": "pm-tool",
}


class AdapterCapabilityBindingError(ValueError):
    """Raised when a registry record's ``capability_id`` is invalid.

    Two distinct failure modes:

    * Unknown ID — the operator wrote ``capability_id: foo`` but no
      ``capabilities/foo.json`` manifest exists. The F001 loader is the
      source of truth.
    * Incompatible category — the manifest exists but its category
      doesn't match the adapter kind. PM-tool adapters require manifest
      category ``pm-tool``; pointing one at e.g. ``firebase-dashboard``
      (category ``dashboard-realtime``) is a config error.
    """


def validate_adapter_capability_binding(
    mapping: PMToolMappingConfig,
    *,
    capability_index: CapabilityIndex,
    adapter_kind: str = "pm-tool",
) -> None:
    """Validate one mapping config's ``capability_id`` against the manifest index.

    Returns silently when the mapping has no ``capability_id`` (legacy
    record) so backward compatibility is preserved. Otherwise raises
    :class:`AdapterCapabilityBindingError` with an actionable message.
    """

    if mapping.capability_id is None:
        return
    expected_category = ADAPTER_KIND_CATEGORY.get(adapter_kind)
    if expected_category is None:
        raise AdapterCapabilityBindingError(
            f"unknown adapter_kind {adapter_kind!r}; known kinds: {sorted(ADAPTER_KIND_CATEGORY)}"
        )
    manifest = capability_index.get(mapping.capability_id)
    if manifest is None:
        raise AdapterCapabilityBindingError(
            f"adapter {mapping.service_name!r} declares unknown "
            f"capability_id {mapping.capability_id!r}; check "
            f"capabilities/<id>.json manifests."
        )
    if manifest.category != expected_category:
        raise AdapterCapabilityBindingError(
            f"adapter {mapping.service_name!r} (kind={adapter_kind!r}) "
            f"binds to capability_id {mapping.capability_id!r} but its "
            f"manifest category is {manifest.category!r}; expected "
            f"{expected_category!r}."
        )


def default_resolver(
    adapters_dir: Path | None = None,
    *,
    capability_index: CapabilityIndex | None = None,
) -> AdapterResolver:
    """Construct an :class:`AdapterResolver` populated from operator config.

    For every ``<service>.json`` in ``adapters_dir`` (default
    ``~/.dontpanic/adapters/``), instantiate the corresponding wrapper
    and register it. Wrappers that fail to instantiate (missing PP
    binary, bad mapping) are logged + skipped — lock-time validation
    falls through to :class:`AdapterUnavailable` for those URIs, which
    the operator sees as a loud refusal.

    Plan 2026-05-21-001 F003 — when a mapping config declares a
    ``capability_id``, it must resolve through the F001 manifest loader
    and the manifest category must be compatible with the adapter kind
    ('pm-tool' for PM-tool adapters). Binding failures log + skip the
    affected adapter so a stray ``capability_id`` typo cannot bring down
    the entire resolver.
    """

    resolver = AdapterResolver()
    base = adapters_dir or DEFAULT_ADAPTERS_DIR
    if not base.is_dir():
        return resolver

    cap_index = capability_index  # loaded lazily on first bound mapping
    for config_path in sorted(base.glob("*.json")):
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            mapping = load_mapping_config(payload)
        except Exception as exc:  # noqa: BLE001 — operator-config errors logged + skipped
            logger.warning(
                "adapter_registry: skipping %s — config invalid: %s: %s",
                config_path,
                type(exc).__name__,
                exc,
            )
            continue

        if mapping.capability_id is not None:
            if cap_index is None:
                try:
                    from dontpanic_orchestrate.capabilities import load_capabilities

                    cap_index = load_capabilities()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "adapter_registry: skipping %s — capability manifests unavailable: %s: %s",
                        config_path,
                        type(exc).__name__,
                        exc,
                    )
                    continue
            try:
                validate_adapter_capability_binding(
                    mapping,
                    capability_index=cap_index,
                    adapter_kind="pm-tool",
                )
            except AdapterCapabilityBindingError as exc:
                logger.warning(
                    "adapter_registry: skipping %s — %s",
                    config_path,
                    exc,
                )
                continue

        hook = _build_wrapper_for(mapping.service_name, mapping)
        if hook is None:
            continue
        try:
            resolver.register(hook)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "adapter_registry: refusing duplicate scheme %r: %s",
                mapping.uri_scheme,
                exc,
            )
    return resolver


def _build_wrapper_for(service_name: str, mapping):  # type: ignore[no-untyped-def]
    """Service-name → wrapper. v0 ships Linear only; extension contract
    documented in evidence/pm-tool-extension-guide.md."""

    if service_name == "linear":
        try:
            from dontpanic_orchestrate.integrations.linear_pm_tool import LinearPMTool
            from dontpanic_orchestrate.integrations.linear_pp_adapter import LinearPPAdapter
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "adapter_registry: Linear wrapper imports failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            return None
        try:
            pp = LinearPPAdapter()  # type: ignore[call-arg]
            return LinearPMTool(mapping=mapping, pp_adapter=pp)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "adapter_registry: Linear wrapper construct failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            return None

    logger.warning(
        "adapter_registry: no built-in wrapper for service_name=%r — "
        "add a wrapper module and extend _build_wrapper_for.",
        service_name,
    )
    return None


__all__ = [
    "ADAPTER_KIND_CATEGORY",
    "AdapterCapabilityBindingError",
    "DEFAULT_ADAPTERS_DIR",
    "default_resolver",
    "validate_adapter_capability_binding",
]
