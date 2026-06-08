---
id: 2026-06-08-004-feat-architecture-reconciler-ui-plan-d
title: Architecture reconciler Plan D — surface the intent + diff + coverage layers in the UI
type: feat
tier: cross-cutting
status: active
date: "2026-06-08"
goal_type: new_feature
description: >
  Plan A/B/C built the reconciler's DATA (as_built + intent claims + diff +
  coverage/confidence) but the dashboard Architecture page still renders only the
  as-built map. Plan D surfaces the rest: an honest coverage/confidence banner, a
  two-layer as-built-vs-intended view with drift badges from the diff taxonomy, and
  per-source freshness — so the operator sees "what DontPanic can prove from current
  evidence," not a confident-looking oracle. Read-only rendering; no model change.
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

The reconciler's whole point is operator-visible honesty (as-built vs intended +
drift + coverage). Today that data is computed and merged but invisible: the map
looks authoritative while silently omitting intent, diff, and the confidence
ceiling. Plan D closes the render gap so the honesty the data already encodes
reaches the human.

## Features

- **F001** — coverage/confidence banner: render the extractor-coverage block at the
  top of the Architecture page — confidence ceiling, per-extractor covered/not_found,
  and any missing_extractor kinds — so a low/medium ceiling is loudly stated, never
  implied away. Render-truth: a low ceiling reads as "incomplete," not a warning to dismiss.
- **F002** — two-layer view + drift badges: render the intent claims (ADR-derived)
  alongside the as-built graph, and surface each diff entry by its Plan A taxonomy
  (aligned / documented_unimplemented / stale_adr) as a drift badge. Intent is
  visibly labelled declared, never shown as an as-built fact; an empty intent layer
  reads "no ADRs found."
- **F003** — real-shell journey: boot the real dashboard shell on a producer-built
  view-state and assert the operator lands on an Architecture surface showing the
  coverage banner + at least one intent claim + the diff, with no raw JSON leak and
  no fake-fresh/over-confident rendering.

## Non-goals

- No new extractors (Plan C track), no change to the as-built/intent/diff data model.
- No operator annotation/correction yet (reserved for a Plan D2 follow-up — needs a
  persistence sidecar).
- No new action-execution channel.

## Decisions
See `decisions.jsonl`.
