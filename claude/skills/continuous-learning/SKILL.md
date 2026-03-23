---
name: continuous-learning
description: Extract reusable patterns and instincts from the current session. Saves learned behaviors with confidence scores that decay if contradicted. Complements the session-summary hook.
disable-model-invocation: true
argument-hint: [--review] [--prune]
---

# Continuous Learning — Extract Patterns from Sessions

You are a meta-learning agent. Your job is to extract reusable patterns from this session and save them as learned instincts.

## Modes

### Default — Extract and Save
Review the current conversation for patterns worth preserving:

1. **Error resolutions** — Problems encountered and how they were solved
   - Only save if the solution was non-obvious (not just "fix the typo")
   - Include the error signature so future sessions can match it

2. **User corrections** — Times the user redirected your approach
   - What you did wrong and what the right approach was
   - Why the user preferred the alternative

3. **Validated approaches** — Things that worked well (user confirmed or accepted)
   - What you did and why it worked
   - When to apply this approach again

4. **Workarounds** — Environment-specific tricks
   - macOS quirks, tool-specific flags, CI gotchas
   - Include version/context so it's clear when they apply

### `--review` — Review Existing Instincts
Read all files in `~/.claude/skills/learned/` and report:
- Total instincts by category
- Highest and lowest confidence
- Any that contradict each other
- Stale instincts (>30 days without reinforcement)

### `--prune` — Remove Low-Confidence Instincts
Delete instincts with confidence < 0.3 or older than 90 days without reinforcement.

## Instinct File Format

Save each instinct as `~/.claude/skills/learned/<category>_<slug>.md`:

```markdown
---
name: <short name>
description: <one-line description>
category: error_resolution | user_correction | validated_approach | workaround
confidence: 0.5
created: 2026-03-22
last_reinforced: 2026-03-22
reinforcement_count: 1
---

## Pattern
<What was observed>

## Response
<What to do when this pattern is seen>

## Context
<When this applies and when it doesn't>
```

## Confidence Scoring

| Event | Confidence Change |
|-------|-------------------|
| Initial extraction | 0.5 |
| User confirms approach works | +0.2 (max 0.95) |
| Same pattern seen in another session | +0.1 |
| User contradicts the instinct | -0.3 |
| 30 days without reinforcement | -0.1 |

## Rules

- Never save instincts about code structure or architecture — those belong in project CLAUDE.md files
- Never save things derivable from git log or current code — instincts are for tacit knowledge
- Keep instincts actionable — "prefer X over Y because Z", not "X is interesting"
- Max 50 instincts total — if at capacity, replace lowest-confidence ones
- When two instincts contradict, keep the more recently reinforced one
