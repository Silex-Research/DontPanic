---
id: 2026-06-08-006-fix-preimpl-governance-loop
title: Fix the pre-impl governance loop (sufficiency caller + lock generation + Category serialization + Codex JSONL parser)
type: fix
tier: cross-cutting
status: draft
date: "2026-06-08"
goal_type: incident
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  objective_contract: ./objective_contract.json
description: >
  Dogfooding the full `dontpanic orchestrate` loop on DontPanic itself (2026-06-08)
  surfaced four real defects in the pre-impl governance path — the exact layer that
  is supposed to make DontPanic trustworthy. This plan repairs all four so a plan can
  go draft → sufficiency audit → lock → design-review without dead-ending or
  discarding a paid Codex response.
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

The pre-impl sufficiency gate was non-functional: `run_sufficiency_audit` had no
production caller, `plan lock` required an artifact nothing generated, the
design-review volley crashed on a `Category` enum, and the sufficiency parser threw
away a paid Codex JSONL response it couldn't parse. These are governance-path bugs,
not incidental — they must be fixed before the loop can be trusted to run plans.

## Features

- **F001** — production sufficiency caller + lock self-generation: add a production
  entry (`generate_sufficiency_findings`) that drives the resolved cross-vendor
  auditor through the registered executor, and make `dontpanic plan lock` invoke it
  when a gated plan is missing its findings — so lock generates the artifact instead
  of dead-ending. Degrades with an actionable message when no auditor is configured.
- **F002** — design-review volley no longer crashes on enum serialization: the
  pre-lock design volley serializes feature dicts with `model_dump(mode="json")` so
  `Category` (and any enum) becomes its string value, fixing
  "Object of type Category is not JSON serializable".
- **F003** — sufficiency reuses the known-good Codex parser: extract the post-impl
  `_extract_codex_streaming_payload` into a shared `codex_stream` module (single
  source of truth, no circular import) and have the sufficiency parser use it plus a
  tolerant `raw_decode` coercion, so a Codex JSONL stream — or a valid JSON value
  with trailing prose ("Extra data") — parses instead of being discarded. Includes a
  no-paid fixture replaying the wasted-response shape and an end-to-end dry-run
  (draft → sufficiency audit → gate sees findings → design volley serializes).

## Non-goals

- No change to what the sufficiency/completion auditors assess (only how their
  output is parsed and how the loop is wired).
- No new audit gates or governance stages.

## Decisions
See `decisions.jsonl`.
