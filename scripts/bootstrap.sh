#!/bin/bash
# bootstrap.sh — One-shot bootstrap for a fresh DontPanic-on-Firebase setup.
#
# Codifies the gcloud + firebase steps that were originally executed by hand
# under sub-plan 2026-04-25-001-infra-jarvis-firebase-bootstrap. Required
# inputs are passed explicitly (no campaign defaults).
#
# Required:
#   --project / DONTPANIC_FIREBASE_PROJECT  Target GCP/Firebase project ID
#             / JARVIS_FIREBASE_PROJECT     Legacy alias
#   --billing-account / DONTPANIC_BILLING_ACCOUNT
#                     / JARVIS_BILLING_ACCOUNT
#                                            Billing account (XXXXXX-XXXXXX-XXXXXX)
#
# Optional:
#   --create-key                             Generate a long-lived SA key. Loud
#                                            and gitignore-verified. Default: off.
#   --skip-apis                              Skip enable-services step
#   --skip-rules                             Skip firebase deploy of rules
#   --dry-run                                Print every command, run nothing
#   -h | --help                              This help

set -euo pipefail

# ── arg parsing ─────────────────────────────────────────────────────────────
PROJECT="${DONTPANIC_FIREBASE_PROJECT:-${JARVIS_FIREBASE_PROJECT:-}}"
BILLING="${DONTPANIC_BILLING_ACCOUNT:-${JARVIS_BILLING_ACCOUNT:-}}"
CREATE_KEY=false
SKIP_APIS=false
SKIP_RULES=false
DRY_RUN=false

usage() {
  sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)         PROJECT="$2"; shift 2 ;;
    --billing-account) BILLING="$2"; shift 2 ;;
    --create-key)      CREATE_KEY=true; shift ;;
    --skip-apis)       SKIP_APIS=true; shift ;;
    --skip-rules)      SKIP_RULES=true; shift ;;
    --dry-run)         DRY_RUN=true; shift ;;
    -h|--help)         usage 0 ;;
    *)                 echo "Unknown flag: $1" >&2; usage 2 ;;
  esac
done

# ── input validation ────────────────────────────────────────────────────────
abort() { echo "Error: $1" >&2; echo "Remediation: $2" >&2; exit 2; }

[[ -n "$PROJECT" ]] || abort \
  "missing --project / DONTPANIC_FIREBASE_PROJECT" \
  "pass --project your-project-id (no campaign default — see CONTRIBUTING.md)"
[[ -n "$BILLING" ]] || abort \
  "missing --billing-account / DONTPANIC_BILLING_ACCOUNT" \
  "pass --billing-account XXXXXX-XXXXXX-XXXXXX (gcloud billing accounts list)"

# Validate billing account shape (very permissive: 6-6-6 hex)
[[ "$BILLING" =~ ^[0-9A-Fa-f]{6}-[0-9A-Fa-f]{6}-[0-9A-Fa-f]{6}$ ]] || abort \
  "billing account '$BILLING' does not look like XXXXXX-XXXXXX-XXXXXX" \
  "run: gcloud billing accounts list --format='value(name)' to find the ID"

# ── prereq checks ───────────────────────────────────────────────────────────
need() {
  command -v "$1" >/dev/null 2>&1 || abort \
    "missing CLI: $1" \
    "$2"
}
# jq and python3 are required even under --dry-run because the script itself
# parses JSON / computes derived values regardless of execution mode.
need jq       "install jq: brew install jq"
need python3  "install Python 3.10+: brew install python@3.11"

# Cloud CLI presence + auth checks — skipped under --dry-run. The whole
# point of dry-run is to preview commands without touching the cloud,
# including authenticating; under dry-run the gcloud/firebase invocations
# are echoed rather than executed (see `run` / `run_quiet` helpers below),
# so requiring the binaries to be installed would defeat dry-run's purpose
# (test_f022_bootstrap_parser.py::test_dry_run_executes_zero_side_effects).
if ! $DRY_RUN; then
  need gcloud   "install gcloud SDK: https://cloud.google.com/sdk/docs/install"
  need firebase "install firebase CLI: npm i -g firebase-tools"
  gcloud auth print-access-token >/dev/null 2>&1 || abort \
    "gcloud is not authenticated" \
    "run: gcloud auth login && gcloud auth application-default login"
  firebase login:list 2>/dev/null | grep -q "@" || abort \
    "firebase CLI is not authenticated" \
    "run: firebase login"
fi

# ── repo paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
JARVIS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SECRETS_DIR="$JARVIS_DIR/.secrets"
GITIGNORE="$JARVIS_DIR/.gitignore"
ENV_FILE="$JARVIS_DIR/environments.json"
ENV_EXAMPLE="$JARVIS_DIR/environments.json.example"
FIREBASERC_FILE="$JARVIS_DIR/.firebaserc"
FIREBASERC_EXAMPLE="$JARVIS_DIR/.firebaserc.example"

run() {
  echo "+ $*"
  if ! $DRY_RUN; then "$@"; fi
}

# Like `run`, but suppresses stdout on a real run so noisy CLIs (gcloud
# IAM bindings) don't dominate the log. The echo of the command itself
# always appears, including in --dry-run, so previewing remains accurate.
quiet_run() {
  echo "+ $*"
  if ! $DRY_RUN; then "$@" >/dev/null; fi
}

# Read-only existence probe, suppressed under --dry-run. Used to choose
# between "skip create" and "create" branches without touching the cloud
# during a preview. Returning 1 in dry-run forces the create branch to
# print, which is the more useful preview.
probe() {
  if $DRY_RUN; then
    return 1
  fi
  "$@" >/dev/null 2>&1
}

