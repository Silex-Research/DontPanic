---
description: Review staged or recent changes for quality, security, and standards
argument-hint: [--staged | --last-commit | --branch]
---

# Code Review — Pre-Commit Quality Gate

Review code changes for issues before committing.

## Scope

Determine what to review based on `$ARGUMENTS`:
- `--staged` or default: `git diff --staged`
- `--last-commit`: `git diff HEAD~1`
- `--branch`: `git diff main...HEAD` (all changes on current branch)

## Checklist

### MUST-FIX (block commit)
- [ ] Secrets, API keys, tokens, passwords in code
- [ ] SQL injection, XSS, command injection, path traversal
- [ ] Hardcoded credentials or URLs that should be config
- [ ] Missing error handling on external calls (network, DB, file I/O)
- [ ] Breaking changes to public APIs without version bump
- [ ] Race conditions or data corruption risks

### SHOULD-FIX (fix before merge)
- [ ] Console.log / print / debugPrint left in production code
- [ ] TODO/FIXME without a ticket reference
- [ ] Commented-out code blocks (delete or restore, don't leave)
- [ ] Missing null/undefined checks on external data
- [ ] Type safety gaps (any, as!, force unwrap without guard)
- [ ] Missing test coverage for new logic branches

### NIT (optional improvements)
- [ ] Naming could be clearer
- [ ] Duplicated logic that could be extracted
- [ ] Import ordering
- [ ] Unnecessary complexity

## Output Format

```
CODE REVIEW — <branch> (<N files changed>)
============================================

MUST-FIX (N):
  1. [file:line] Description
  2. [file:line] Description

SHOULD-FIX (N):
  1. [file:line] Description

NIT (N):
  1. [file:line] Description

VERDICT: APPROVE | REQUEST CHANGES
```
