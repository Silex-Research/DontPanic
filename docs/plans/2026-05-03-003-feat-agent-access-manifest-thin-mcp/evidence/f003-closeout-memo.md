# F003 close-out memo — 2026-05-04

F003 shipped direct per D010. This was a documentation-only feature with
deterministic acceptance: caller examples, MCP snippets, safety-rule presence,
publish-readiness checklist, and cross-reference checks.

## What changed

| Surface | Change |
|---|---|
| `README.md` | Added `How agents call DontPanic` with Claude Code, Cursor, OpenClaw, and Codex CLI examples. Each example includes manifest discovery, `mcp.json` wiring for `dontpanic mcp serve`, and a safe tool flow. |
| `docs/DISCOVERABILITY.md` | New publish-readiness checklist for manifest, README examples, MCP snippet, PyPI readiness, GitHub topics, MCP-directory readiness, and cross-references. |
| `docs/ECOSYSTEM.md` | Added `Safety rules for agent callers`; corrected Phase B language to the shipped six-tool MCP surface and no `intake` tool. |
| `docs/ROADMAP.md` | Updated Phase B status and shipped tool list; points to discoverability and authoring-plan docs. |
| `scripts/jarvis_orchestrate/tests/test_f003_discoverability_docs.py` | New tests for safety-rule presence, caller examples, JSON snippet validity, canonical `dontpanic mcp serve`, and cross-references. |

## Verification

- `PYTHONPATH=scripts python3 -m pytest scripts/jarvis_orchestrate/tests/test_f003_discoverability_docs.py -q`: **4 passed**.
- `ruff check scripts/jarvis_orchestrate/tests/test_f003_discoverability_docs.py`: **All checks passed**.
- `ruff format --check scripts/jarvis_orchestrate/tests/test_f003_discoverability_docs.py`: **already formatted**.

## Scope Boundary

External publication is deliberately not part of F003. PyPI submission,
GitHub topic updates, README badges, and MCP-directory submission remain
checklist items in `docs/DISCOVERABILITY.md`, not acceptance blockers.

`docs/AUTHORING_PLANS.md` is referenced as the F004 surface and is expected to
land in the next direct documentation commit.
