# Jarvis

> Cross-agent orchestration framework for Claude Code, Codex, Gemini, Grok, and local Ollama models. Plans are executable contracts; agents implement and audit each other; humans decide at tier-appropriate gates.

**Status:** alpha — bootstrap phase. Self-hosting orchestration system being built. See [`docs/plans/`](./docs/plans/) for active work and [parent plan](./docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md) for the design.

---

## What is Jarvis

A 4-layer hierarchy that lets multiple AI agents collaborate on real work without going off the rails:

```
Identity & governance        ← SOUL.md, AGENTS.md, USER.md
Routing & contracts          ← claude/RESOLVER.md, claude/shared/ (agent-conventions subtree)
Execution units              ← claude/skills/, docs/plans/<id>/
Multi-agent panel + bounds   ← Claude / Codex / Gemini / Grok / OSS  +  CAWP tiers + circuit breakers
```

Each layer's output becomes the next layer's contract. Plans live in `docs/plans/<YYYY-MM-DD-NNN-type-name>/` with `features.json` as inviolable machine-checkable ground truth. Different model families audit each other so no single vendor self-approves.

---

## Prerequisites

Required:

- **macOS** (Linux likely works, untested) with **zsh** or **bash**
- **gcloud SDK** 500+ — `brew install --cask google-cloud-sdk`
- **firebase-tools** 15+ — `npm install -g firebase-tools` (Node 20+)
- **Python 3.10+** with `pip` — `brew install python@3.11`
- **jq** — `brew install jq`
- **bq** (BigQuery CLI) — bundled with gcloud
- **git** with `git subtree` (default in modern git)

Optional (depending on which agents you wire):

- **ollama** — `brew install ollama` (local OSS models for safety/embeddings)
- **codex CLI** — adversarial auditor (different vendor → no self-approval)
- **gemini CLI** — multimodal review + 2M context
- **xAI API key** — Grok currency check / third opinion
- **terminal-notifier** — `brew install terminal-notifier` (INBOX async channel)

Python deps: `pip3 install firebase-admin pydantic jsonschema pyyaml datamodel-code-generator`

---

## Quickstart

> **Coming soon:** `./bootstrap.sh` will codify the manual steps below into a single interactive script. Tracked as parent plan F022.

### 1. Clone

```bash
git clone https://github.com/Silex-Research/Jarvis.git
cd Jarvis
```

### 2. Set up evidence storage (one-time)

You need a Firebase/GCP project for orchestration evidence. Walk through:

```bash
# Auth
gcloud auth login
firebase login

# Create or pick a project (replace <id> with your project ID)
gcloud projects create <id> --name=Jarvis-evidence
firebase use <id>

# Link a billing account (required for Storage + Firestore)
gcloud beta billing accounts list
gcloud beta billing projects link <id> --billing-account=<billing-id>

# Enable APIs
gcloud services enable firestore.googleapis.com firebasestorage.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com --project=<id>

# Storage bucket for evidence > 100KB
gcloud storage buckets create gs://<id>-evidence --project=<id> \
  --location=us-central1 --uniform-bucket-level-access

# Service account for orchestrator runtime
gcloud iam service-accounts create orchestrator \
  --display-name="Jarvis Orchestrator" --project=<id>
SA="orchestrator@<id>.iam.gserviceaccount.com"
for ROLE in roles/storage.admin roles/datastore.user roles/logging.logWriter \
            roles/iam.serviceAccountTokenCreator; do
  gcloud projects add-iam-policy-binding <id> \
    --member="serviceAccount:$SA" --role="$ROLE" --condition=None
done

# Generate key (gitignored under .secrets/)
mkdir -p .secrets
gcloud iam service-accounts keys create .secrets/<id>-orchestrator.json \
  --iam-account="$SA"

# Smoke test the pipeline
PYTHONPATH=scripts python3 -m jarvis_orchestrate.smoke_test_storage
```

If the smoke test prints `✓ F002 acceptance PASS`, evidence storage is wired.

### 3. Configure billing tracking (optional, ~24h to populate)

For the dashboard to show GCP cost over time, configure BigQuery export from your billing account:

1. Open https://console.cloud.google.com/billing/<billing-id>/export/bigquery
2. **Standard usage cost** → Edit settings → Project: `<your-billing-export-project>`, Dataset: `billing_export`
3. After ~24h, run `bash scripts/refresh-costs.sh` to populate `dashboard/state/costs.json`.

### 4. Validate your first plan

```bash
python3 claude/shared/schemas/v1.0/validate.py \
  docs/plans/2026-04-19-001-infra-cross-agent-orchestration
```

