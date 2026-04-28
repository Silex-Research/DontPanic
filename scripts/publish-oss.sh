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

# Files/dirs to EXCLUDE from public.
# rsync ignores .gitignore by default — anything that's gitignored locally
# but exists on disk (environments.json, .secrets/, scripts/maintainer/, …)
# would otherwise leak into the public repo. List every such path here.
EXCLUDE=(
  # version control + dep caches
  ".git"
  "node_modules"
  "package-lock.json"
  ".firebase"
  # Firebase project alias — F022 untracked this; private maintainers
  # regenerate it via bootstrap.sh. Belt-and-suspenders even though the
  # file no longer exists in the tracked surface.
  ".firebaserc"
  ".firebaserc.example"
  # Per-repo environments registry — F022 untracked. Never publish.
  "environments.json"
  # Service account keys — gitignored, but rsync would copy.
  ".secrets"
  # Local env override files
  ".env"
  ".env.*"
  # Live dashboard state (replaced by demo writes in Step 3)
  "dashboard/state"
  "dashboard/node_modules"
  "dashboard/package-lock.json"
  # Maintainer-private scripts. F022 moved refresh-costs.sh under
  # scripts/maintainer/; keep the legacy single-file entry as a guard
  # in case anything else lands at the old path.
  "scripts/maintainer"
  "scripts/refresh-costs.sh"
  # The publish + private-side sanitizer themselves
  "scripts/publish-oss.sh"
  "scripts/sanitization_check.py"
  # Claude / Codex / Gemini local state
  "claude/settings.json"
  "claude/hooks"
  "claude/scripts"
  "claude/registry"
  "claude/projects"
  ".claude"
  "codex/config.toml"
  "codex/auth.json"
  "gemini/settings.json"
  "gemini/oauth_creds.json"
  "gemini/google_accounts.json"
  "gemini/state.json"
  "gemini/installation_id"
  "gemini/tmp"
  # Personal context
  "USER.md"
  # Private audit chain — D076–D079 contain campaign IDs by design
  # (sanitization_check allowlists docs/plans for the private repo).
  # The OSS mirror gets a curated narrative, not the verbatim history.
  "docs/plans"
  # Personal research + tracking artifacts
  "research"
  "tracking"
  "memory"
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

# ── Step 5b: Sanitization preflight on the public tree ──
# Scans the entire public dir (excluding .git) for the same campaign
# patterns sanitization_check.py guards in the private repo. The
# PUBLIC tree gets ZERO allowlist — plan dirs and campaign-private
# scripts must already be excluded above; if any pattern remains here,
# something slipped past EXCLUDE and we abort before commit.
echo "→ Running sanitization preflight on public tree..."

if ! $DRY_RUN; then
  # Patterns assembled from parts so this script doesn't match itself
  # when grep walks scripts/ inside the public copy (note: this script
  # itself is excluded, but defense in depth).
  PROJECT_PAT="jarvis-""a6ee1"
  BILLING_PAT="01EA42-""C7164E-""236F6E"
  USER_PAT="bil""otto"

  HITS=$(grep -rIln \
    -e "$PROJECT_PAT" \
    -e "$BILLING_PAT" \
    -e "$USER_PAT" \
    --exclude-dir=.git \
    "$PUBLIC_DIR" 2>/dev/null || true)

  if [[ -n "$HITS" ]]; then
    echo ""
    echo "ERROR: Sanitization preflight FAILED — the public tree contains" >&2
    echo "private patterns. Refusing to commit/push. Offending files:" >&2
    echo "" >&2
    echo "$HITS" >&2
    echo "" >&2
    echo "Fix: add the offending paths to EXCLUDE in scripts/publish-oss.sh," >&2
    echo "or sanitize the source file in the private repo, then re-run." >&2
    exit 1
  fi
  echo "  ✓ no private patterns in public tree"
else
  echo "  (skipped under --dry-run)"
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
echo "  ✗ Firebase project config (.firebaserc, .firebaserc.example)"
echo "  ✗ Per-repo environments registry (environments.json)"
echo "  ✗ Service account keys (.secrets/)"
echo "  ✗ Maintainer-private scripts (scripts/maintainer/, refresh-costs.sh)"
echo "  ✗ Harness settings + state (claude/, codex/, gemini/ local files)"
echo "  ✗ Private audit chain (docs/plans/)"
echo "  ✗ Personal research + tracking (research/, tracking/, memory/, USER.md)"
