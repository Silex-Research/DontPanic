---
id: 2026-04-25-001-infra-jarvis-firebase-bootstrap
title: Jarvis Firebase Bootstrap (<firebase-project-id>) + Two-Axis Billing
type: infra
tier: local
status: abandoned
date: "2026-04-25"
dependencies:
  - 2026-04-19-001-infra-cross-agent-orchestration
description: Activate <firebase-project-id> services + service account + orchestrator credentials, satisfying parent F002 and F020. Lights up GCP $ tracking and LLM token tracking.
agents_required:
  - claude
human_gates:
  - pre_impl
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  parent: ../2026-04-19-001-infra-cross-agent-orchestration/plan.md
  features: ./features.json
  decisions: ./decisions.jsonl
---

> **⊘ ABANDONED 2026-05-05** — superseded by `2026-04-19-001-infra-cross-agent-orchestration` F002 (Firebase project + Storage + creds), which shipped under parent-plan tasks F002-A through F002-K. The bootstrap work this sub-plan was scoped to land has already been delivered through the parent. Closed as housekeeping per `docs/GOAL_GOVERNANCE_V1.md` §10. Original plan content preserved below for historical reference.

# Jarvis Firebase Bootstrap

Sub-plan of `2026-04-19-001`. Closes parent features F002 (Firebase project + Storage + creds) and F020 (LLM token quota tracking).

## Goal

Make `<firebase-project-id>` a working backend for the orchestration system: Storage for evidence > 100KB, service-account creds for Python supervisor, two-axis billing tracking (GCP $ via `refresh-costs.sh`, LLM tokens via `quota_check.py`).

## Scope (in)

- New Jarvis billing account, linked to `<firebase-project-id>`
- Cloud Storage default bucket + `storage.rules` (auth-only write, no client read)
- `orchestrator` service account with Storage Admin / Firestore User / Logs Writer
- Service account JSON key in `Jarvis/.secrets/` (gitignored, mirrored to 1Password)
- `firebase_client.py` — Admin SDK wrapper
- `smoke_test_storage.py` — F002 acceptance harness (upload + 1h signed URL)
- `quota_check.py` — F020, writes `~/.jarvis/quota_state.json`
- `refresh-costs.sh` patch — new "Jarvis" cost bucket
- Parent `features.json` patched (F002 description: `<firebase-project-id>` → `<firebase-project-id>`)

## Scope (out — deferred to parent plan or later sub-plans)

- Firestore rules beyond locked-down deny (no plan/audit collections yet — Phase 2 supervisor adds them)
- App Check (single-operator project, no client SDK)
- Cloud Functions (Phase 8 hygiene)
- Schema promotion to claude-conventions repo (separate sub-plan; conventions repo is missing locally)
- BigQuery export wiring (manual — depends on new billing account creation)

## Dependencies

- gcloud + firebase CLIs authenticated as `<operator-email>` (✓)
- `<operator-email>` Owner on `<firebase-project-id>` (✓ confirmed 2026-04-25)
- New "Jarvis" billing account created and linked (PENDING — operator action)

## Acceptance

This plan is `signoff: true` when:
- F002 acceptance: `python3 scripts/jarvis_orchestrate/smoke_test_storage.py` uploads fixture and retrieves via 1h signed URL with HTTP 200
- F020 acceptance: `python3 scripts/quota_check.py` writes `~/.jarvis/quota_state.json` with non-empty `models` map
- `refresh-costs.sh` runs without error and includes a "Jarvis" key (value will be 0 until BigQuery export populates ~24h after billing link)
- Parent `features.json` F002 reflects `<firebase-project-id>`
- `decisions.jsonl` D036 records the project-ID rename

## Risks

- **Billing not linked → Storage writes fail.** Smoke test will fail. Operator must create+link billing account first.
- **BigQuery export lag.** New billing account first export takes ~24h. costs.json shows Jarvis=0 until then; not a blocker.
- **Service account key on disk.** Compensating control: `.secrets/` gitignored + 1Password mirror + key rotated quarterly (manual reminder).

## Provenance

User created `<firebase-project-id>` in Firebase console on 2026-04-25 from session continuation of parent plan `2026-04-19-001`. This sub-plan was approved during the same session ("execute in parallel where able").

## Target

```yaml
target_env: dev
target_project: <firebase-project-id>
```