echo "=== Jarvis bootstrap ==="
echo "  Project:         $PROJECT"
echo "  Billing account: $BILLING"
echo "  Create SA key:   $CREATE_KEY"
echo "  Dry run:         $DRY_RUN"
echo ""

# ── 1. Link billing ─────────────────────────────────────────────────────────
echo "[1/6] Linking billing account..."
run gcloud beta billing projects link "$PROJECT" --billing-account="$BILLING"

# ── 2. Enable APIs ──────────────────────────────────────────────────────────
if ! $SKIP_APIS; then
  echo "[2/6] Enabling required APIs (firestore, storage, firebase, iam, cloudbuild)..."
  run gcloud services enable \
    firebase.googleapis.com \
    firestore.googleapis.com \
    storage.googleapis.com \
    iam.googleapis.com \
    iamcredentials.googleapis.com \
    cloudbuild.googleapis.com \
    --project="$PROJECT"
else
  echo "[2/6] Skipping API enable (--skip-apis)"
fi

# ── 3. Create orchestrator SA + grant roles ─────────────────────────────────
SA_EMAIL="orchestrator@${PROJECT}.iam.gserviceaccount.com"
echo "[3/6] Creating orchestrator service account..."
if probe gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT"; then
  echo "  → orchestrator SA already exists, skipping create"
else
  run gcloud iam service-accounts create orchestrator \
    --display-name="Jarvis orchestrator" \
    --project="$PROJECT"
fi

# Roles granted to the orchestrator SA. Mirrors the original F002 manual
# setup with one deliberate deviation:
#   - storage.objectAdmin (not storage.admin) — least-privilege; the
#     smoke test path is upload + signed URL, both covered by objectAdmin.
#     Bucket-level operations (create/delete) are out of band of the
#     orchestrator's runtime scope.
for role in \
  roles/datastore.user \
  roles/storage.objectAdmin \
  roles/logging.logWriter \
  roles/iam.serviceAccountTokenCreator
do
  quiet_run gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$role" \
    --condition=None \
    --quiet
done

# ── 4. Optional SA key generation (LOUD, gitignore-verified) ────────────────
KEY_PATH="$SECRETS_DIR/${PROJECT}-orchestrator.json"
if $CREATE_KEY; then
  echo "[4/6] Creating SA key (long-lived; --create-key was passed)..."
  echo ""
  echo "  ⚠️  WARNING: Long-lived SA keys are a high-risk credential."
  echo "  ⚠️  Prefer Workload Identity Federation or short-lived tokens"
  echo "  ⚠️  in any environment that supports them."
  echo ""

  # Verify .secrets/ is gitignored before writing
  if ! grep -qE '(^|/)\.secrets/?$' "$GITIGNORE" 2>/dev/null; then
    abort \
      ".secrets/ is not in .gitignore — refusing to write a key" \
      "add a line '.secrets/' to .gitignore, then re-run bootstrap.sh --create-key"
  fi
  # Belt-and-suspenders: confirm git treats the file as ignored
  mkdir -p "$SECRETS_DIR"
  if ! git -C "$JARVIS_DIR" check-ignore -q "$KEY_PATH" 2>/dev/null; then
    abort \
      "git would track $KEY_PATH despite .gitignore — refusing to write" \
      "investigate .gitignore order or per-path exclusions before --create-key"
  fi

  if [[ -f "$KEY_PATH" ]]; then
    echo "  → key already exists at $KEY_PATH, skipping (delete first to rotate)"
  else
    run gcloud iam service-accounts keys create "$KEY_PATH" \
      --iam-account="$SA_EMAIL" \
      --project="$PROJECT"
    run chmod 600 "$KEY_PATH"
    echo "  ✓ wrote $KEY_PATH (gitignore-verified)"
  fi
else
  echo "[4/6] Skipping SA key creation (pass --create-key to opt in)"
fi

# ── 5. Deploy storage + firestore rules ─────────────────────────────────────
if ! $SKIP_RULES; then
  echo "[5/6] Deploying storage + firestore rules..."
  (
    cd "$JARVIS_DIR"
    run firebase deploy --only=storage,firestore:rules --project="$PROJECT"
  )
else
  echo "[5/6] Skipping rules deploy (--skip-rules)"
fi

# ── 6. Generate environments.json + .firebaserc from examples ──────────────
echo "[6/6] Generating environments.json + .firebaserc..."

write_from_example() {
  local target="$1" example="$2" jq_filter="$3"
  if [[ -f "$target" ]]; then
    echo "  → $(basename "$target") already exists, leaving it alone"
    return
  fi
  if [[ ! -f "$example" ]]; then
    abort \
      "$(basename "$example") missing at $example" \
      "this should be tracked in git — restore it from origin"
  fi
  if $DRY_RUN; then
    echo "  + would write $target with project=$PROJECT"
  else
    jq --arg p "$PROJECT" "$jq_filter" "$example" > "$target"
    echo "  ✓ wrote $target"
  fi
}

write_from_example "$ENV_FILE" "$ENV_EXAMPLE" \
  '.dev.firebase_project = $p | .dev.gcp_project = $p'
write_from_example "$FIREBASERC_FILE" "$FIREBASERC_EXAMPLE" \
  '.projects.default = $p | .projects.orchestrator = $p'

echo ""
echo "=== Bootstrap complete ==="
echo "Next:"
echo "  export DONTPANIC_FIREBASE_PROJECT=$PROJECT"
echo "  python3 scripts/jarvis_doctor.py     # verify"
if ! $CREATE_KEY; then
  echo "  # If you need a SA key for local agent auth, re-run with --create-key"
fi
