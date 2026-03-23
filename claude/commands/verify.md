---
description: Universal verification loop — build, type-check, lint, test, security scan, diff review
argument-hint: [--skip-tests] [--skip-security]
---

# Verify — Universal Build & Quality Check

Run a full verification pipeline for the current project. Auto-detect the project type and run all applicable checks.

## Steps

1. **Detect project type** by checking for:
   - `package.json` → Node/TypeScript project (npm/pnpm/yarn)
   - `Package.swift` or `*.xcodeproj` → Swift/iOS project
   - `pyproject.toml` or `setup.py` → Python project
   - `Gemfile` → Ruby project
   - `Cargo.toml` → Rust project
   - `go.mod` → Go project

2. **Build** — Run the project's build command:
   - Node: `npm run build` or `npx tsc --noEmit`
   - Swift: `xcodebuild -scheme <scheme> build` or `swift build`
   - Python: `uv run python -m py_compile` on changed files
   - Ruby: `bundle exec ruby -c` on changed files

3. **Type check** (if separate from build):
   - TypeScript: `npx tsc --noEmit`
   - Python: `mypy` or `pyright` if configured

4. **Lint**:
   - Node: `npx eslint .` or project-configured linter
   - Swift: `swiftlint lint` if available
   - Python: `ruff check .` or `flake8`
   - Ruby: `bundle exec rubocop` if available

5. **Test** (skip if `$ARGUMENTS` contains `--skip-tests`):
   - Node: `npm test` or `npx vitest run`
   - Swift: `xcodebuild test` or `swift test`
   - Python: `pytest` or `uv run pytest`
   - Ruby: `bundle exec rspec` or `bundle exec rake test`

6. **Security scan** (skip if `$ARGUMENTS` contains `--skip-security`):
   - Check for secrets in staged files (grep for API keys, tokens, passwords)
   - Node: `npm audit --production` if available
   - Python: `pip-audit` if available

7. **Diff review** — Review `git diff` for:
   - Console.log / print statements left in
   - TODO/FIXME without ticket references
   - Commented-out code blocks
   - Large files that shouldn't be committed

8. **Report** — Output a structured summary:
   ```
   VERIFY REPORT — <project name>
   ================================
   Build:     PASS | FAIL (details)
   Types:     PASS | FAIL | SKIP
   Lint:      PASS | FAIL (N warnings, M errors)
   Tests:     PASS | FAIL (X/Y passed) | SKIP
   Security:  PASS | WARN (details) | SKIP
   Diff:      CLEAN | WARN (details)
   ================================
   OVERALL:   PASS | FAIL
   ```
