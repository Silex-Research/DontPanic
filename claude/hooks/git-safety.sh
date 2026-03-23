#!/bin/bash
# Git safety — blocks destructive git commands unless FORCE=1
# Hook: PreToolUse → Bash

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Skip if FORCE override is set
if [ "$FORCE" = "1" ]; then
  exit 0
fi

BLOCKED=""

# Force push
if echo "$COMMAND" | grep -qE -e 'git\s+push\s+.*--force' -e 'git\s+push\s+-f\b'; then
  BLOCKED="git push --force"
fi

# Push to main/master
if echo "$COMMAND" | grep -qE -e 'git\s+push\s+.*\b(main|master)\b'; then
  BLOCKED="git push to main/master"
fi

# Reset hard
if echo "$COMMAND" | grep -qE -e 'git\s+reset\s+--hard'; then
  BLOCKED="git reset --hard"
fi

# Clean -f
if echo "$COMMAND" | grep -qE -e 'git\s+clean\s+-f'; then
  BLOCKED="git clean -f"
fi

# No-verify
if echo "$COMMAND" | grep -qE -e '\-\-no\-verify'; then
  BLOCKED="--no-verify (skipping hooks)"
fi

# Branch -D (force delete)
if echo "$COMMAND" | grep -qE -e 'git\s+branch\s+-D\b'; then
  BLOCKED="git branch -D (force delete)"
fi

# rm -rf with broad paths
if echo "$COMMAND" | grep -qE -e 'rm\s+-rf\s+(/|~|\.\.)'; then
  BLOCKED="rm -rf on broad path"
fi

if [ -n "$BLOCKED" ]; then
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: ("BLOCKED: Destructive command detected (" + $what + "). Set FORCE=1 to override.")
    }
  }' --arg what "$BLOCKED"
  exit 0
fi

exit 0
