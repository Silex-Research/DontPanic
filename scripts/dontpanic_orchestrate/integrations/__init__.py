"""PM-tool category contract + per-service wrappers.

Plan 2026-05-20-001 F001 introduces this package. The split is sharp:

- ``pm_tool_models`` — abstract Pydantic models that every PM-tool wrapper
  speaks. Service-agnostic by directive. v0 covers the minimum surface
  all PM tools share (issue/project/status/comment); vendor-specific
  concepts stay opaque pass-throughs via the raw PP MCP adapter.
- ``pm_tool_mapping`` — semantic mapping config schema. Per-service JSON
  at ``~/.dontpanic/adapters/<service>.json`` translates field names +
  status enum + priority enum into the abstract contract.
- ``pm_tool_sync`` — sync hook interface (``read_issue`` /
  ``push_status``) and the ``ExternalSyncRecord`` evidence shape that
  F002's plan-close push consumes. Per-service wrappers implement these
  by composing the raw MCP adapter from P10 F001's ADAPTER_TEMPLATE.
- ``linear_pp_adapter`` — PP-template-shaped subprocess adapter for the
  Linear MCP binary. Owns the trust layer (subprocess + redact +
  sanitize boundary) per P10 F001's printing-press-adapter skill. The
  PP binary itself is delivered by P10 F003 dogfood and pinned at
  plan-lock time via ``~/.dontpanic/adapters/linear.json``.
- ``linear_pm_tool`` — the reference PM-tool wrapper: composes
  ``linear_pp_adapter`` + mapping JSON to satisfy ``PMToolSyncHook``.
  ≤100 lines by design; copy as ``<service>_pm_tool.py`` for new PM
  tools. The per-service modules MUST NOT touch ``pm_tool_models`` /
  ``pm_tool_mapping`` / ``pm_tool_sync`` — if you find yourself needing
  to, the category contract itself is expanding (a v1 plan, not a
  per-service follow-on).

Add a second PM tool by:

  1. PP-generating the per-service MCP binary (per P10 F001's
     ``printing-press-adapter`` skill).
  2. Copying ``linear_pp_adapter.py`` to ``<service>_pp_adapter.py``
     and filling SERVICE_NAME / MUTATING_TOOLS / REDACT_LEVEL.
  3. Authoring ``~/.dontpanic/adapters/<service>.json`` against
     ``pm_tool_mapping.PMToolMappingConfig``.
  4. Copying ``linear_pm_tool.py`` to ``<service>_pm_tool.py`` and
     swapping the service_name / adapter import. No edits to the
     three generic modules above should be required.
"""

from __future__ import annotations
