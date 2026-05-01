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

The platform thesis is captured in [`docs/PLATFORM.md`](./docs/PLATFORM.md):
Jarvis is portable trust infrastructure for bounded agent work. It routes intent
through reusable skills and learned memory, turns non-trivial work into
machine-checkable plans, executes those plans across model/vendor boundaries, and
preserves proof through audits, evidence, signoff, and protected-path checks.

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

### 1. Clone

```bash
git clone https://github.com/Silex-Research/Jarvis.git
cd Jarvis
```

### 2. Bootstrap your own GCP/Firebase project

Pick a fresh GCP project ID (do NOT reuse the maintainer's campaign project)
and a billing account, then run:

```bash
gcloud auth login
gcloud auth application-default login
firebase login

scripts/bootstrap.sh \
  --project your-project-id \
  --billing-account XXXXXX-XXXXXX-XXXXXX
```

The script links billing, enables required APIs, creates the orchestrator
service account with scoped roles, deploys storage + firestore rules, and
generates a local `environments.json` + `.firebaserc` from the tracked
`.example` templates. SA keys are **off by default** — pass `--create-key`
explicitly if your local agents need one (the script verifies `.secrets/`
is gitignored before writing).

Pass `--dry-run` to preview every command without executing.

### 3. Verify

```bash
export JARVIS_FIREBASE_PROJECT=your-project-id

# Full check — needs `gcloud auth login` + `firebase login` first
python3 scripts/jarvis_doctor.py

# Or, before you've authenticated the CLIs (fresh clone smoke):
python3 scripts/jarvis_doctor.py --skip-auth
```

Both modes should print `✓ N/N checks passed — Jarvis is ready`. Each
red check includes a remediation line. Then run the storage smoke test:

```bash
PYTHONPATH=scripts python3 -m jarvis_orchestrate.smoke_test_storage
```

If it prints `✓ F002 acceptance PASS`, evidence storage is wired.

### 4. Validate your first plan

```bash
python3 claude/shared/schemas/v1.0/validate.py \
  docs/plans/2026-04-19-001-infra-cross-agent-orchestration
```

Should print all green checkmarks.

### 5. Run the test suite

```bash
PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/ -q
ruff check scripts/
ruff format --check scripts/
```

These four commands are the exact local equivalents of the
[GitHub Actions CI workflow](.github/workflows/ci.yml). See
[CONTRIBUTING.md](./CONTRIBUTING.md) for the contributor flow.

### 6. Preview your first volley

Before authorizing a real dispatch, the `dispatch-from-plan` subcommand prints a
10-field pre-flight context block (resolved plan path, target_env, declared
gates, quota readiness, etc.) and exits without dispatching:

```bash
PYTHONPATH=scripts python -m jarvis_orchestrate dispatch-from-plan <plan-id>
```

Add `--confirm` to actually dispatch via `supervisor.dispatch_volley` (in-process,
no subprocess shell-out). Forwarded flags: `--feature`, `--implementer`,
`--auditor`, `--max-iterations`, `--mode`. A full operator walkthrough — quota
calibration, INBOX, gate approvals — lands with the onboarding-UX plan
([`2026-05-01-001-feat-onboarding-ux`](./docs/plans/2026-05-01-001-feat-onboarding-ux/plan.md), F001).

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
│   ├── jarvis_orchestrate/          # supervisor runtime
│   ├── bootstrap.sh                 # one-shot GCP/Firebase setup
│   ├── jarvis_doctor.py             # preflight health checks
│   ├── sanitization_check.py        # sanitization regression guard
│   └── quota_check.py               # LLM tokens → ~/.jarvis/quota_state.json
│
├── dashboard/                       # Firebase Hosting static SPA
│   └── state/                       # agents.json, tasks.json, …
│
├── .secrets/                        # gitignored — service account keys (created by bootstrap --create-key)
├── environments.json                # gitignored; generated from environments.json.example
└── .firebaserc                      # gitignored; generated from .firebaserc.example
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
| GCP $ | Your billing-account BigQuery export | `dashboard/state/costs.json` | Cloud-spend dashboard (operator-supplied refresh script; not bundled) |
| LLM tokens | Per-model session logs (Claude/Codex/Gemini/Grok) + Ollama probe | `~/.jarvis/quota_state.json` | Circuit breakers (defer dispatch when weekly quota near cap) |

Run `python3 scripts/quota_check.py` for LLM tokens (every ~30 min during active work). GCP $ refresh is operator-specific (project list, app categorization, billing-export project all vary) and is not shipped as a bundled script.

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
