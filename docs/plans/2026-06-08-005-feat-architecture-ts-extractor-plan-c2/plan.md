---
id: 2026-06-08-005-feat-architecture-ts-extractor-plan-c2
title: Architecture reconciler Plan C+ (slice 2) — TypeScript/JSX import extractor + non-product scoping
type: feat
tier: cross-cutting
status: active
date: "2026-06-08"
goal_type: new_feature
description: >
  Second per-evidence-type extractor slice. Extend the JS extractor to parse
  first-party TypeScript/JSX (.ts/.tsx/.jsx) ES imports, register a ts_import_crawler,
  and move typescript/jsx from the unextracted set to extracted. PAIRED with an honest
  scoping decision: documentation mockups (docs/design/**) and vendored skill assets
  (claude/skills/**/assets) are NON-PRODUCT and excluded from the architecture model
  (like node_modules), so DontPanic's own ceiling lifts off low truthfully rather than
  by ingesting mockup noise. Relative imports only (no tsconfig path/alias resolution).
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

The 2026-06-08 audit (B1#2) correctly capped DontPanic's own ceiling at low because
it ships unextracted .tsx/.jsx. But those files are documentation React mockups and
remotion-skill rule-assets — NOT the orchestrator's runtime architecture. The honest
resolution is twofold: (1) a real TS/JSX extractor for FIRST-PARTY TypeScript (so a
TS target project gets a real as-built graph), and (2) scope non-product TS/JSX out
of the architecture model entirely, the same way node_modules/vendor are excluded.
For DontPanic that lifts the ceiling because no first-party TS/JSX remains; for a TS
project it produces a real module graph.

## Features

- **F001** — TS/JSX import extractor: parse first-party .ts/.tsx/.jsx ES imports
  (incl. import-type and re-export forms), emit ts_module nodes + relative-import
  edges, contract-stamped; bare/unresolved imports surface as low-confidence
  unresolved endpoints (mirrors the JS crawler). Deterministic + bounded.
- **F002** — non-product scoping + coverage lift: documentation-mockup and vendored
  skill-asset trees are excluded from BOTH the extractor scan and the coverage
  language-presence scan; with first-party TS/JSX extracted (or absent), typescript
  and jsx leave the missing-extractor set, so a repo whose only TS/JSX was non-product
  is no longer falsely capped.

## Non-goals

- No tsconfig path/alias resolution, no type analysis (relative imports only).
- No other languages (Swift/Gradle/Kotlin/Go/Rust stay reserved, demand-gated by a
  governed target project that ships them).
- No change to the intent reconciler or the Python as-built crawler.

## Decisions
See `decisions.jsonl`.
