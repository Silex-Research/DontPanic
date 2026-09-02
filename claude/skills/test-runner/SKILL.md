---
name: test-runner
description: Write and run tests in Silex repos. Use when adding tests, choosing a test framework, running a suite, or checking coverage in TypeScript/JavaScript, Python, or Swift projects.
---

# test-runner

Write and run tests across the languages Silex uses. The global rules (`~/.claude/rules/*.md`) set the red/green TDD workflow and per-language testing rules; this skill fixes the framework choices and the commands to run.

## Framework Selection

| Language | Unit Tests | Integration | E2E |
|----------|-----------|-------------|-----|
| TypeScript/JS | Vitest (preferred), Jest | Supertest | Playwright |
| Python | pytest | pytest + httpx | Playwright |
| Swift | XCTest | XCTest | XCUITest |

## Running

- Vitest: `npx vitest run` for a single run, `npx vitest --coverage` for coverage. Config lives in `vitest.config.ts`; use `environment: 'jsdom'` for component tests.
- pytest: `pytest -x --tb=short` while iterating; `pytest --cov=app --cov-fail-under=80` as the coverage gate.
- Swift packages: `swift test --filter <Suite>`. iOS app targets build and test through the named Xcode scheme (see proof-gated-cloud-agent), not `swift test`.
- Playwright: `npx playwright test`; add `--headed` or `--debug` when a flow needs watching.

## What to Test

Public behavior, edge cases (empty, null, boundaries), error paths, and business logic. Do not test private implementation details, framework internals, trivial accessors, or third-party libraries.
