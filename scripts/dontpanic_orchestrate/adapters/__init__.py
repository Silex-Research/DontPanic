"""Printing-press-adapter wrappers, one module per dogfooded service.

The printing-press-adapter skill (claude/skills/printing-press-adapter/
ADAPTER_TEMPLATE.md) declares this directory as the canonical home for
DontPanic-side wrappers around PP-emitted MCP binaries. Each adapter
module owns the trust boundary for one external service: spawn the PP
binary as a subprocess, route every tool response through the redact +
sanitize pipeline, and hard-reject mutating tools in v0.

F003 dogfood lands Linear here via ``linear_adapter`` — see plan
2026-05-10-001-feat-printing-press-adapter-skill, F003 evidence and
D007 / D008 for the budget lock and the v1 → v2 friction note about
the parallel ``integrations/linear_pp_adapter`` slot.
"""
