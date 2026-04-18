# Skill Conformance Standard

Every skill file (`.claude/commands/*.md`) must meet these requirements to pass validation.

## Required Structure

```markdown
---
name: skill-name
description: One-line description of what this skill does
trigger_keywords: [keyword1, keyword2]
file_patterns: ["glob/pattern/**/*.ts"]
applicable_agents: [all] or [Backend-Engineer, QA-Reviewer]
phase: pre-commit | post-edit | on-demand
---

# Skill Name

## Purpose
One paragraph explaining when and why to use this skill.

## Arguments
| Argument | Required | Description |
|---|---|---|
| `target` | yes | File or directory to operate on |
| `--verbose` | no | Show detailed output |

If no arguments: write "None — operates on current context."

## Prerequisites
Conventions or context to read before executing. Reference shared conventions:
- See `.claude/shared/conventions/security.md` for auth patterns
- See `.claude/shared/conventions/testing-hierarchy.md` for mock boundaries

If no prerequisites: write "None."

## Steps
1. **Step name** — what to do
2. **Step name** — what to do
3. **Step name** — what to do

## Output
What the skill produces: a report, modified files, console output, etc.

## Examples
At least one usage example showing invocation and expected behavior.
```

## Frontmatter Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | yes | string | Matches filename without `.md`. Kebab-case. |
| `description` | yes | string | Under 80 chars. Used by resolver for disambiguation. |
| `trigger_keywords` | yes | string[] | Keywords that match this skill in intent-trigger resolver rows |
| `file_patterns` | no | string[] | Glob patterns for file-pattern resolver rows. Omit for intent-only skills. |
| `applicable_agents` | yes | string[] | `[all]` or list of agent roles that should invoke this skill |
| `phase` | yes | string | When this skill fires: `pre-commit`, `post-edit`, `post-merge`, or `on-demand` |

## Validation Checks

The validator enforces:

1. **Frontmatter present** — YAML frontmatter block exists with all required fields
2. **Name matches filename** — `name` field equals the filename (without `.md`)
3. **Required sections exist** — Purpose, Arguments, Steps, Output headings present
4. **Convention references** — if the skill body mentions security, testing, error handling, or naming topics, it must reference the relevant convention file rather than inlining rules
5. **Resolver registration** — the skill's `trigger_keywords` or `file_patterns` appear in RESOLVER.md
6. **No orphan skills** — every skill file in the directory has a corresponding resolver entry

## Anti-Patterns

- **Inlined conventions** — don't restate "use enforceAppCheck: true" in the skill; reference `conventions/firestore-security.md`
- **Missing arguments section** — even "None" is required so agents know the skill takes no input
- **Vague trigger keywords** — "check" alone matches too broadly; use "check security" or "security audit"
- **God skills** — a skill that does search + enrich + publish + deploy is too broad; split by responsibility
