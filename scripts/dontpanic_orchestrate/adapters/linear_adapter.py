"""DontPanic-side adapter for the Linear MCP binary wrapped via Printing Press.

F003 dogfood entry point. The canonical implementation lives at
``dontpanic_orchestrate.integrations.linear_pp_adapter`` — that module
predates F003 (authored by plan 2026-05-20-001 F001 for the PM-tool
bridge) and already implements every behavior the printing-press-adapter
skill prescribes:

  (i)   spawn the PP-emitted MCP binary as a subprocess,
  (ii)  forward each tool call,
  (iii) redact + sanitize every response (fail closed on surviving
        secret-shaped substrings),
  (iv)  hard-reject mutating tools on the generic ``call_tool`` proxy,
  (v)   register the adapter in ``~/.dontpanic/adapters.json``.

Rather than duplicate ~340 lines of boundary code, this module re-exports
the canonical surface from ``integrations.linear_pp_adapter`` at the
skill-prescribed path so the import that operators see in SKILL.md still
resolves:

    from dontpanic_orchestrate.adapters import linear_adapter as svc
    result = svc.call("issue", id="ISS-123")

The v1 → v2 friction this captures (recorded as D009 in this plan):
the skill's ADAPTER_TEMPLATE.md fixes the wrapper path at
``scripts/dontpanic_orchestrate/adapters/<service>_adapter.py`` while
the bridge plan claimed the ``integrations/`` slot first; v2 of the
skill resolves the location ambiguity (one canonical home + clear
guidance for adapters that double as PM-tool bridges).
"""

from __future__ import annotations

from typing import Any

from dontpanic_orchestrate.integrations.linear_pp_adapter import (
    MUTATING_TOOLS,
    PP_BINARY_PATH,
    REDACT_LEVEL,
    SERVICE_NAME,
    LinearPPAdapter,
    MutationRejected,
    SanitizationFailed,
    apply_redact,
    redact_and_sanitize,
    register_adapter,
    sanitize_response,
)

_PROCESS_SINGLETON: LinearPPAdapter | None = None


def get_process() -> LinearPPAdapter:
    """Lazy singleton matching the template's contract — the subprocess
    starts on first tool call, not at module import. Keeps import side-
    effect free aside from the idempotent registry write below."""

    global _PROCESS_SINGLETON
    if _PROCESS_SINGLETON is None:
        _PROCESS_SINGLETON = LinearPPAdapter(
            binary_path=PP_BINARY_PATH, redact_level=REDACT_LEVEL
        )
    return _PROCESS_SINGLETON


def call(tool_name: str, **arguments: Any) -> Any:
    """Public entry point for the rest of DontPanic.

    Mutating tools (``MUTATING_TOOLS``) hard-reject via the generic
    proxy. Status flips must go through the bridge's
    ``LinearPMTool.push_status`` codepath, which writes an
    ``ExternalSyncRecord`` per attempt — that record, not this proxy,
    is the mutation gate.
    """

    return get_process().call_tool(tool_name, dict(arguments))


# Plan D011: ``register_adapter()`` is NOT called at import time —
# importing this module must not mutate operator config under
# ``$DONTPANIC_HOME``. Operators (or a setup CLI) call
# ``register_adapter()`` explicitly during install. Tests can call it
# against their isolated ``DONTPANIC_HOME`` without leaking to
# ``~/.dontpanic``.


__all__ = (
    "SERVICE_NAME",
    "PP_BINARY_PATH",
    "REDACT_LEVEL",
    "MUTATING_TOOLS",
    "LinearPPAdapter",
    "MutationRejected",
    "SanitizationFailed",
    "apply_redact",
    "sanitize_response",
    "redact_and_sanitize",
    "register_adapter",
    "call",
    "get_process",
)
