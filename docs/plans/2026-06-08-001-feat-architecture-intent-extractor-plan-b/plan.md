---
id: 2026-06-08-001-feat-architecture-intent-extractor-plan-b
title: Architecture reconciler Plan B — ADR/doc intent extractor + as-built vs intended diff
type: feat
tier: cross-cutting
status: active
date: "2026-06-08"
goal_type: new_feature
description: >
  Fill the intent + diff layers Plan A reserved (empty shell). Extract intent
  claims from ADR/decision docs (graceful when none exist), then a bounded
  reconciler compares each claim against the as-built graph and emits a diff
  keyed by the taxonomy Plan A defined. This turns the Architecture surface from
  as-built-only into as-built-vs-intended, the next reconciler slice. No new
  code extractors (that is Plan C); ADR parsing only.
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

Plan A (2026-06-07-001) shipped the evidence contract and a layer shell whose
`intent.claims` and `diff` are empty by design — reserved for this plan. Plan B
populates them: a doc/ADR intent extractor produces declared claims, and a
bounded reconciler diffs them against the as-built graph using the taxonomy Plan
A already defined (`aligned`, `drift`, `implemented_undocumented`,
`documented_unimplemented`, `conflicting_dependency`, `stale_adr`,
`unknown_confidence`). Absence of ADRs degrades gracefully — most repos have
none, and the honesty contract requires "no ADRs found", never a crash.

## Contract

- An intent claim is `source_kind=adr`, `evidence_basis=declared` (it describes
  intent, never an as-built fact). Each carries id, title, status, source path,
  the decision text, and the symbols it references.
- The reconciler is conservative: it only emits a diff entry it can defend from
  evidence. v0 emits `aligned` (claim reference resolves to an as-built node),
  `documented_unimplemented` (claim reference resolves to nothing as-built), and
  `stale_adr` (a superseded ADR). The remaining taxonomy values stay defined and
  reserved for later extractor coverage (Plan C).

## Features

- **F001** — ADR/doc intent extractor: parse decision docs into declared intent
  claims and populate the previously-empty intent layer; graceful absence;
  coverage reports the doc/adr extractor honestly.
- **F002** — as-built vs intended reconciler: diff each claim against the
  as-built graph and populate the previously-empty diff list, keyed by the Plan A
  taxonomy; conservative (only evidence-backed entries).

## Non-goals

- No new code/build/language extractors (Plan C owns those).
- No ADR authoring or status mutation — read-only.
- No UI work (rendering the two layers is a later slice).
- No change to the Plan A contract enums or the as-built builder.

## Decisions

See `decisions.jsonl`.
