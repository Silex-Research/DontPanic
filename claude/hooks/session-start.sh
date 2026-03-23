#!/bin/bash
# Session start — injects project context at every session start, clear, or compact
# Hook: SessionStart

set -euo pipefail

INPUT=$(cat)
WORKING_DIR=$(echo "$INPUT" | jq -r '.cwd // empty')

if [ -z "$WORKING_DIR" ]; then
  exit 0
fi

CONTEXT=""

# 1. Find and inject CLAUDE.md from the working directory (or nearest parent)
search_dir="$WORKING_DIR"
while [ "$search_dir" != "/" ]; do
  if [ -f "$search_dir/CLAUDE.md" ]; then
    CLAUDE_CONTENT=$(cat "$search_dir/CLAUDE.md" 2>/dev/null || true)
    if [ -n "$CLAUDE_CONTENT" ]; then
      CONTEXT="${CONTEXT}## Project Instructions (CLAUDE.md)\n${CLAUDE_CONTENT}\n\n"
    fi
    break
  fi
  search_dir=$(dirname "$search_dir")
done

# 2. Detect project type and inject relevant context
if [ -f "$WORKING_DIR/Package.swift" ] || [ -f "$WORKING_DIR/project.pbxproj" ]; then
  CONTEXT="${CONTEXT}## Detected: iOS/Swift project — apply Swift rules, MVVM, structured concurrency\n"
elif [ -f "$WORKING_DIR/package.json" ]; then
  PKG_TYPE="Node.js"
  if [ -f "$WORKING_DIR/wrangler.jsonc" ] || [ -f "$WORKING_DIR/wrangler.toml" ]; then
    PKG_TYPE="Cloudflare Worker"
  elif [ -f "$WORKING_DIR/firebase.json" ]; then
    PKG_TYPE="Firebase"
  elif [ -f "$WORKING_DIR/turbo.json" ]; then
    PKG_TYPE="Turborepo monorepo"
  fi
  CONTEXT="${CONTEXT}## Detected: ${PKG_TYPE} project — apply TypeScript rules\n"
elif [ -f "$WORKING_DIR/pyproject.toml" ] || [ -f "$WORKING_DIR/setup.py" ]; then
  CONTEXT="${CONTEXT}## Detected: Python project — apply Python rules, use uv\n"
elif [ -f "$WORKING_DIR/Gemfile" ] || [ -f "$WORKING_DIR/Fastfile" ]; then
  CONTEXT="${CONTEXT}## Detected: Ruby project — apply Ruby rules\n"
fi

# 3. Load recent session breadcrumb (per-project, with fallback to global)
PROJECT_KEY=$(echo "$WORKING_DIR" | sed 's|/|-|g')
MEMORY_DIR="$HOME/.claude/projects/${PROJECT_KEY}/memory"
GLOBAL_MEMORY_DIR="$HOME/.claude/projects/-Users-bayesian-Documents-GitHub/memory"

BREADCRUMB_FILE=""
if [ -f "$MEMORY_DIR/.last_session_breadcrumb" ]; then
  BREADCRUMB_FILE="$MEMORY_DIR/.last_session_breadcrumb"
elif [ -f "$GLOBAL_MEMORY_DIR/.last_session_breadcrumb" ]; then
  BREADCRUMB_FILE="$GLOBAL_MEMORY_DIR/.last_session_breadcrumb"
fi

if [ -n "$BREADCRUMB_FILE" ]; then
  BREADCRUMB=$(cat "$BREADCRUMB_FILE" 2>/dev/null || true)
  if [ -n "$BREADCRUMB" ]; then
    CONTEXT="${CONTEXT}## Previous Session\n${BREADCRUMB}\n\n"
  fi
fi

# 4. Check for uncommitted changes as a reminder
if command -v git >/dev/null 2>&1 && [ -d "$WORKING_DIR/.git" ]; then
  DIRTY_COUNT=$(git -C "$WORKING_DIR" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  if [ "$DIRTY_COUNT" -gt 0 ]; then
    CONTEXT="${CONTEXT}## Note: ${DIRTY_COUNT} uncommitted changes in working directory\n"
  fi
fi

# 5. Memory staleness check
# Scan project memory files and flag any older than 30 days
STALE_MEMORIES=""
for mem_dir in "$MEMORY_DIR" "$GLOBAL_MEMORY_DIR"; do
  if [ -d "$mem_dir" ]; then
    for mem_file in "$mem_dir"/*.md; do
      [ -f "$mem_file" ] || continue
      basename_file=$(basename "$mem_file")
      [ "$basename_file" = "MEMORY.md" ] && continue  # Index file, skip
      # Check file age (modified more than 30 days ago)
      if [ "$(uname)" = "Darwin" ]; then
        file_age_days=$(( ( $(date +%s) - $(stat -f %m "$mem_file") ) / 86400 ))
      else
        file_age_days=$(( ( $(date +%s) - $(stat -c %Y "$mem_file") ) / 86400 ))
      fi
      if [ "$file_age_days" -gt 30 ]; then
        STALE_MEMORIES="${STALE_MEMORIES}\n- ${basename_file} (${file_age_days} days old)"
      fi
    done
  fi
done

if [ -n "$STALE_MEMORIES" ]; then
  CONTEXT="${CONTEXT}## Stale Memories (>30 days — verify before relying on these)${STALE_MEMORIES}\n\n"
fi

# 6. Load cross-project entity registry if it exists
REGISTRY="$HOME/.claude/registry/entities.md"
if [ -f "$REGISTRY" ]; then
  REGISTRY_CONTENT=$(cat "$REGISTRY" 2>/dev/null || true)
  if [ -n "$REGISTRY_CONTENT" ]; then
    CONTEXT="${CONTEXT}## Cross-Project Entity Registry\n${REGISTRY_CONTENT}\n\n"
  fi
fi

# 7. Inject methodology reminders
CONTEXT="${CONTEXT}## Workflow Reminders\n"
CONTEXT="${CONTEXT}- For ambiguous tasks: brainstorm and clarify before coding\n"
CONTEXT="${CONTEXT}- For non-trivial implementations: create a plan first, validate with a reviewer subagent\n"
CONTEXT="${CONTEXT}- For features: use TDD — no production code without a failing test first\n"
CONTEXT="${CONTEXT}- For multi-file changes: consider using a git worktree for isolation\n"
CONTEXT="${CONTEXT}- Dispatch focused subagents for independent tasks when possible\n"

if [ -z "$CONTEXT" ]; then
  exit 0
fi

# Output as additionalContext for Claude Code
printf '%s' "$CONTEXT" | jq -Rs '{
  hookSpecificOutput: {
    additionalContext: .
  }
}'
