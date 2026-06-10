---
id: 2026-06-09-001-feat-architecture-c0-weak-graph
title: Architecture C0 — language-agnostic weak graph baseline + tiered coverage
type: feat
tier: cross-cutting
status: completed
date: "2026-06-09"
goal_type: new_feature
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  objective_contract: ./objective_contract.json
description: >
  Give DontPanic a realistic architecture map for ANY tracked project immediately,
  without pretending it natively understands every stack. C0 establishes the
  language-agnostic baseline: a project detector + extractor registry + a Tier-0
  filesystem/package/config inventory graph that works for every repo, plus Tier-1
  heuristic (regex) dependency edges for common languages emitted as low-confidence
  /unresolved. Coverage is reported honestly per language AND per evidence-type with
  explicit ceilings ("Dependency confidence is low. No Swift extractor installed.").
  Precursor to Plan D (UI renders this coverage/diff honestly) and Plan C+ (stronger
  per-language extractors layered in over time).
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

DontPanic's as-built map is currently Python+JS-centric: a repo in an unextracted
language renders thin and the honesty lives only in a confidence ceiling. The right
model is a tiered one — Tier 0 inventory (every repo), Tier 1 heuristic imports, Tier
2 parser-backed (Python AST / TS-JS today), Tier 3 build/runtime — so DontPanic shows
*something useful and truthful* for an arbitrary app on day one and gets stronger as
extractors are added. "Native support" must mean "native extractor framework + honest
baseline," NOT "we magically understand every stack." This generalizes the existing
evidence contract (source_kind / evidence_basis / confidence / missing_extractor) from
Python+JS to a registry-driven, language-agnostic substrate.

## Features

- **F001** — project detector: from a repo root, detect languages, package managers,
  build systems, test frameworks, app frameworks, docs/ADR presence, and infra/config
  surfaces into a deterministic ProjectProfile. Pure, no network, graceful on empty.
- **F002** — extractor registry: a registry mapping (evidence_kind / language) →
  extractor + availability, so the system can declare available vs missing extractors
  for a given ProjectProfile. Generalizes the ad-hoc EXTRACTORS list; tier-aware
  (tier 0 filesystem, tier 1 heuristic, tier 2 parser, tier 3 build/runtime).
- **F003** — Tier-0 inventory + Tier-1 heuristic graph: a baseline as-built graph for
  ANY repo — nodes for directories, package/build/config manifests, test dirs,
  docs/ADRs, and detected infra surfaces (Tier 0, low/medium confidence) — plus
  Tier-1 regex/import-pattern edges for common languages emitted as low-confidence
  unresolved unless a relative target resolves. Tier precedence pinned: parser-backed
  (tier-2) edges supersede same-source heuristic edges — no duplicate low-confidence
  counterparts for parser-served languages. Contract-stamped; never drops;
  deterministic + bounded.
- **F004** — tiered coverage block: emit an architecture coverage object with an
  overall rollup (limited / partial / covered; deterministic pinned rules),
  per-language status (covered / missing_extractor / not_found) and
  per-evidence-type status keyed by ONE taxonomy unified with the architecture
  contract's source_kind enum (filesystem / code / manifest / build / test /
  config / infra / doc / adr / runtime) — every ProjectProfile detection class
  maps deterministically (and tested-totally) into it — with confidence ceilings
  that stay honest: an unextracted language shows its file/config graph AND a
  clear low-confidence note. Computed on project registration and inside
  build_view_state.
- **F005** — fixture-repo tests across Python, JS/TS, and Swift/Kotlin: assert the
  weak baseline renders for each, that imports are heuristic-low for the unextracted
  languages while filesystem/package coverage is present, and that the coverage block
  flags the missing Swift/Kotlin extractor without suppressing the Tier-0 graph.

## Non-goals

- No UI overhaul beyond the existing coverage display (Plan D renders it).
- No new parser-backed extractors for Swift/Kotlin/etc. (that is Plan C+; C0 only
  establishes the registry + honest "missing_extractor" reporting for them).
- No build/runtime (Tier 3) collection — reserved, declared not_found for now.

## Decisions
See `decisions.jsonl`.
