---
id: 2026-06-06-007-feat-architecture-render
title: Architecture render — regenerate diff-able levels in the build + breadcrumb zoom on the live SVG
type: feat
tier: cross-cutting
status: draft
date: "2026-06-06"
goal_type: new_feature
description: >
  Build navigable architecture on the EXISTING interactive SVG graph — an interactive component map,
  not a Mermaid diagram-text renderer (operator decision: do NOT vendor mermaid). Model: architecture
  state → normalized graph/levels DATA → interactive SVG map → click a component → highlight
  upstream/downstream dependencies + dim unrelated + detail panel → drill into the next level, with a
  breadcrumb showing the level path (System ▸ Dashboard ▸ Operator Console ▸ Cockpit). The graph model
  `{nodes, edges, levels, clusters, metadata, freshness}` is the source of truth; the architecture_levels
  `.mmd` slices remain an OPTIONAL diffable export for docs/git review, never the render source.
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
---

## Features
- **F001 graph/level DATA (not mermaid)** — the architecture build emits the normalized graph model
  the map consumes: `nodes` + `edges` + `levels` + `clusters` (by directory, mirroring `cluster_key`)
  + `freshness`, into the architecture view-state. `architecture_levels.write_levels` stays wired as an
  OPTIONAL diffable `.mmd` export (cache-only, foreign-repo guarded), never the render source.
- **F002 interactive component map** — on the EXISTING Architecture SVG: clicking a component
  highlights its upstream/downstream dependencies, dims unrelated nodes, and opens the detail panel;
  a breadcrumb shows the level path and drills into the next cluster level (and back).

## Sequence
F001 (build wiring) → F002 (page breadcrumb zoom), both pure/tested; no mermaid runtime added.