Should print all green checkmarks.

---

## Project layout

```
Jarvis/
├── SOUL.md                          # values + safety guard
├── AGENTS.md                        # operating manual + role catalog
├── USER.md                          # who you're helping
├── CONTINUOUS_WORK_PROTOCOL.md      # 15-min cycle + tier-based approval matrix
├── MEMORY_ARCHITECTURE.md           # daily logs + long-term memory layout
│
├── claude/
│   ├── RESOLVER.md                  # intent → skill routing with precedence
│   ├── settings.json                # hooks, env, permissions
│   ├── skills/                      # 24 skills (plan-artifacts, brainstorm-gate, …)
│   ├── hooks/                       # session-start, security-gate, …
│   ├── commands/                    # slash commands
│   ├── registry/entities.md         # cross-project service registry
│   └── shared/                      # ← agent-conventions subtree (v1.1.0)
│       ├── conventions/             # firestore-security, error-handling, …
│       ├── resolver/SPEC.md         # RESOLVER.md format definition
│       ├── skill-standard/          # skill conformance + template
│       └── schemas/v1.0/            # plan/features/audit/signoff schemas + Pydantic
│
├── docs/plans/                      # directory plans (executable contracts)
│   └── <YYYY-MM-DD-NNN-type-name>/
│       ├── plan.md                  # frontmatter validates against plan.schema.json
│       ├── features.json            # validates against features.schema.json
│       ├── decisions.jsonl          # append-only decision log
│       ├── audit/*.json             # per-agent audit reports
│       └── evidence/                # small artifacts (large → Firebase Storage)
│
├── scripts/
│   ├── jarvis_orchestrate/          # supervisor runtime (in progress)
│   ├── refresh-costs.sh             # GCP $ → dashboard/state/costs.json
│   └── quota_check.py               # LLM tokens → ~/.jarvis/quota_state.json
│
├── dashboard/                       # Firebase Hosting static SPA
│   └── state/                       # agents.json, tasks.json, costs.json, …
│
├── .secrets/                        # gitignored — service account keys
└── .firebaserc / firebase.json      # multi-project alias config
```

---

## Architecture in one diagram

```
SOUL / AGENTS / USER       ← who I am, what I can do, who I serve
        ↓
RESOLVER + claude/shared/  ← which skill fires, by which rules
        ↓
skills/  +  registry/      ← unit of work + cross-project knowledge
        ↓
plans/ + features.json     ← executable contract for any non-trivial work
        ↓
Claude / Codex / Gemini / Grok / OSS  ← panel that implements + audits
        ↓
CAWP tiers + quotas + dashboard       ← the throttle and the readout
```

Full design in [`docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md`](./docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md).

---

## Two-axis billing

Jarvis tracks cost on two independent axes:

| Axis | Source | Output | Use |
|---|---|---|---|
| GCP $ | `silexr-billing` BigQuery export | `dashboard/state/costs.json` | Cloud-spend dashboard |
| LLM tokens | Per-model session logs (Claude/Codex/Gemini/Grok) + Ollama probe | `~/.jarvis/quota_state.json` | Circuit breakers (defer dispatch when weekly quota near cap) |

Run `bash scripts/refresh-costs.sh` for GCP $ (daily cron recommended) and `python3 scripts/quota_check.py` for LLM tokens (every ~30 min during active work).

---

## Setup checklist (running list — what new users need)

This list grows as we build. If a feature requires new setup, it lands here.

- [x] gcloud + firebase CLI authenticated
- [x] Firebase project linked to billing
- [x] APIs enabled: Firestore, Firebase Storage, IAM, IAM Credentials
- [x] GCS evidence bucket created
- [x] `orchestrator` service account + 4 roles + JSON key in `.secrets/`
- [x] firebase-admin Python SDK installed
- [x] Storage smoke test passes (F002 acceptance)
- [ ] BigQuery billing export configured (manual, Console only)
- [ ] (when supervisor lands) Codex / Gemini / Grok CLIs authed
- [ ] (when supervisor lands) `terminal-notifier` for INBOX async channel
- [ ] (when supervisor lands) `~/.jarvis/quota_state.json` caps calibrated to your real usage

---

## Contributing

`CONTRIBUTING.md` and `CODE_OF_CONDUCT.md` coming with the open-source push (parent F022). For now: read `AGENTS.md`, follow the conventions in `claude/shared/conventions/`, and write plans before code.

## License

License coming with F022. Until then, treat as all rights reserved.
