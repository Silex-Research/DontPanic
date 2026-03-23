#!/bin/bash
set -euo pipefail

# sync-harness.sh — Mirror ~/.claude/ config into other AI harness formats
# Usage: ~/.claude/scripts/sync-harness.sh [--dry-run]
#
# Mirrors skills, rules, and commands from the canonical ~/.claude/ directory
# into equivalent directories for Cursor, Codex, and OpenCode.
# Uses symlinks where possible, copies where format differs.

CLAUDE_DIR="$HOME/.claude"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  echo "DRY RUN — no changes will be made"
fi

sync_file() {
  local src="$1"
  local dst="$2"

  if $DRY_RUN; then
    echo "  WOULD: $src → $dst"
    return
  fi

  mkdir -p "$(dirname "$dst")"

  # Use symlink if target doesn't exist or is already a symlink
  if [[ -L "$dst" ]] || [[ ! -e "$dst" ]]; then
    ln -sf "$src" "$dst"
    echo "  LINK: $src → $dst"
  else
    echo "  SKIP: $dst exists and is not a symlink (won't overwrite)"
  fi
}

copy_with_transform() {
  local src="$1"
  local dst="$2"
  local transform="$3"

  if $DRY_RUN; then
    echo "  WOULD COPY+TRANSFORM: $src → $dst"
    return
  fi

  mkdir -p "$(dirname "$dst")"

  if [[ "$transform" == "strip-frontmatter" ]]; then
    # Remove YAML frontmatter (--- to ---) for harnesses that don't support it
    sed '1{/^---$/!q;};1,/^---$/d' "$src" > "$dst"
    echo "  COPY: $src → $dst (frontmatter stripped)"
  else
    cp "$src" "$dst"
    echo "  COPY: $src → $dst"
  fi
}

echo "=== Syncing Claude Code config to other harnesses ==="
echo ""

# --- Cursor ---
CURSOR_DIR="$HOME/.cursor"
echo "→ Cursor ($CURSOR_DIR/rules/)"
if [[ -d "$CURSOR_DIR" ]] || $DRY_RUN; then
  for rule in "$CLAUDE_DIR"/rules/*.md; do
    [[ -f "$rule" ]] || continue
    name=$(basename "$rule")
    sync_file "$rule" "$CURSOR_DIR/rules/$name"
  done
else
  echo "  SKIP: $CURSOR_DIR not found"
fi
echo ""

# --- Codex / .agents ---
AGENTS_DIR="$HOME/.agents"
echo "→ Agents standard ($AGENTS_DIR/)"
for skill_dir in "$CLAUDE_DIR"/skills/*/; do
  [[ -d "$skill_dir" ]] || continue
  skill_name=$(basename "$skill_dir")
  skill_file="$skill_dir/SKILL.md"
  [[ -f "$skill_file" ]] || continue
  sync_file "$skill_file" "$AGENTS_DIR/skills/$skill_name/SKILL.md"
done
echo ""

# --- Rules to .agents ---
echo "→ Agents rules ($AGENTS_DIR/rules/)"
for rule in "$CLAUDE_DIR"/rules/*.md; do
  [[ -f "$rule" ]] || continue
  name=$(basename "$rule")
  sync_file "$rule" "$AGENTS_DIR/rules/$name"
done
echo ""

# --- Summary ---
echo "=== Sync complete ==="
echo ""
echo "Portable formats used:"
echo "  - Skills: Markdown with YAML frontmatter (Agent Skills standard)"
echo "  - Rules: Markdown with globs frontmatter"
echo "  - Commands: Markdown with argument-hint frontmatter"
echo ""
echo "Claude-specific features (not mirrored):"
echo "  - Hooks (settings.json) — no equivalent in other harnesses"
echo "  - Teams — Claude Code specific"
echo "  - Memory system — Claude Code specific"
echo "  - MCP server config — varies by harness"
