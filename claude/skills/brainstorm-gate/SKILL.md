---
name: brainstorm-gate
description: Design-first gate that prevents premature implementation. Use when the task is ambiguous, has multiple valid approaches, or the user hasn't specified how something should work. Forces clarification before any code is written.
---

# Brainstorm Gate — Design Before Code

When a task is ambiguous or has multiple valid approaches, brainstorm the design
with the user BEFORE writing any code. No implementation until the design is approved.

## When This Activates

- User describes a feature without specifying the approach
- Multiple valid architectures exist (and choosing wrong is expensive)
- The task touches 3+ files or introduces a new pattern
- You find yourself making assumptions about behavior
- The phrase "it depends" applies to the implementation

## When to Skip

- Bug fix with a clear root cause
- User gave explicit, unambiguous instructions
- Mechanical task (rename, move, update config)
- Single-file change with obvious implementation

## Protocol

### 1. Clarify the Problem

Before proposing solutions, confirm you understand:
- **What** the user wants (observable behavior, not implementation)
- **Why** they want it (the motivation shapes the solution)
- **Constraints** (performance, compatibility, timeline, existing patterns)

Ask at most 2-3 focused questions. Don't interrogate.

### 2. Propose Options

Present 2-3 approaches, each with:
- **One-line summary** of the approach
- **Pros**: why you'd choose this
- **Cons**: what you'd give up
- **Effort**: relative complexity (low / medium / high)

Lead with your recommendation and say why.

### 3. Wait for Approval

Do NOT proceed to implementation until the user explicitly picks an approach
or says "go ahead." Silence or ambiguity means "wait."

Valid approval signals:
- "Option 2" / "Go with B" / "The second one"
- "Sounds good" / "Do it" / "Go ahead"
- "Your call" (use your recommendation)

NOT approval:
- "Interesting" / "Hmm" / "What about..." (they're still thinking)
- No response (they may be away)

### 4. Record the Decision

After approval, briefly state what you're about to do:
> "Building option 2: [one-line summary]. Starting with [first step]."

This is the contract. If the implementation drifts from this, stop and re-check.

## Anti-Patterns

- Presenting 5+ options (analysis paralysis — pick the best 2-3)
- Writing code "just to explore" before approval
- Asking questions you could answer by reading the codebase
- Brainstorming trivial decisions (don't ask whether to use `const` vs `let`)
