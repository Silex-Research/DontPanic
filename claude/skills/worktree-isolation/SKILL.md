---
name: worktree-isolation
description: Git worktree-based task isolation. Use when making changes that should not affect the main working tree until verified, or when running parallel development tasks that might conflict.
---

# Worktree Isolation — Clean Branches for Every Task

Use git worktrees to isolate development tasks. Each task gets its own working
directory with its own branch, keeping `main` and the primary worktree clean.

## When to Use

- Multi-step feature work that might need to be abandoned
- Parallel tasks that touch overlapping files
- Experimental changes you want to evaluate before merging
- Subagent-driven development (each subagent gets a worktree)
- Any change where "undo everything" should be trivial

## When to Skip

- Single-file edits or config changes
- Changes you're confident about (bug fix with known root cause)
- The repo doesn't use git

## Protocol

### 1. Create Worktree

```bash
# From the repo root
git worktree add -b feature/<task-name> ../worktrees/<repo>-<task-name>
```

Naming convention:
- Branch: `feature/<task-name>` or `fix/<task-name>`
- Directory: `../worktrees/<repo-name>-<task-name>`

### 2. Bootstrap Environment

Detect and install dependencies:
- `package.json` → `npm install` or `npm ci`
- `Package.swift` → `swift package resolve`
- `pyproject.toml` → `uv sync` or `pip install -e .`
- `Gemfile` → `bundle install`
- `go.mod` → `go mod download`

Run baseline tests to confirm the worktree is healthy before making changes.

### 3. Do the Work

- Make changes in the worktree directory
- Commit frequently with descriptive messages
- Run tests after each significant change

### 4. Verify Before Merging

Before merging back:
1. Run the full test suite in the worktree
2. `git diff main...HEAD` to review all changes
3. Check for unintended files (build artifacts, `.DS_Store`, etc.)

### 5. Merge and Clean Up

```bash
# From the main worktree
git merge feature/<task-name>
# If clean:
git worktree remove ../worktrees/<repo>-<task-name>
git branch -d feature/<task-name>
```

If the merge has conflicts, resolve them in the main worktree (not the feature worktree).

### 6. Abandoning Work

If the task didn't work out:
```bash
git worktree remove --force ../worktrees/<repo>-<task-name>
git branch -D feature/<task-name>
```

## Integration with Subagent-Driven Development

When dispatching subagents, use `isolation: "worktree"` in the Agent tool call.
Claude Code handles worktree creation and cleanup automatically. The subagent
works in an isolated copy and its branch is returned in the result.

## Anti-Patterns

- Creating worktrees for trivial changes (overhead isn't worth it)
- Leaving stale worktrees around — clean up after merge or abandon
- Making changes in both the main worktree and feature worktree for the same files
- Forgetting to install dependencies in the new worktree
