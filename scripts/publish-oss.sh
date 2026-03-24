#!/bin/bash
set -euo pipefail

# publish-oss.sh — Syncs Jarvis private repo → Jarvis-OSS public repo
#
# What it does:
#   1. Copies all code from private to public
#   2. Replaces real state data with demo templates
#   3. Strips sensitive configs (.firebaserc, real settings)
#   4. Adds setup instructions for new users
#   5. Commits and pushes to public repo
#
# Usage: ./scripts/publish-oss.sh [--dry-run]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRIVATE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PUBLIC_DIR="$PRIVATE_DIR/../Jarvis-OSS"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  echo "[DRY RUN] No changes will be made"
fi

if [[ ! -d "$PUBLIC_DIR/.git" ]]; then
  echo "Error: Jarvis-OSS not found at $PUBLIC_DIR"
  echo "Clone it first: gh repo clone Silex-Research/Jarvis-OSS ../Jarvis-OSS"
  exit 1
fi

echo "=== Publishing Jarvis → Jarvis-OSS ==="
echo "  Private: $PRIVATE_DIR"
echo "  Public:  $PUBLIC_DIR"
echo ""

# ── Step 1: Clean public dir (preserve .git) ──
echo "→ Cleaning public directory..."
if ! $DRY_RUN; then
  find "$PUBLIC_DIR" -mindepth 1 -maxdepth 1 -not -name '.git' -exec rm -rf {} +
fi

# ── Step 2: Copy code (excluding sensitive files) ──
echo "→ Copying code..."

# Files/dirs to EXCLUDE from public
EXCLUDE=(
  ".git"
  "node_modules"
  "package-lock.json"
  ".firebaserc"
  "dashboard/state"
  "dashboard/node_modules"
  "dashboard/package-lock.json"
  "scripts/refresh-costs.sh"
  "scripts/publish-oss.sh"
  "claude/settings.json"
  "claude/hooks"
  "claude/scripts"
  "claude/registry"
  "codex/config.toml"
  "gemini/settings.json"
  ".claude"
  ".firebase"
  "USER.md"
)

RSYNC_EXCLUDES=""
for exc in "${EXCLUDE[@]}"; do
  RSYNC_EXCLUDES="$RSYNC_EXCLUDES --exclude=$exc"
done

if ! $DRY_RUN; then
  rsync -a $RSYNC_EXCLUDES "$PRIVATE_DIR/" "$PUBLIC_DIR/"
fi

# ── Step 3: Write demo state files ──
echo "→ Writing demo state files..."

if ! $DRY_RUN; then
  mkdir -p "$PUBLIC_DIR/dashboard/state"

  cat > "$PUBLIC_DIR/dashboard/state/agents.json" << 'AGENTS'
[
  {
    "id": "claude",
    "name": "Claude Code",
    "role": "Primary AI Harness",
    "status": "online",
    "currentTask": "Building features",
    "lastSeen": "2026-03-23T12:00:00Z",
    "tokensUsed": 450000,
    "tokenBudget": 1000000
  },
  {
    "id": "codex",
    "name": "Codex CLI",
    "role": "OpenAI Agent",
    "status": "offline",
    "currentTask": null,
    "lastSeen": null,
    "tokensUsed": 0,
    "tokenBudget": 500000
  },
  {
    "id": "gemini",
    "name": "Gemini CLI",
    "role": "Google Agent",
    "status": "offline",
    "currentTask": null,
    "lastSeen": null,
    "tokensUsed": 0,
    "tokenBudget": 500000
  }
]
AGENTS

  cat > "$PUBLIC_DIR/dashboard/state/tasks.json" << 'TASKS'
[
  {
    "id": "demo-1",
    "title": "Set up Jarvis dashboard",
    "project": "infra",
    "status": "in_progress",
    "priority": "high",
    "agent": "claude",
    "created": "2026-03-23T12:00:00Z"
  },
  {
    "id": "demo-2",
    "title": "Connect BigQuery billing",
    "project": "infra",
    "status": "todo",
    "priority": "medium",
    "agent": null,
    "created": "2026-03-23T12:00:00Z"
  }
]
TASKS

  cat > "$PUBLIC_DIR/dashboard/state/activity.json" << 'ACTIVITY'
[
  {
    "type": "task",
    "text": "Dashboard deployed successfully",
    "agent": "claude",
    "timestamp": "2026-03-23T12:00:00Z"
  }
]
ACTIVITY

  cat > "$PUBLIC_DIR/dashboard/state/costs.json" << 'COSTS'
{
  "generated": null,
  "totals": { "App 1": 0, "App 2": 0, "Total": 0 },
  "breakdown": [],
  "trend": []
}
COSTS

  cat > "$PUBLIC_DIR/dashboard/state/security.json" << 'SECURITY'
