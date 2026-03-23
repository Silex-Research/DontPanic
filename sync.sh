#!/bin/bash
set -euo pipefail

# sync.sh — Bidirectional sync between Jarvis repo and AI harness configs
#
# Usage:
#   ./sync.sh pull    — Copy from live configs (~/.claude, ~/.codex, ~/.gemini) into Jarvis
#   ./sync.sh push    — Deploy from Jarvis into live configs
#   ./sync.sh status  — Show what's different between Jarvis and live configs
#   ./sync.sh --dry-run <command>  — Preview without changes

JARVIS_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
CODEX_DIR="$HOME/.codex"
GEMINI_DIR="$HOME/.gemini"
CURSOR_DIR="$HOME/.cursor"
AGENTS_DIR="$HOME/.agents"

DRY_RUN=false
ACTION="${1:-status}"

if [[ "$ACTION" == "--dry-run" ]]; then
  DRY_RUN=true
  ACTION="${2:-status}"
fi

sync_copy() {
  local src="$1"
  local dst="$2"
  local label="${3:-}"

  if [[ ! -f "$src" ]]; then
    return
  fi

  if $DRY_RUN; then
    if [[ -f "$dst" ]] && diff -q "$src" "$dst" >/dev/null 2>&1; then
      return  # identical, skip
    fi
    echo "  WOULD: $src → $dst"
    return
  fi

  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  echo "  SYNC: $(basename "$src") ${label:+($label)}"
}

sync_link() {
  local src="$1"
  local dst="$2"

  if $DRY_RUN; then
    echo "  WOULD LINK: $src → $dst"
    return
  fi

  mkdir -p "$(dirname "$dst")"
  ln -sf "$src" "$dst"
  echo "  LINK: $(basename "$src")"
}

