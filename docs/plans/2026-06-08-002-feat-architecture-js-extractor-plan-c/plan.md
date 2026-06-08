---
id: 2026-06-08-002-feat-architecture-js-extractor-plan-c
title: Architecture reconciler Plan C (slice 1) — JavaScript/TS import extractor
type: feat
tier: cross-cutting
status: completed
date: "2026-06-08"
goal_type: new_feature
description: >
  First Plan C extractor slice: a JavaScript/TypeScript import extractor for the
  dashboard so DontPanic's own as-built map stops reporting javascript as an
  unextracted evidence kind. This lifts the extractor-coverage ceiling Plan A's
  contract pins low whenever a present language has no extractor. One
  evidence-type per slice; this slice is JS/TS only (Swift/Gradle later).
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

Plan A's coverage contract drops the confidence ceiling to low whenever the repo
contains a language DontPanic cannot extract. For DontPanic itself that language
is JavaScript — the dashboard ships ~39 ES modules with no import extractor, so
the as-built map is Python-only and the ceiling is pinned low. This slice adds a
JS/TS extractor so the dashboard's module graph becomes as-built evidence and the
javascript kind moves from missing_extractor to covered.

## Scope (bounded)

- JS/TS **import** extraction only — ES `import ... from './x.js'` relative graph
  for the dashboard, emitted as as-built module nodes + import edges with the
  Plan A evidence contract; unresolved (bare/vendor) imports surface as
  low-confidence unresolved endpoints, exactly like the Python crawler.
- The coverage block stops listing javascript as missing_extractor (DontPanic now
  HAS a JS extractor) and reports the new extractor's status.

## Non-goals

- No other languages (Swift/Gradle/Go/Rust remain reserved slices).
- No TS type analysis, no bundler/alias resolution beyond relative paths.
- No UI work; no change to the as-built Python crawler or the reconciler.

## Features

- **F001** — JS/TS import extractor: emit dashboard ES modules as as-built nodes
  + relative-import edges (unresolved imports visible), contract-stamped.
- **F002** — coverage lift: javascript is no longer an unextracted kind; the
  coverage block reports the JS extractor, so a JS+Python repo can rise above the
  low ceiling.

## Decisions

See `decisions.jsonl`.
