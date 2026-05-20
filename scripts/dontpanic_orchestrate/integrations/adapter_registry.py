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

from dontpanic_orchestrate.external_refs_sync import AdapterResolver
from dontpanic_orchestrate.integrations.pm_tool_mapping import load_mapping_config

logger = logging.getLogger(__name__)

DEFAULT_ADAPTERS_DIR: Path = Path.home() / ".dontpanic" / "adapters"


def default_resolver(
    adapters_dir: Path | None = None,
) -> AdapterResolver:
    """Construct an :class:`AdapterResolver` populated from operator config.

    For every ``<service>.json`` in ``adapters_dir`` (default
    ``~/.dontpanic/adapters/``), instantiate the corresponding wrapper
    and register it. Wrappers that fail to instantiate (missing PP
    binary, bad mapping) are logged + skipped — lock-time validation
    falls through to :class:`AdapterUnavailable` for those URIs, which
    the operator sees as a loud refusal.
    """

    resolver = AdapterResolver()
    base = adapters_dir or DEFAULT_ADAPTERS_DIR
    if not base.is_dir():
        return resolver

    for config_path in sorted(base.glob("*.json")):
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            mapping = load_mapping_config(payload)
        except Exception as exc:  # noqa: BLE001 — operator-config errors logged + skipped
            logger.warning(
                "adapter_registry: skipping %s — config invalid: %s: %s",
                config_path, type(exc).__name__, exc,
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
                mapping.uri_scheme, exc,
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
                type(exc).__name__, exc,
            )
            return None
        try:
            pp = LinearPPAdapter()  # type: ignore[call-arg]
            return LinearPMTool(mapping=mapping, pp_adapter=pp)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "adapter_registry: Linear wrapper construct failed: %s: %s",
                type(exc).__name__, exc,
            )
            return None

    logger.warning(
        "adapter_registry: no built-in wrapper for service_name=%r — "
        "add a wrapper module and extend _build_wrapper_for.",
        service_name,
    )
    return None


__all__ = ["DEFAULT_ADAPTERS_DIR", "default_resolver"]
