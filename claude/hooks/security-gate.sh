#!/bin/bash
# Security gate — blocks edits to sensitive files
# Hook: PreToolUse → Edit|Write

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

BASENAME=$(basename "$FILE_PATH")
DIRNAME=$(dirname "$FILE_PATH")

# Sensitive file patterns
SENSITIVE_FILES=".env .env.local .env.production .env.staging credentials.json service-account.json serviceAccountKey.json secrets.yaml secrets.json keystore.jks .p12 .pem .key id_rsa id_ed25519 .netrc .npmrc"
SENSITIVE_DIRS=".secrets secrets credentials private-keys"

for PATTERN in $SENSITIVE_FILES; do
  case "$BASENAME" in
    $PATTERN|*"$PATTERN"*)
      jq -n '{
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: ("BLOCKED: Attempted edit to sensitive file: " + $path + ". Use the terminal directly if this is intentional.")
        }
      }' --arg path "$FILE_PATH"
      exit 0
      ;;
  esac
done

for DIR in $SENSITIVE_DIRS; do
  case "$DIRNAME" in
    *"/$DIR"*|*"/$DIR")
      jq -n '{
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: ("BLOCKED: Attempted edit to file in sensitive directory: " + $path)
        }
      }' --arg path "$FILE_PATH"
      exit 0
      ;;
  esac
done

exit 0
