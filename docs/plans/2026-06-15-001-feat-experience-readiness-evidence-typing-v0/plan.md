---
id: 2026-06-15-001-feat-experience-readiness-evidence-typing-v0
title: Experience Readiness — consumer-family evidence typing v0 (2a)
type: feat
tier: cross-cutting
status: draft
date: "2026-06-15"
goal_type: new_feature
description: >
  The TYPING/EVIDENCE half of the Experience Readiness Gate (split from
  2026-06-14-002 by operator decision, D025). Defines the consumer-family
  taxonomy, the closed surface_class + evidence_class vocabularies, the
  structured EvidenceRef fields (data_provenance/data_source/availability),
  the pure evidence-class typing rule, the dogfoodable agent-surface evidence
  harness, and the degraded-honesty + structured cross-surface-agreement
  checker. It proves the platform can DECLARE the intended consumer/surface,
  TYPE the required evidence, CAPTURE agent-class evidence, and CHECK honest
  degradation — but does NOT decide close blocking. Close-time enforcement is
  the sibling plan 2b (2026-06-15-002), which consumes this stable vocabulary
  and locks only after 2a merges.
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

This plan is the typing/evidence layer of the Experience Readiness Gate. The
original combined plan (`2026-06-14-002`) converged its typing layer across two
paid sufficiency rounds but the **enforcement** matrix (activation × posture ×
deferral × consumer-cardinality × no-journey) kept surfacing new high/critical
conceptual layers each round. Per operator decision (D025) the two are split:

- **2a (this plan)** — vocabulary + capture + checks. Mostly settled; the four
  round-3 typing findings are pinned here as D026–D029.
- **2b (`2026-06-15-002`)** — the `consumer_outcome_gate` and the enforcement
  posture/activation/disposition matrix. Built ON 2a's vocabulary; stays draft
  and does not lock until 2a is merged.

Grounding (substrate exists; this plan adds the typed vocabulary on top):

| Concern | Status | File |
|---|---|---|
| 8 qa surface classes; "enter the real surface" | exists, advisory | `docs/qa-sufficiency-contract.md` |
| Journey model (`surfaces[]`, `states`, `acceptance_signals`, `required_evidence`) | exists | `objective_contract.schema.json` |
| `EvidenceRef.type` enum (8 values) | exists | `features.schema.json` |
| Human/app evidence capture (web/iOS/Android/backend, typed-skip) | exists, mature | `runtime_evidence/` |
| in-process `mcp_server` (for F003 MCP source) | exists | `scripts/dontpanic_orchestrate/mcp_server.py` |
| Plan 1 canonical `normalize_identifier` / `operator_surface` / `agent_runtime` | merged (main da48bb3) | `invocation_context.py` |
| Closed surface_class/evidence_class enums; consumer families; structured EvidenceRef fields; agent evidence class | **ABSENT** | — |

## Features

- **F001 — Consumer-family taxonomy + evidence vocabulary (schema).** Closed
  `surface_class` enum (8 structural classes; legacy `mutation` → `claim_kind`),
  `SurfaceFamily` (human/agent) total mapping, `consumer`/`fixture_only` on the
  journey, and a single CLOSED `evidence_class` enum + `data_provenance` +
  structured `data_source`/`availability` on `EvidenceRef` (no invented
  `EvidenceRef.type` values). **Consumer×surface validation** (D026) and
  **availability-requires-data_source** (D027).
- **F002 — Evidence-class typing rule.** Pure
  `required_evidence_classes(surface_class, consumer, claim_kind)` returning
  explicit conjunctive groups (`a|b` = at-least-one) drawn only from F001's
  closed enum; checker → `satisfied | evidence_class_mismatch |
  seeded_masks_readiness`. Agent tool/contract transcript alone satisfies a
  read-only success; `structured_error` only for error-path claims (D028).
- **F003 — Agent-surface evidence class in the harness.** Three dogfoodable
  `EvidenceSource` adapters (CLI transcript; in-process MCP tool-call via
  `mcp_server`; schema/contract check), each setting `evidence_class` + a valid
  existing `EvidenceRef.type` + `data_provenance`, with honest typed-skip whose
  reason lives in `EvidenceRef.note` (+ artifact body for transcript/log
  sources) (D029).
- **F004 — Per-family degraded honesty + structured cross-surface agreement.**
  `required_data_sources` + `allowed_degraded_modes` on the journey; a pure
  checker over the structured EvidenceRef fields reports `degraded_dishonest`,
  treats typed-skip as honest-unavailability (never success), and flags
  `cross_surface_disagreement` keyed by `data_source`.

## Non-goals (deferred / out of scope)

- **Close-time enforcement** (the `consumer_outcome_gate`, activation rules,
  posture matrix, deferral/disposition) — sibling plan **2b**
  (`2026-06-15-002`), locks after 2a merges.
- The QuantRE Product Readiness plan (separate consumer-side plan).
- Re-building human-surface capture (already exists).
- Accessibility / visual-regression / empty-state depth.
- Webhook / background-job / repo-PR agent sources beyond the CLI+MCP+contract
  trio.

## Surfaces touched

schema (`claude/shared/schemas/` — journey + EvidenceRef fields, closed enums),
engine (`scripts/dontpanic_orchestrate/` — typing rule, harness agent sources,
degraded/agreement checker). No close-path or dashboard changes (that's 2b).

## Scope-lint note (advisory)

`plan-review` will flag `missing_prereq` on declared field/class names
(`surface_class`, `consumer`, `evidence_class`, `data_provenance`, `data_source`,
`availability`, `claim_kind`, `required_evidence_classes`,
`evidence_class_mismatch`, `seeded_masks_readiness`, `tool_call_transcript`,
`cli_transcript`, `contract_check`, `required_data_sources`,
`allowed_degraded_modes`, `capability_unavailable`, `degraded_dishonest`,
`cross_surface_disagreement`, `consumer_surface_validation`, `fixture_only`) —
all introduced/declared here — plus `over_surface`/`likely_timeout` heuristics on
the schema+model+validator producer pattern. Re-confirm at `pre_impl`.

## Decisions

See `decisions.jsonl`. Carried typing decisions keep their `2026-06-14-002`
numbers (enforcement decisions moved to 2b, leaving intentional gaps). Headline:
D001 human/agent consumer families; D006 `evidence_class`/`data_provenance` new
EvidenceRef fields, no invented `type`; D012 structured `data_source`/
`availability`; D014 `claim_kind` separate from surface; D017 typed-skip =
`availability=unavailable`+`data_provenance=degraded`; D018 closed
`evidence_class` enum; D024 closed `surface_class` enum (mutation→claim_kind);
D020 explicit set semantics; D023 typed-skip-vs-degradation evidence-SET
discriminator; **D025 the 2a/2b split; D026 consumer×surface validation; D027
availability-requires-data_source; D028 agent-transcript-sufficient (structured_error
error-path-only); D029 typed-skip reason location.**
