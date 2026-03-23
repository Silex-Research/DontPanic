---
description: Iteratively fix build errors until the project compiles clean
argument-hint: [build command override]
---

# Build-Fix — Iterative Build Error Resolution

Run the build, capture errors, fix them one at a time, and repeat until clean.

## Protocol

1. **Detect build command** (or use `$ARGUMENTS` if provided):
   - `package.json` with `build` script → `npm run build`
   - `tsconfig.json` → `npx tsc --noEmit`
   - `*.xcodeproj` or `Package.swift` → `xcodebuild -scheme <scheme> build`
   - `pyproject.toml` → `uv run python -m compileall src/`
   - `Gemfile` → `bundle exec ruby -c`

2. **Run build**, capture stderr/stdout

3. **If build succeeds** → report success and stop

4. **If build fails**:
   - Parse the FIRST error (not all errors — fix one at a time to avoid cascading confusion)
   - Read the file at the error location
   - Fix the error
   - Go to step 2

5. **Safety limits**:
   - Max 20 iterations per run
   - If the same error appears 3 times, stop and report — it likely needs human judgment
   - If error count increases after a fix, revert the change and try a different approach

6. **Report** when done:
   ```
   BUILD-FIX REPORT
   ================
   Iterations: N
   Errors fixed: M
   Status: CLEAN | STUCK (details)
   ```