case "$ACTION" in

  pull)
    echo "=== Pulling live configs into Jarvis ==="

    echo ""
    echo "→ Claude Code"
    # Rules
    for f in "$CLAUDE_DIR"/rules/*.md; do
      [[ -f "$f" ]] || continue
      sync_copy "$f" "$JARVIS_DIR/claude/rules/$(basename "$f")" "rule"
    done
    # Skills
    for skill_dir in "$CLAUDE_DIR"/skills/*/; do
      [[ -d "$skill_dir" ]] || continue
      skill_name=$(basename "$skill_dir")
      for f in "$skill_dir"*.md; do
        [[ -f "$f" ]] || continue
        mkdir -p "$JARVIS_DIR/claude/skills/$skill_name"
        sync_copy "$f" "$JARVIS_DIR/claude/skills/$skill_name/$(basename "$f")" "skill"
      done
    done
    # Commands
    for f in "$CLAUDE_DIR"/commands/*.md; do
      [[ -f "$f" ]] || continue
      sync_copy "$f" "$JARVIS_DIR/claude/commands/$(basename "$f")" "command"
    done
    # Hooks
    for f in "$CLAUDE_DIR"/hooks/*.sh; do
      [[ -f "$f" ]] || continue
      sync_copy "$f" "$JARVIS_DIR/claude/hooks/$(basename "$f")" "hook"
    done
    # Scripts
    for f in "$CLAUDE_DIR"/scripts/*.sh; do
      [[ -f "$f" ]] || continue
      sync_copy "$f" "$JARVIS_DIR/claude/scripts/$(basename "$f")" "script"
    done
    # Registry
    for f in "$CLAUDE_DIR"/registry/*.md; do
      [[ -f "$f" ]] || continue
      sync_copy "$f" "$JARVIS_DIR/claude/registry/$(basename "$f")" "registry"
    done
    # Settings (non-sensitive)
    sync_copy "$CLAUDE_DIR/settings.json" "$JARVIS_DIR/claude/settings.json" "settings"
    sync_copy "$CLAUDE_DIR/PORTABILITY.md" "$JARVIS_DIR/claude/PORTABILITY.md" "docs"

    echo ""
    echo "→ Codex"
    sync_copy "$CODEX_DIR/config.toml" "$JARVIS_DIR/codex/config.toml" "config"

    echo ""
    echo "→ Gemini CLI"
    sync_copy "$GEMINI_DIR/settings.json" "$JARVIS_DIR/gemini/settings.json" "settings"

    echo ""
    echo "=== Pull complete. Run 'git diff' to review changes. ==="
    ;;

  push)
    echo "=== Deploying Jarvis configs to live harnesses ==="

    echo ""
    echo "→ Claude Code"
    # Rules
    for f in "$JARVIS_DIR"/claude/rules/*.md; do
      [[ -f "$f" ]] || continue
      sync_copy "$f" "$CLAUDE_DIR/rules/$(basename "$f")" "rule"
    done
    # Skills
    for skill_dir in "$JARVIS_DIR"/claude/skills/*/; do
      [[ -d "$skill_dir" ]] || continue
      skill_name=$(basename "$skill_dir")
      for f in "$skill_dir"*.md; do
        [[ -f "$f" ]] || continue
        mkdir -p "$CLAUDE_DIR/skills/$skill_name"
        sync_copy "$f" "$CLAUDE_DIR/skills/$skill_name/$(basename "$f")" "skill"
      done
    done
    # Commands
    for f in "$JARVIS_DIR"/claude/commands/*.md; do
      [[ -f "$f" ]] || continue
      sync_copy "$f" "$CLAUDE_DIR/commands/$(basename "$f")" "command"
    done
    # Hooks
    for f in "$JARVIS_DIR"/claude/hooks/*.sh; do
      [[ -f "$f" ]] || continue
      sync_copy "$f" "$CLAUDE_DIR/hooks/$(basename "$f")" "hook"
      chmod +x "$CLAUDE_DIR/hooks/$(basename "$f")"
    done
    # Scripts
    for f in "$JARVIS_DIR"/claude/scripts/*.sh; do
      [[ -f "$f" ]] || continue
      sync_copy "$f" "$CLAUDE_DIR/scripts/$(basename "$f")" "script"
      chmod +x "$CLAUDE_DIR/scripts/$(basename "$f")"
    done
    # Registry
    for f in "$JARVIS_DIR"/claude/registry/*.md; do
      [[ -f "$f" ]] || continue
      mkdir -p "$CLAUDE_DIR/registry"
      sync_copy "$f" "$CLAUDE_DIR/registry/$(basename "$f")" "registry"
    done
    # Settings
    sync_copy "$JARVIS_DIR/claude/settings.json" "$CLAUDE_DIR/settings.json" "settings"

    echo ""
    echo "→ Codex"
    sync_copy "$JARVIS_DIR/codex/config.toml" "$CODEX_DIR/config.toml" "config"

    echo ""
    echo "→ Gemini CLI"
    sync_copy "$JARVIS_DIR/gemini/settings.json" "$GEMINI_DIR/settings.json" "settings"

    echo ""
    echo "→ Cross-harness sync (portable rules + skills)"
    # Cursor — rules
    if [[ -d "$CURSOR_DIR" ]]; then
      echo "  Cursor:"
      for f in "$JARVIS_DIR"/claude/rules/*.md; do
        [[ -f "$f" ]] || continue
        sync_link "$CLAUDE_DIR/rules/$(basename "$f")" "$CURSOR_DIR/rules/$(basename "$f")"
      done
    fi
    # Agents standard — skills + rules
    echo "  Agents standard (~/.agents/):"
    for skill_dir in "$JARVIS_DIR"/claude/skills/*/; do
      [[ -d "$skill_dir" ]] || continue
      skill_name=$(basename "$skill_dir")
      skill_file="$CLAUDE_DIR/skills/$skill_name/SKILL.md"
      [[ -f "$skill_file" ]] || continue
      sync_link "$skill_file" "$AGENTS_DIR/skills/$skill_name/SKILL.md"
    done
    for f in "$JARVIS_DIR"/claude/rules/*.md; do
      [[ -f "$f" ]] || continue
      sync_link "$CLAUDE_DIR/rules/$(basename "$f")" "$AGENTS_DIR/rules/$(basename "$f")"
    done

    echo ""
    echo "=== Push complete. All harnesses updated. ==="
    ;;

  status)
    echo "=== Jarvis ↔ Live Config Status ==="
    echo ""
    DIFFS=0

    echo "→ Claude Code"
    for f in "$JARVIS_DIR"/claude/rules/*.md "$JARVIS_DIR"/claude/commands/*.md "$JARVIS_DIR"/claude/hooks/*.sh "$JARVIS_DIR"/claude/scripts/*.sh "$JARVIS_DIR"/claude/registry/*.md "$JARVIS_DIR"/claude/settings.json; do
      [[ -f "$f" ]] || continue
      rel_path="${f#$JARVIS_DIR/claude/}"
      live_file="$CLAUDE_DIR/$rel_path"
      if [[ ! -f "$live_file" ]]; then
        echo "  MISSING in live: $rel_path"
        DIFFS=$((DIFFS + 1))
      elif ! diff -q "$f" "$live_file" >/dev/null 2>&1; then
        echo "  DIFFERS: $rel_path"
        DIFFS=$((DIFFS + 1))
      fi
    done

    for skill_dir in "$JARVIS_DIR"/claude/skills/*/; do
      [[ -d "$skill_dir" ]] || continue
      skill_name=$(basename "$skill_dir")
      for f in "$skill_dir"*.md; do
        [[ -f "$f" ]] || continue
        live_file="$CLAUDE_DIR/skills/$skill_name/$(basename "$f")"
        if [[ ! -f "$live_file" ]]; then
          echo "  MISSING in live: skills/$skill_name/$(basename "$f")"
          DIFFS=$((DIFFS + 1))
        elif ! diff -q "$f" "$live_file" >/dev/null 2>&1; then
          echo "  DIFFERS: skills/$skill_name/$(basename "$f")"
          DIFFS=$((DIFFS + 1))
        fi
      done
    done

    echo ""
    echo "→ Codex"
    if [[ -f "$JARVIS_DIR/codex/config.toml" ]] && [[ -f "$CODEX_DIR/config.toml" ]]; then
      if ! diff -q "$JARVIS_DIR/codex/config.toml" "$CODEX_DIR/config.toml" >/dev/null 2>&1; then
        echo "  DIFFERS: config.toml"
        DIFFS=$((DIFFS + 1))
      fi
    fi

    echo ""
    echo "→ Gemini CLI"
    if [[ -f "$JARVIS_DIR/gemini/settings.json" ]] && [[ -f "$GEMINI_DIR/settings.json" ]]; then
      if ! diff -q "$JARVIS_DIR/gemini/settings.json" "$GEMINI_DIR/settings.json" >/dev/null 2>&1; then
        echo "  DIFFERS: settings.json"
        DIFFS=$((DIFFS + 1))
      fi
    fi

    echo ""
    if [[ "$DIFFS" -eq 0 ]]; then
      echo "All configs in sync."
    else
      echo "$DIFFS difference(s) found. Run './sync.sh pull' or './sync.sh push' to resolve."
    fi
    ;;

  *)
    echo "Usage: $0 [--dry-run] <pull|push|status>"
    echo ""
    echo "  pull    — Copy from live configs into Jarvis repo"
    echo "  push    — Deploy from Jarvis into live configs"
    echo "  status  — Show differences between Jarvis and live"
    exit 2
    ;;
esac
