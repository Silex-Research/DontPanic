---
name: plan-artifacts
description: Structured artifact trail for plans, brainstorms, and solutions. Automatically triggered when creating plans or documenting learnings. Writes artifacts to docs/plans/, docs/brainstorms/, and docs/solutions/ so knowledge compounds across sessions.
---

# Plan Artifacts — Structured Knowledge Trail

When creating plans, brainstorms, or documenting solutions, write them as dated
markdown files in a structured directory hierarchy. This creates a searchable
knowledge base that compounds over time.

## Directory Convention

```
docs/
├── plans/          # Implementation plans (from /plan or brainstorm output)
├── brainstorms/    # Design explorations and requirements (from brainstorm-gate)
└── solutions/      # Learnings and solutions to past problems (post-implementation)
```

If `docs/` doesn't exist at the repo root, create it.

## When to Write Artifacts

### Plans (`docs/plans/`)
Write when:
- Running `/plan` or creating an implementation plan
- A brainstorm concludes with an approved approach

Format: `YYYY-MM-DD-NNN-<type>-<name>-plan.md`
- `NNN`: zero-padded sequence number for the day (001, 002, ...)
- `type`: feat, fix, refactor, migration, infra
- `name`: kebab-case short name

```markdown
---
title: <descriptive title>
type: feat|fix|refactor|migration|infra
status: active|completed|abandoned
date: YYYY-MM-DD
---

# <Title>

## Problem / Motivation
## Proposed Solution
## Files to Touch
## Steps
- [ ] Step 1
- [ ] Step 2
## Acceptance Criteria
## Risks
```

### Brainstorms (`docs/brainstorms/`)
Write when:
- The brainstorm-gate skill activates and options are explored
- A design discussion produces requirements

Format: `YYYY-MM-DD-<topic>-requirements.md`

### Solutions (`docs/solutions/`)
Write when:
- A non-obvious bug is fixed (capture the root cause and fix for future reference)
- A pattern is discovered that should inform future work
- A technology decision is made with important context

Format: `YYYY-MM-DD-<topic>.md`

```markdown
---
title: <what was solved>
tags: [relevant, tags]
date: YYYY-MM-DD
---

# <Title>

## Problem
## Root Cause
## Solution
## Key Learnings
## References
```

## Rules

- Always check `docs/solutions/` before planning — a prior solution may apply
- Update plan status to `completed` or `abandoned` when done
- Solutions should capture the *why*, not just the *what* — future you needs context
- Keep artifacts concise — a 20-line solution doc beats a 200-line one nobody reads
- Never delete artifacts — they're the project's institutional memory
