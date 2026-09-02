---
name: subagent-driven-dev
description: Structured pattern for dispatching focused subagents per task with two-stage review. Use when implementing a plan with 3+ independent steps, or when parallelizable work spans multiple files/domains.
---

# Subagent-Driven Development (SDD)

Dispatch focused subagents for each task in an implementation plan, then review results
in two stages. This maximizes parallelism and keeps each agent's context small and precise.

## When to Use

- Implementing a plan with 3+ independent steps
- Changes that span multiple packages or domains (e.g., backend + frontend + tests)
- When tasks can be parallelized (no sequential dependency between them)
- Do NOT use for single-file changes or tightly coupled sequential work

## Protocol

### 1. Decompose

Break the work into independent, self-contained tasks. Each task must:
- Have a clear, measurable "done" condition
- Be completable without knowing the results of other tasks
- Touch a distinct set of files (no overlapping edits)

If tasks share files, they are NOT independent — sequence them instead.

### 2. Dispatch

For each independent task, launch a subagent with:
- **Precise instructions**: What to change, in which files, and what "done" looks like
- **Context-free**: Include all necessary context in the prompt — don't assume the subagent knows what you know
- **Test requirement**: Each subagent must write or update tests for its changes
- **Isolation**: Use `isolation: "worktree"` for tasks that modify overlapping build artifacts

Launch independent subagents in parallel (multiple Agent tool calls in one message).

### 3. Effort and Model Selection

Match effort to task complexity before reaching for a different model. On current Claude models, low effort on the flagship usually beats a smaller model on cost per completed task, and a mixed-model roster forfeits prompt-cache reuse (caches are model-scoped):
- **Mechanical** (rename, move, update imports, config changes): `low` effort (or the harness's `haiku` alias)
- **Straightforward** (add endpoint, write tests, implement known pattern): `medium` effort (or `sonnet`)
- **Complex** (architecture decisions, security-sensitive, novel algorithms): `high` or `xhigh` effort on the flagship (`opus` / `fable`)

### 4. Two-Stage Review

Do not block on the slowest subagent: review each result as it arrives and keep preparing integration while the others run. Once every result is in:

**Stage 1 — Spec Compliance** (can use a reviewer subagent):
- Does each result satisfy the original task description?
- Are all "done" conditions met?
- Are tests present and passing?

**Stage 2 — Code Quality**:
- No duplicated logic across subagent outputs
- Consistent naming and patterns
- No conflicting changes (e.g., two subagents modifying the same type differently)
- Integration points are correct (imports, type signatures, API contracts)

### 5. Integrate

- If using worktrees: merge each branch, resolving any conflicts
- Run the full test suite after integration
- If tests fail: diagnose whether it's a single subagent's issue or an integration issue

## Anti-Patterns

- Dispatching subagents for trivially small tasks (overhead > benefit)
- Giving subagents vague instructions ("improve the auth system")
- Dispatching dependent tasks in parallel (task B needs task A's output)
- Skipping the review stage because "it compiled"
- Running mechanical tasks at high effort (wasteful) or architecture at low effort (risky)

## Example Dispatch

```
Task: Implement user preferences API

Subagent 1 (medium effort): "Create UserPreferences type in packages/shared/types.ts
  with fields: theme (light|dark), locale (string), notifications (boolean).
  Export it from the package index. Write unit tests."

Subagent 2 (medium effort): "Add GET/PUT /api/preferences endpoints in
  packages/functions/src/preferencesApi.ts. Use Firestore collection
  'user_preferences' keyed by userId. Validate input with Zod.
  Write integration tests using the Firebase emulator."

Subagent 3 (low effort): "Add 'preferences' to the nav menu in
  packages/dashboard/src/components/Sidebar.tsx, linking to /preferences."
```
