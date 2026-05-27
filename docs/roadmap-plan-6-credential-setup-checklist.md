# Plan 6 — Credential Setup Checklist (operator)

**Plan ID:** Plan 6 in `docs/roadmap-2026-05-19-install-ux-architecture-v0.md`
**Owner:** operator (you, on your machine)
**Estimated time:** 30-60 minutes
**Status:** ready to start in parallel with running paid dispatches

This checklist runs entirely on your local machine + GCP Console. No code changes in DontPanic. Mark steps as you go.

## Pre-flight (verify what's already in place)

```bash
# What does doctor say right now?
cd "$HOME/Documents/GitHub/DontPanic"
python3 -m dontpanic_orchestrate doctor 2>&1 | grep -E "firebase|target-project|secrets-dir|sa-key"
```

Expected: some checks may be passing, some red. Note which ones are red — those drive the next steps.

## Step 1 — Confirm gcloud + firebase CLIs

```bash
gcloud --version
firebase --version
```

If missing: `brew install --cask google-cloud-sdk` and `npm install -g firebase-tools`.

## Step 2 — Authenticate

```bash
gcloud auth login
gcloud auth application-default login
firebase login
```

You'll be redirected to a browser for each. Use the Google account that owns the target Firebase project (or whichever account has owner/editor access).

## Step 3 — Confirm project access

```bash
PROJECT_ID="YOUR_FIREBASE_PROJECT_ID"
gcloud projects list | grep "${PROJECT_ID}"
firebase projects:list | grep "${PROJECT_ID}"
```

Expected: both list your target Firebase project as accessible. If not, you don't have access yet — either grant your account roles in GCP Console, or create the project if it doesn't exist.

## Step 4 — Generate the orchestrator service-account key

If a previous SA key exists at `~/.dontpanic/.secrets/`, you can skip this and just verify.

```bash
# Create service account if not already present
PROJECT_ID="YOUR_FIREBASE_PROJECT_ID"
gcloud iam service-accounts create dontpanic-orchestrator \
  --project="${PROJECT_ID}" \
  --display-name="DontPanic orchestrator" \
  --description="Service account used by dontpanic supervisor for Firebase/GCS operations" || true

# Grant roles (these are the documented minimum from F022)
SA="dontpanic-orchestrator@${PROJECT_ID}.iam.gserviceaccount.com"
for role in roles/storage.objectAdmin roles/firebase.admin roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA}" --role="${role}" >/dev/null
done

# Generate + place key
mkdir -p ~/.dontpanic/.secrets
chmod 700 ~/.dontpanic/.secrets
gcloud iam service-accounts keys create \
  ~/.dontpanic/.secrets/"${PROJECT_ID}"-orchestrator.json \
  --iam-account="${SA}"
chmod 600 ~/.dontpanic/.secrets/"${PROJECT_ID}"-orchestrator.json
```

## Step 5 — Verify .secrets is gitignored

```bash
cd "$HOME/Documents/GitHub/DontPanic"
PROJECT_ID="YOUR_FIREBASE_PROJECT_ID"
git check-ignore -v ~/.dontpanic/.secrets/"${PROJECT_ID}"-orchestrator.json || echo "OK — outside repo, not tracked"
# Also check that the in-repo .secrets/ pattern (if any) is gitignored:
grep -E "^\.secrets|^\.dontpanic" .gitignore || echo "WARN: add .secrets/ to .gitignore if you'll ever symlink it into the repo"
```

## Step 6 — Run the doctor probe

```bash
cd "$HOME/Documents/GitHub/DontPanic"
python3 -m dontpanic_orchestrate doctor 2>&1 | tail -30
```

Expected: `firebase-auth`, `target-project`, `secrets-dir`, `sa-key-age` all green.

## Step 7 — Optional smoke test

```bash
# If Plan 7's Firebase work is queued, this validates the end-to-end pre-condition:
PROJECT_ID="YOUR_FIREBASE_PROJECT_ID"
python3 -m firebase_adapter.dontpanic_sync start \
  --project-id "${PROJECT_ID}" --once --dry-run \
  --plans-root docs/plans 2>&1 | tail -10
```

Expected: connects to Firebase, lists plans, exits cleanly (dry-run does not mutate).

## Done?

When all 7 steps pass:
- Plan 6 acceptance: doctor `--profile=firebase-dashboard` (once Plan 2 F001 adds profiles) returns green
- Plan 7 unblocks; Plan 4.5 architecture map can also consume Firebase if needed (it doesn't, but the credentials are nice-to-have)

If you hit any issue: paste the doctor output back to me and I'll diagnose.
