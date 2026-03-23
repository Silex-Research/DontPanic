---
description: De-sloppify pass — remove noise from uncommitted changes while preserving business logic
argument-hint: [--dry-run]
---

# Cleanup — De-Sloppify Pass

Review all uncommitted changes and remove accumulated noise. Preserves all business logic.

## What Gets Removed

- `console.log`, `console.debug`, `print()`, `debugPrint()`, `NSLog` left from debugging
- Commented-out code blocks (if the code is needed, it's in git history)
- Unused imports and variables
- Tests that test language/framework behavior rather than your code
- Over-defensive nil checks on values that are guaranteed non-nil by the type system
- Empty catch blocks or catch blocks that only log
- Redundant type annotations the compiler can infer
- Trailing whitespace and inconsistent formatting

## What Gets Kept

- ALL business logic — even if it looks suboptimal, don't "improve" it here
- Comments that explain WHY (not WHAT)
- TODO/FIXME with ticket references
- Error handling on external boundaries
- Type annotations that aid readability

## Protocol

1. Run `git diff` to see all uncommitted changes
2. Read each changed file fully for context
3. If `$ARGUMENTS` contains `--dry-run`, list what would be removed without editing
4. Otherwise, make the edits
5. Run the project's test suite to verify nothing broke
6. Report what was removed

## Output

```
CLEANUP REPORT
==============
Removed: N items across M files
- 3x console.log (file1.ts, file2.ts)
- 2x commented-out code blocks (file3.swift)
- 1x unused import (file4.py)
Tests: PASS | FAIL
```
