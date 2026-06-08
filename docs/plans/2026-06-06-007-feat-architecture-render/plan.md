---
id: 2026-06-06-007-feat-architecture-render
title: Architecture render — regenerate diff-able levels in the build + breadcrumb zoom on the live SVG
type: feat
tier: cross-cutting
status: draft
date: "2026-06-06"
goal_type: new_feature
description: >
  The redesign's "navigable architecture" (spec §9) is already half-shipped: the Architecture page
  renders an interactive swimlane SVG (typed edges, click-to-detail) from architecture-view-state.json,
  and architecture_levels.py emits diff-able per-level Mermaid slices. 007 closes the two real gaps
  WITHOUT vendoring a mermaid runtime (operator decision): (F001) wire write_levels into the build so
  the diff-able levels/*.mmd regenerate from the current architecture.json — cache-only, never writing
  into a foreign tracked project tree; (F002) add a breadcrumb L0->L3 cluster-zoom to the EXISTING
  interactive SVG so the operator can drill from the whole map into a single cluster and back.
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
---

## Features
- **F001 levels-into-build (cache-only)** — the build regenerates the diff-able per-level `.mmd` slices
  via `architecture_levels.write_levels` from the current architecture snapshot, into the DontPanic
  repo's own `docs/architecture/levels/`; guarded so a fleet/foreign build never writes levels into
  another project's tracked tree.
- **F002 breadcrumb cluster-zoom** — the existing Architecture SVG gains a breadcrumb (All ▸ cluster)
  that filters the rendered nodes/edges to a single cluster (by directory, mirroring `cluster_key`)
  and back, giving the L2→L3 drill the spec asked for — on the render that already exists.

## Sequence
F001 (build wiring) → F002 (page breadcrumb zoom), both pure/tested; no mermaid runtime added.
