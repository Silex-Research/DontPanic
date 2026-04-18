---
name: skill-name
description: One-line description (under 80 chars)
trigger_keywords: [keyword1, keyword2]
file_patterns: []
applicable_agents: [all]
phase: on-demand
---

# Skill Name

## Purpose
When and why to use this skill. One paragraph.

## Arguments
| Argument | Required | Description |
|---|---|---|
| `target` | yes | File or directory to operate on |

## Prerequisites
- See `.claude/shared/conventions/relevant-convention.md`

## Steps
1. **Read context** — understand the target files and current state
2. **Analyze** — apply the relevant checks or transformations
3. **Report** — output findings or apply changes

## Output
What this skill produces (report format, modified files, console output).

## Examples

```
/skill-name GlamSwift/ViewModels/StudioViewModel.swift
```

Expected: [describe expected output]
