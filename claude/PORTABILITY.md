# Portability Contract

This document describes which parts of the `~/.claude/` configuration are portable across AI coding harnesses and which are Claude Code-specific.

## Portable (Markdown + YAML Frontmatter)

These files follow a standard format that any harness can parse:

| Component | Location | Format | Portable Fields |
|-----------|----------|--------|-----------------|
| Skills | `skills/<name>/SKILL.md` | YAML frontmatter + markdown body | `name`, `description`, `argument-hint` |
| Rules | `rules/<lang>.md` | YAML frontmatter + markdown body | `globs`, `description` |
| Commands | `commands/<name>.md` | YAML frontmatter + markdown body | `description`, `argument-hint` |

### Frontmatter Fields — Portability Matrix

| Field | Claude Code | Cursor | Codex | OpenCode |
|-------|-------------|--------|-------|----------|
| `name` | Yes | — | Yes | Yes |
| `description` | Yes | Yes | Yes | Yes |
| `globs` | Yes (rules) | Yes (rules) | — | — |
| `argument-hint` | Yes | — | — | — |
| `disable-model-invocation` | Yes | — | — | — |
| `context` | Yes | — | — | — |
| `agent` | Yes | — | — | — |
| `model` | Yes | — | — | — |

### Body Content

The markdown body of skills, rules, and commands is universally portable. It's just instructions that any LLM can follow. The only Claude Code-specific content would be:
- References to Claude Code tool names (`Edit`, `Write`, `Bash`, `Glob`, `Grep`, `Agent`)
- References to Claude Code features (`TaskCreate`, `TaskUpdate`, `EnterPlanMode`)

These references are generally understood by other harnesses since the concepts map to their equivalents.

## Claude Code-Specific (Not Portable)

| Component | Location | Why Not Portable |
|-----------|----------|------------------|
| Hooks | `settings.json` → `hooks` | JSON schema is Claude Code-specific. Each harness has its own hook system. |
| Teams | `settings.json` → team config | Claude Code-specific agent teaming. |
| Memory | `projects/*/memory/` | File-based memory system with MEMORY.md index. Other harnesses have different persistence. |
| MCP Servers | `settings.json` → `mcpServers` | Config format varies. MCP protocol is standard but config isn't. |
| Plugins | `settings.json` → `enabledPlugins` | Claude Code plugin system. |
| Permissions | `settings.json` → `permissions` | Claude Code permission model. |

## Sync Script

Run `~/.claude/scripts/sync-harness.sh` to mirror portable files into other harness directories:
- `~/.cursor/rules/` — Cursor rules
- `~/.agents/skills/` — Agent Skills standard
- `~/.agents/rules/` — Agent Skills standard

Use `--dry-run` to preview changes without writing.

## Adding New Components

When adding new skills, rules, or commands:
1. Write them in the portable format (YAML frontmatter + markdown)
2. Keep Claude Code-specific features optional (mentioned but not required)
3. Run `sync-harness.sh` to propagate to other harnesses
4. Test in the target harness to verify compatibility