[]
SECURITY
fi

# ── Step 4: Write template configs ──
echo "→ Writing template configs..."

if ! $DRY_RUN; then
  cat > "$PUBLIC_DIR/.firebaserc" << 'FIREBASERC'
{
  "projects": {
    "default": "YOUR_FIREBASE_PROJECT_ID"
  }
}
FIREBASERC

  # Template refresh-costs script
  mkdir -p "$PUBLIC_DIR/scripts"
  cat > "$PUBLIC_DIR/scripts/refresh-costs.sh" << 'COSTS_SCRIPT'
#!/bin/bash
set -euo pipefail

# refresh-costs.sh — Template for populating dashboard/state/costs.json
#
# Prerequisites:
#   1. Install gcloud CLI: https://cloud.google.com/sdk/docs/install
#   2. Authenticate: gcloud auth login
#   3. Update the BigQuery table names below to match your billing export
#
# Setup:
#   1. Enable billing export in GCP Console → Billing → Billing export
#   2. Note your dataset and table names
#   3. Replace the placeholder values below
#   4. Run: ./scripts/refresh-costs.sh

# ── CONFIGURE THESE ──
BILLING_PROJECT="YOUR_BILLING_PROJECT"
BILLING_TABLE="YOUR_DATASET.YOUR_TABLE"
# If you have multiple billing accounts, add more UNION ALL blocks

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_FILE="$SCRIPT_DIR/../dashboard/state/costs.json"

echo "Fetching billing data from BigQuery..."
echo ""
echo "NOTE: Update the BigQuery table references in this script first."
echo "See: https://cloud.google.com/billing/docs/how-to/export-data-bigquery"
echo ""

# Example query — customize for your project structure:
# bq query --project_id=$BILLING_PROJECT --use_legacy_sql=false --format=json \
# "SELECT project.id AS project, ROUND(SUM(cost), 2) AS cost
#  FROM \`$BILLING_TABLE\`
#  WHERE invoice.month = FORMAT_DATE('%Y%m', CURRENT_DATE())
#  GROUP BY 1 ORDER BY cost DESC"

echo "Template script — edit scripts/refresh-costs.sh with your BigQuery details."
COSTS_SCRIPT
  chmod +x "$PUBLIC_DIR/scripts/refresh-costs.sh"
fi

# ── Step 5: Write public .gitignore ──
echo "→ Writing .gitignore..."

if ! $DRY_RUN; then
  cat > "$PUBLIC_DIR/.gitignore" << 'GITIGNORE'
# Dependencies
node_modules/
package-lock.json

# Environment & secrets
.env
.env.*
*.p12
*.pem
*.key

# OS artifacts
.DS_Store
Thumbs.db

# Session data
**/history.jsonl
**/debug/
**/*.sqlite
**/*.jsonl

# Harness auth (if you add real configs)
codex/auth.json
gemini/oauth_creds.json
gemini/state.json
GITIGNORE
fi

# ── Step 6: Commit and push ──
echo "→ Committing..."

if ! $DRY_RUN; then
  cd "$PUBLIC_DIR"
  git add -A

  CHANGES=$(git diff --cached --stat)
  if [[ -z "$CHANGES" ]]; then
    echo "No changes to publish."
    exit 0
  fi

  TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  git commit -m "sync: Update from private repo ($TIMESTAMP)" \
    --author="Jarvis Sync <noreply@silex.ai>"

  echo "→ Pushing to origin..."
  git push origin main 2>/dev/null || git push -u origin HEAD:main
fi

echo ""
echo "=== Published successfully ==="
echo "  Public repo: https://github.com/Silex-Research/Jarvis-OSS"
echo ""
echo "What's included:"
echo "  ✓ Dashboard code (all 6 pages)"
echo "  ✓ Lib modules + test suite"
echo "  ✓ Demo state data"
echo "  ✓ Template configs"
echo "  ✓ Setup instructions (README)"
echo ""
echo "What's excluded:"
echo "  ✗ Real billing data (state/costs.json)"
echo "  ✗ Firebase project config (.firebaserc)"
echo "  ✗ Harness settings (claude/settings.json)"
echo "  ✗ Hooks and scripts with credentials"
echo "  ✗ refresh-costs.sh (real BigQuery tables)"
