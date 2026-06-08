---
id: 2026-06-07-001-feat-architecture-evidence-contract-v0
title: Architecture evidence contract v0 — source_kind + confidence + observed/inferred + provenance + extractor-coverage + as_built/intent layers + diff taxonomy (contract-only)
type: feat
tier: cross-cutting
status: draft
date: "2026-06-07"
goal_type: new_feature
description: >
  Make the architecture surface honest about WHAT IT CAN PROVE. Add an evidence
  contract to the view-state the interactive component map (plan 2026-06-06-007)
  already consumes, so the map stops implying "this IS the architecture" and starts
  asserting "this is the architecture DontPanic can prove from current evidence."
  Every node and edge carries source_kind + confidence + observed-vs-inferred +
  provenance refs; unresolved edges are emitted as low-confidence inferred instead
  of being silently dropped; a top-level extractor-coverage block states which
  evidence kinds are covered vs missing (so a Swift app with no Swift extractor
  renders LOW coverage, not a confident Python-shaped map); the model splits into
  as_built vs intent layers and defines the as-built<->intent diff taxonomy (intent
  and diff may start empty). This generalizes the render-truth trust boundary from
  per-node liveness to the architecture model itself.

  CONTRACT-ONLY (v0). NO new extractors (Swift/Gradle/Xcode/JS/routing/API/infra),
  NO ADR/doc ingestion populating the intent layer, NO UI overhaul or drift
  surfacing. Those are later plans (B = ADR intent extractor + reconciler; C+ =
  per-evidence-kind extractors; D = two-layer UI + drift + annotation) that DEPEND
  on this contract. Contract before coverage, so even a thin model is honest.
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
---

## Features
- **F001 evidence fields on every node + edge** — emit `source_kind`
  (`code | build | manifest | config | infra | test | doc | adr | inferred` —
  v0 only populates the kinds the current crawler can prove: code/manifest/test/doc
  for nodes), `confidence` (`high | medium | low`), `evidence_basis`
  (`observed | inferred`), and a `provenance` block (`source_path` + `extractor`
  id + how-resolved) on every node and edge `build_view_state` emits. Derived from
  signals already present (resolved intra-repo import → observed/high; curated
  catalog/manifest → declared/medium). Deterministic; tested.
- **F002 unresolved edges become visible, not dropped** — stop silently discarding
  unresolved references (external/stdlib imports, unresolved authored refs). Emit
  them as `evidence_basis=inferred`, `confidence=low`, flagged unresolved, so
  "missing evidence is visible" instead of invisibly absent. Tested.
- **F003 extractor-coverage block** — a top-level `coverage` block enumerating which
  extractors ran, which evidence kinds are covered vs missing/not-applicable for
  this repo, and an overall coverage + confidence summary. Honest for absent kinds
  (e.g. `swift: missing`, `build_config: unavailable`, `adr: not_found`). Tested.
- **F004 as_built/intent layers + diff taxonomy (schema-only)** — split the model
  into an `as_built` layer (today's nodes/edges) and an `intent` layer (claim shape
  defined, EMPTY in v0 — no ADR ingestion), and define the `diff` taxonomy
  (`aligned | drifted | unverified | implemented_undocumented |
  documented_unimplemented | conflicting_dependency | stale_adr | unknown_confidence`)
  with an empty/placeholder diff list. Tested that the shape exists and is honest
  about its emptiness.

## Sequence
F001 (per-element evidence fields) → F002 (unresolved-edge visibility, reuses F001
fields) → F003 (coverage block) → F004 (layer split + diff taxonomy). All
contract/producer + tests; no extractors, no ADR ingestion, no UI.

## Out of scope (explicit — later plans)
- ADR/doc extractor + as-built<->intent reconciliation (Plan B).
- Swift/Gradle/Xcode/JS/routing/API-client/DB/infra extractors (Plan C+).
- Two-layer UI render, drift surfacing, user annotation/correction (Plan D).
- Promoting the contract to an agent-conventions JSON Schema (deferred until the
  shape settles against ≥1 consumer).
