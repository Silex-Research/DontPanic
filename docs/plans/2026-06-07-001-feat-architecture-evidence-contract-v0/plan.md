---
id: 2026-06-07-001-feat-architecture-evidence-contract-v0
title: Architecture evidence contract v0 — source_kind + evidence_basis + confidence + provenance + extractor-coverage + as_built/intent layers + diff taxonomy (contract-only)
type: feat
tier: cross-cutting
status: completed
date: "2026-06-07"
goal_type: new_feature
description: >
  Make the architecture surface honest about WHAT IT CAN PROVE. Add an evidence
  contract to the view-state the interactive component map (plan 2026-06-06-007)
  already consumes, so the map stops implying "this IS the architecture" and starts
  asserting "this is the architecture DontPanic can prove from current evidence."
  Every node and edge carries source_kind (WHERE the evidence is) + evidence_basis
  (HOW it is known) + confidence + provenance refs; unresolved refs are emitted as
  unresolved/low-confidence instead of being silently dropped; a top-level
  extractor-coverage block states which evidence kinds are covered vs missing (so a
  Swift app with no Swift extractor renders missing_extractor coverage, not a
  confident Python-shaped map); the model splits into as_built vs intent layers and
  defines the as-built<->intent diff taxonomy (intent and diff may start empty).
  This generalizes the render-truth trust boundary from per-node liveness to the
  architecture model itself.

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

## Target

```yaml
target_env: dev
target_project: none
```

## Contract (v0 enums + rules)

`source_kind` answers **WHERE the evidence is** (closed enum). `evidence_basis`
answers **HOW it is known** — they are orthogonal axes, never conflated:

```yaml
source_kind:   code | build | manifest | config | infra | test | doc | adr | runtime | external | unknown
evidence_basis: observed | declared | inferred | unresolved
```

- v0 only POPULATES the kinds the current crawler can prove
  (`code`/`manifest`/`test`/`doc` for nodes; `external`/`unknown` for unresolved
  edge endpoints). The full enum is reserved so later extractors don't churn it.
- `inferred` is an evidence_basis, NOT a source_kind (review fix). Curated
  command catalogs / manifests are `evidence_basis=declared`, not forced into
  observed or inferred.

**Confidence precedence (rule, not examples — evaluate top-down, first match wins):**

```yaml
high:   parsed from source/build artifact with a RESOLVED endpoint (observed)
medium: declared/curated from a manifest/catalog/doc that cites a source_path (declared)
low:    unresolved | name-matched | heuristic | no extractor coverage (inferred/unresolved)
```

**Extractor-coverage statuses (F003) — distinct, not collapsed:**

```yaml
covered          # an extractor ran and produced evidence of this kind
not_found        # extractor exists + ran, but the repo has no such artifact (e.g. no docs/adr/)
missing_extractor# the repo HAS this evidence kind but DontPanic has no extractor for it (e.g. Swift)
not_applicable   # this evidence kind cannot apply to this repo (e.g. gradle in a pure-Python repo)
error            # extractor ran and failed
```

`missing_extractor` is the load-bearing honesty case: it must drive coverage/confidence
DOWN so a Swift repo never renders a confident map. `not_applicable` does not.

## Features
- **F001 evidence fields on every node + edge** — emit `source_kind`,
  `evidence_basis`, `confidence`, and a `provenance` block (`source_path` +
  `extractor` id + resolution method) on every node and edge `build_view_state`
  emits, per the enums + precedence rule above. Derived from signals already
  present; no new extractors. Deterministic; tested.
- **F002 unresolved refs become visible, not dropped** — stop silently discarding
  unresolved references (external/stdlib/third-party imports, unresolved authored
  refs). Emit them as `evidence_basis=unresolved`, `confidence=low`,
  `source_kind=external|unknown`, flagged unresolved, so "missing evidence is
  visible" instead of invisibly absent. Tested.
- **F003 extractor-coverage block** — a top-level `coverage` block enumerating which
  extractors ran, a per-evidence-kind status from the closed set above
  (`covered | not_found | missing_extractor | not_applicable | error`), and an
  overall coverage + confidence summary that `missing_extractor`/`error` pull down.
  Tested that absent extractors surface honestly and never as `covered`.
- **F004 as_built/intent layers + diff taxonomy (schema-only, backward-compatible)**
  — add an `as_built` layer (mirrors today's nodes/edges) and an `intent` layer
  (claim shape defined, EMPTY in v0 — no ADR ingestion), and define the `diff`
  taxonomy (`aligned | drifted | unverified | implemented_undocumented |
  documented_unimplemented | conflicting_dependency | stale_adr |
  unknown_confidence`) with an empty/placeholder diff list. **Backward-compat
  guarantee:** top-level `nodes`/`edges` REMAIN as compatibility aliases of
  `as_built.nodes`/`as_built.edges` in v0 so the 007 map and `.mmd` export keep
  working unchanged. Tested for both the layer shape and the alias equality.

## Sequence
F001 (per-element evidence fields) → F002 (unresolved-ref visibility, reuses F001
fields) → F003 (coverage block) → F004 (layer split + diff taxonomy, alias-preserving).
All contract/producer + tests; no extractors, no ADR ingestion, no UI.

## Out of scope (explicit — later plans)
- ADR/doc extractor + as-built<->intent reconciliation (Plan B).
- Swift/Gradle/Xcode/JS/routing/API-client/DB/infra extractors (Plan C+).
- Two-layer UI render, drift surfacing, user annotation/correction (Plan D).
- Promoting the contract to an agent-conventions JSON Schema (deferred until the
  shape settles against ≥1 consumer).
