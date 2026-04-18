# Shared Conventions Index

Cross-project conventions for iOS+Firebase apps. Skills MUST reference these files rather than inlining the rules.

- [Firestore Security](firestore-security.md) — auth verification, App Check, transaction ordering, query safety, write reliability
- [Error Handling](error-handling.md) — error types, async handling, backend errors, classification taxonomy
- [Testing Hierarchy](testing-hierarchy.md) — TDD red/green, coverage targets, mock boundaries, QA review protocol
- [Naming](naming.md) — Swift/TS/Firestore naming, Cloud Functions, skill/agent files, terminology
- [Security](security.md) — authentication, input validation, rate limiting, data protection, AI content safety

## How to Use

In skill files, reference conventions instead of restating rules:

```markdown
## Prerequisites
- See `.claude/shared/conventions/firestore-security.md` for auth patterns
- See `.claude/shared/conventions/testing-hierarchy.md` for mock boundaries
```

## Cross-Agent Portability

These conventions are **plain markdown** — consumable by any agent harness (Claude Code, Codex, Gemini, Grok, Kimi, Qwen, Cursor). No Claude-specific features are used in convention content.

**How each harness loads them:**

| Harness | Native directory | How to consume shared conventions |
|---|---|---|
| Claude Code | `.claude/` | Subtree at `.claude/shared/` — loaded natively |
| Codex | `.codex/` or project root | `sync-harness.sh` copies to Codex-native location |
| Gemini | `gemini/` | `sync-harness.sh` copies; Gemini reads markdown directly |
| Grok / Kimi / Qwen | varies | Point agent at convention files via system prompt or context loading |
| Cursor | `.cursor/rules/` | `sync-harness.sh` copies to `.cursor/rules/` |

**Portability rules:**
- Convention files use only standard markdown (no Claude-specific tags, tools, or slash commands)
- YAML frontmatter in skill files uses only standard fields; agent-specific fields (e.g., `disable-model-invocation`) are ignored by other harnesses
- The resolver SPEC uses markdown tables — universally parseable
- `validate.py` is a standalone Python script with no agent dependencies

**For multi-harness projects (e.g., Jarvis):** maintain a `sync-harness.sh` script that mirrors convention files from the canonical `.claude/shared/` location to other harness directories. See Jarvis `claude/PORTABILITY.md` for the reference implementation.

## Project-Specific Extensions

Each project may add local conventions in `.claude/conventions/` that extend (not override) the shared set:
- `.claude/conventions/terminology.md` — project-specific naming (UI labels, forbidden terms)
- `.claude/conventions/pipeline.md` — enrichment pipeline rules (SpinDine)
- `.claude/conventions/approval-gates.md` — agent tier system (Jarvis)
