---
id: 2026-06-15-001-feat-experience-readiness-evidence-typing-v0
title: Experience Readiness — consumer-family evidence typing v0 (2a-core, F001–F003)
type: feat
tier: cross-cutting
status: active
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

- **2a-core (this plan)** — vocabulary + agent capture + the typing checker.
- **2a-F004 (`2026-06-15-002`)** — degraded honesty + cross-surface agreement,
  carved out (D055); consumes 2a-core's vocabulary.
- **2b (`2026-06-14-002`)** — the `consumer_outcome_gate` and the enforcement
  posture/activation/disposition matrix. Built ON 2a's vocabulary; stays draft
  and does not lock until 2a-core is merged.

**Scope of 2a-core (D060): shared vocabulary now, agent enforcement now, human
producer typing later.** F001 defines the FULL shared `EvidenceRef` vocabulary for
both human and agent families. F003 proves the AGENT producers populate it. F002's
fail-closed rich typing is ENFORCED on agent-family surfaces only; human-family
surfaces whose evidence lacks the new fields are `not_yet_typed` (legacy_untyped
compatibility), never invalid — human-surface field population is a named
follow-up, so nothing here contradicts the "don't rebuild human capture" non-goal.

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
  closed enum; checker takes the **full `EvidenceRef[]`** and returns a
  **per-`(surface_class, group)` result list** with statuses `satisfied |
  evidence_class_mismatch | seeded_masks_readiness | missing_provenance |
  not_yet_typed`, plus a **tri-state journey verdict** (D062) — `satisfied` /
  `agent_satisfied_human_pending` / `unsatisfied` — so the agent-now/human-later
  deferral is honest at the journey level, never a misleading failure. Agent
  tool/contract transcript alone satisfies a read-only success; `structured_error`
  only for error-path claims (D028). **Enforcement scope (D060): fail-closed rich
  typing applies to AGENT-family surfaces** (the surfaces F003 produces);
  human-family surfaces lacking the new fields return `not_yet_typed`
  (legacy_untyped compatibility), never a fail-closed rejection.
- **F003 — Agent-surface evidence class in the harness.** Three dogfoodable
  `EvidenceSource` adapters (CLI transcript; in-process MCP tool-call via
  `mcp_server`; schema/contract check), each setting `evidence_class` + a valid
  existing `EvidenceRef.type` + `data_provenance` + `surface_class` (the
  adapter's agent surface) + the shared fields, with honest typed-skip whose
  reason lives in `EvidenceRef.note` (+ artifact body for transcript/log
  sources) (D029).
- **(carved out) F004 — degraded honesty + cross-surface agreement** → moved to
  sibling follow-up **2a-F004** (`2026-06-15-002`) by operator split (D055), after
  F004 produced high findings in consecutive rounds (per-family, shared-exclusion,
  objective-level keying). 2a-core still defines the shared `EvidenceRef` fields it
  consumes.

## Non-goals (deferred / out of scope)

- **Degraded honesty + cross-surface agreement** — sibling follow-up **2a-F004**
  (`2026-06-15-002`); 2a-core owns the shared EvidenceRef fields, 2a-F004 consumes
  them. (D055)
- **Close-time enforcement** (the `consumer_outcome_gate`, activation rules,
  posture matrix, deferral/disposition) — plan **2b** (`2026-06-14-002`).
- The QuantRE Product Readiness plan (separate consumer-side plan).
- Re-building human-surface capture (already exists).
- **Human-surface field population + human-surface enforcement** — 2a-core defines
  the shared vocabulary for BOTH families but only ENFORCES it on agent surfaces
  (it produces those via F003). Stamping `surface_class`/`availability`/
  `consumer_family`/`data_provenance` onto existing human producers, and enforcing
  rich typing for human surfaces, is an explicit **follow-up** — human evidence
  lacking the fields is `not_yet_typed` here, not invalid (D060).
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
