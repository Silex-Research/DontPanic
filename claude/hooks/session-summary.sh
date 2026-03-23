#!/bin/bash
# Session summary — extracts semantic context to breadcrumb on session end
# Hook: Stop (async, best-effort)

INPUT=$(cat)
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

if [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ]; then
  exit 0
fi

# Count messages to decide if session was substantial
MSG_COUNT=$(wc -l < "$TRANSCRIPT" 2>/dev/null || echo "0")
if [ "$MSG_COUNT" -lt 15 ]; then
  exit 0
fi

# Determine the correct project memory directory based on CWD
if [ -n "$CWD" ]; then
  # Convert path to Claude's project directory format: /a/b/c → -a-b-c
  PROJECT_KEY=$(echo "$CWD" | sed 's|/|-|g')
  MEMORY_DIR="$HOME/.claude/projects/${PROJECT_KEY}/memory"
else
  MEMORY_DIR="$HOME/.claude/projects/-Users-bayesian-Documents-GitHub/memory"
fi

# Ensure memory directory exists
mkdir -p "$MEMORY_DIR" 2>/dev/null || true

TIMESTAMP=$(date +%Y-%m-%d_%H%M)

# Extract semantic context from transcript
# Look for key signals: tool calls (Edit/Write = files changed), errors, decisions
FILES_CHANGED=""
if command -v jq >/dev/null 2>&1; then
  # Count distinct files edited/written (tool_name: Edit or Write)
  FILES_CHANGED=$(grep -o '"file_path":"[^"]*"' "$TRANSCRIPT" 2>/dev/null | sort -u | head -10 | sed 's/"file_path":"//;s/"$//' | while read -r f; do basename "$f" 2>/dev/null; done | paste -sd ", " -)
fi

# Extract git activity if in a repo
GIT_SUMMARY=""
if [ -n "$CWD" ] && [ -d "$CWD/.git" ]; then
  # Commits made during this session (last 2 hours)
  RECENT_COMMITS=$(git -C "$CWD" log --oneline --since="2 hours ago" 2>/dev/null | head -5)
  if [ -n "$RECENT_COMMITS" ]; then
    GIT_SUMMARY="Commits: ${RECENT_COMMITS}"
  fi

  # Current branch
  BRANCH=$(git -C "$CWD" branch --show-current 2>/dev/null)
  if [ -n "$BRANCH" ]; then
    GIT_SUMMARY="Branch: ${BRANCH}. ${GIT_SUMMARY}"
  fi

  # Uncommitted changes count
  DIRTY=$(git -C "$CWD" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  if [ "$DIRTY" -gt 0 ]; then
    GIT_SUMMARY="${GIT_SUMMARY} Uncommitted: ${DIRTY} files."
  fi
fi

# Build structured breadcrumb
cat > "$MEMORY_DIR/.last_session_breadcrumb" <<BREADCRUMB
Session: ${TIMESTAMP}
Transcript: ${TRANSCRIPT} (~${MSG_COUNT} lines)
Working Dir: ${CWD:-unknown}
${GIT_SUMMARY:+Git: ${GIT_SUMMARY}}
${FILES_CHANGED:+Files touched: ${FILES_CHANGED}}
BREADCRUMB

exit 0
