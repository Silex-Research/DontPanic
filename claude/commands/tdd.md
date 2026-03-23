---
description: Test-driven development workflow — write failing test first, then implement
argument-hint: <description of what to implement>
---

# TDD — Test-Driven Development Workflow

Implement the feature or fix described in `$ARGUMENTS` using strict TDD.

## Protocol

### 1. Understand
- Read the target code and surrounding context
- Identify the test file (co-located `*.test.*`, `*Tests.swift`, `test_*.py`, or `*_spec.rb`)
- If no test file exists, create one following project conventions

### 2. Red — Write a Failing Test
- Write the simplest test that captures the desired behavior
- Run the test suite to confirm it FAILS
- If it passes, the behavior already exists — write a more specific test or stop

### 3. Green — Make It Pass
- Write the minimum code to make the test pass
- Do not add anything beyond what the test requires
- Run the test suite to confirm it PASSES

### 4. Refactor
- Clean up the implementation (remove duplication, improve naming)
- Run tests again to confirm they still pass
- Clean up the test if needed (but keep it readable)

### 5. Repeat
- If the feature needs more behavior, go back to step 2
- Stop when `$ARGUMENTS` is fully implemented

## The Iron Law

**No production code exists without a failing test that demands it.**

This is non-negotiable. If you catch yourself writing implementation before a test:
1. Stop immediately
2. Delete the implementation code
3. Write the failing test first
4. Re-implement only what the test requires

Common rationalizations that are NOT valid exceptions:
- "It's just a small change" — small changes get tests too
- "The test is obvious" — then it's fast to write
- "I'll add tests after" — no, the test comes first
- "This is just refactoring" — refactoring happens in step 4, after green
- "It's just a type/interface" — types don't need tests, but the code using them does

## Rules
- Never write implementation before a failing test
- Each red-green-refactor cycle should be small (1-3 minutes of work)
- If you're unsure what to test, test the public interface, not internals
- Auto-detect test framework: Vitest/Jest (TS/JS), XCTest (Swift), pytest (Python), RSpec/Minitest (Ruby)
- If tests pass on the first run without changes, the behavior already exists — investigate before proceeding
