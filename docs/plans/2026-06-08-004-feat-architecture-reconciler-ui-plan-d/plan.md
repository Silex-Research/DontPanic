---
id: 2026-06-08-004-feat-architecture-reconciler-ui-plan-d
title: Architecture reconciler Plan D — surface the coverage + intent + diff + baseline layers in the UI
type: feat
tier: cross-cutting
status: completed
date: "2026-06-08"
goal_type: new_feature
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  objective_contract: ./objective_contract.json
description: >
  Plans A/B/C/C0 built the reconciler's DATA (as_built + intent claims + diff +
  extractor coverage + the C0 tiered baseline coverage block) but the dashboard
  Architecture page still renders only the as-built map. Plan D surfaces the rest:
  an honest coverage/confidence banner, the C0 baseline coverage panel (rollup,
  per-language status, per-evidence-type tiers, scan_truncated, operator notes),
  confidence-aware styling for low-confidence/heuristic graph items, a two-layer
  as-built-vs-intended view with drift badges from the diff taxonomy, and a
  one-line producer parity fix so coverage.baseline reaches the payload on both
  build_view_state branches — so the operator sees "what DontPanic can prove from
  current evidence," not a confident-looking oracle.
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

The reconciler's whole point is operator-visible honesty (as-built vs intended +
drift + coverage + the C0 weak-baseline limits). Today that data is computed and
merged but invisible: the map looks authoritative while silently omitting intent,
diff, the confidence ceiling, and every C0 coverage surface (rollup lattice,
per-language extractor status, per-evidence-type tiers, scan truncation, and the
low-confidence/unknown-language notes the C0 plan pinned as RENDERED payload
fields). Plan D closes the render gap so the honesty the data already encodes
reaches the human.

## Current producer contract (what Plan D renders — read before editing acceptance)

- `architecture_baseline.build_baseline(repo_root)` returns
  `{profile, registry, graph, coverage}`. Its `coverage` block is:
  `rollup` (pinned lattice: `limited` / `partial` / `covered`),
  `per_language` (detected languages ONLY → `covered` for tier-2 parser-backed
  languages, `missing_extractor` otherwise), `per_evidence_type` (all 10 keys of
  `architecture_baseline.EVIDENCE_TYPES`, each `{status, tier, ...}`; `runtime`
  is the reserved tier-3 row), `scan_truncated` (one shared signal),
  `notes` (operator-facing strings: `LOW_CONFIDENCE_NOTE_TEMPLATE` per tier-1
  language + `UNKNOWN_LANGUAGE_NOTE`), and `unrecognized_extensions`.
- `build_view_state` attaches this block as `coverage["baseline"]` in the
  absent-architecture.json branch (`architecture_view_state.py`), but the
  present-architecture branch computes the same baseline and currently DROPS the
  coverage block (graph nodes/edges only). F005 fixes that asymmetry.
- The contract coverage block (both branches) is `compute_coverage`:
  `extractors[]` (incl. the Plan B `adr_intent_extractor` row),
  `missing_extractors[]`, `confidence_ceiling`, `note`.
- Layers: `layers.intent.claims[]` (`source_kind=adr`, `evidence_basis=declared`),
  `layers.diff[]` keyed by `DIFF_TAXONOMY` (7 values; the reconciler emits
  `aligned` / `documented_unimplemented` / `stale_adr` today), `layers.as_built`.
- Low-confidence graph items: `heuristic_import` edges
  (`evidence_basis: inferred|unresolved`, `resolved` flag), `heuristic_target`
  nodes (`source_kind=unknown`, `evidence_basis=unresolved`), and tier-0
  `fs_*` nodes / `contains` edges (`source_kind=filesystem`, declared).

## Features

- **F001** — coverage/confidence banner: render the contract coverage block at the
  top of the Architecture page — confidence ceiling, per-extractor
  covered/not_found rows (including adr_intent_extractor), and any
  missing_extractor kinds — so a low/medium ceiling is loudly stated, never
  implied away. Render-truth: a low ceiling reads as "incomplete," not a warning
  to dismiss.
- **F002** — two-layer view + drift badges: render the intent claims (ADR-derived)
  alongside the as-built graph, and surface each diff entry by its taxonomy as a
  drift badge. Intent is visibly labelled declared, never shown as an as-built
  fact; an empty intent layer reads "no ADRs found."
- **F003** — C0 baseline coverage panel: render `coverage.baseline` — the rollup
  verdict, the per-language status map, the per-evidence-type tier table
  (including the reserved runtime row), a visible truncation warning when
  `scan_truncated` is true, and the `notes` strings verbatim (low-confidence
  extractor notes + the unknown-language note). Absent block renders an honest
  empty state, never a fabricated one.
- **F004** — confidence-aware graph styling: heuristic/unresolved edges and
  heuristic-target/filesystem nodes render visually distinct from parser-backed
  evidence, with a legend keyed to the evidence vocabulary; render-truth
  passthrough — low-confidence items stay visible, never filtered or restyled
  into looking proven.
- **F005** — producer parity: attach `coverage["baseline"]` on the
  present-architecture branch of `build_view_state` (the block is already
  computed there and dropped); parity is proven by a test. One attach line —
  no data-model change, no detector/table change.
- **F006** — real-shell journeys: boot the real dashboard shell on
  producer-built view-states for BOTH states — architecture.json present
  (banner + baseline panel + intent claim + diff badge all visible) and absent
  (baseline graph + baseline coverage panel render instead of an empty
  surface) — with no raw-JSON leak and no over-confident rendering, guarded by
  a fixture↔producer contract test.

## Non-goals

- No new extractors and no detector/marker-table changes (Plan C+ scope); no
  change to the baseline data model or the evidence contract vocabulary.
- No operator annotation/correction yet (reserved for a Plan D2 follow-up — needs
  a persistence sidecar).
- No new action-execution channel.
- No tier-3 runtime collection (reserved in C0; the UI renders its reserved
  status honestly, nothing more).

## Decisions
See `decisions.jsonl`.
