---
id: 2026-06-15-002-feat-experience-readiness-degraded-honesty-v0
title: Experience Readiness — degraded honesty + cross-surface agreement v0 (2a-F004)
type: feat
tier: cross-cutting
status: draft
date: "2026-06-15"
goal_type: new_feature
description: >
  The degraded-honesty + structured cross-surface-AGREEMENT half of the
  Experience Readiness typing layer, CARVED OUT of 2a-core (2026-06-15-001) by
  operator split decision after F004 produced high findings in consecutive
  sufficiency rounds (per-family honesty, F002/F004 shared exclusion, and the
  objective-level comparison keying — which is conceptual, not an impl pin). It
  owns the pure checker: per-family degradation honesty, allowed_degraded_modes
  consumption, the typed-skip-vs-real evidence-set discriminator, and
  OBJECTIVE-LEVEL cross-surface availability/provenance agreement keyed by
  (objective, data_source). It CONSUMES 2a-core's shared EvidenceRef fields
  (data_source/availability/consumer_family/degraded_mode) and closed enums, and
  MUST NOT lock until 2a-core is merged.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
privacy_tier: internal
links:
  features: ./features.json
  objective_contract: ./objective_contract.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  audits_dir: ./audit/
---

## Target

```yaml
target_env: dev
target_project: none
```

## Frame

The Experience Readiness typing plan (2a) converged its core schema/typing/harness
across three sufficiency rounds, but **F004 (degraded honesty + cross-surface
agreement)** kept producing high findings every round — per-family honesty (r1),
the F002/F004 shared typed-skip exclusion (r2), and the **objective-level
comparison keying** (r3). Per operator decision, F004 is split into this focused
follow-up so 2a-core (F001–F003) can lock clean while the cross-surface
agreement *keying/comparison boundary* — a genuine modeling decision — gets its
own slice.

**Dependency:** consumes 2a-core's shared `EvidenceRef` fields
(`data_source`/`availability`/`consumer_family`/`degraded_mode`) + the closed
`surface_class`/`evidence_class` enums. **Do not lock until 2a-core is merged.**

## Feature

- **F001 — Degraded honesty + structured cross-surface agreement** (was F004 in
  the combined typing plan). A pure checker over 2a-core's structured EvidenceRef
  fields: (a) **per-family** `degraded_dishonest` (each required `consumer_family`
  must carry its own honest `availability=unavailable` for a down `data_source`);
  (b) `allowed_degraded_modes` consumption (a degraded ref is honest only if its
  `degraded_mode` is allowed); (c) typed-skip = honest-unavailability, never a
  satisfying capture (evidence-set discriminator, shared with 2a-core F002);
  (d) **OBJECTIVE-LEVEL** `cross_surface_disagreement` keyed by
  `(objective, data_source)`.

## Open question to settle before lock

- The exact **objective key** (journey `objective` id? a contract-level objective
  list?) and how EvidenceRefs are collected/grouped to it — this is the
  conceptual boundary that drove the split (D006).

## Non-goals

- The typing/schema/harness layer — sibling **2a-core** (`2026-06-15-001`); this
  plan consumes it.
- Close-time enforcement — plan **2b** (`2026-06-14-002`).
- QuantRE plan; rebuilding human-surface capture; a11y/visual depth.

## Surfaces touched

engine only (`scripts/dontpanic_orchestrate/` — the degraded/agreement checker
over 2a-core's EvidenceRef fields + journey `required_data_sources`/
`allowed_degraded_modes`). No schema additions (2a-core owns the fields).

## Decisions

See `decisions.jsonl` (D001–D007): D001 the split + dependency on 2a-core; D002
structural-not-prose; D003 per-family `degraded_dishonest`; D004
`allowed_degraded_modes` consumption via `degraded_mode`; D005 typed-skip
evidence-set discriminator + shared exclusion; **D006 objective-level comparison
keyed by (objective, data_source) — the carve-out's central decision**; D007
minimal human-family compatibility (additive fields, not a rebuild).
