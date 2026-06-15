---
id: 2026-06-14-002-feat-experience-readiness-gate-v0
title: Experience Readiness Gate v0 — consumer-family evidence typing with close-time enforcement
type: feat
tier: cross-cutting
status: draft
date: "2026-06-14"
goal_type: new_feature
description: >
  Add a fourth gate class — Experience Readiness — that proves the intended
  CONSUMER (human or agent) can complete their journey with evidence matching
  their surface, on real or honestly-degraded data, and ENFORCES it at plan close
  rather than only warning. Organizes surfaces into two consumer families, turns
  evidence-class typing into a checked rule, adds the dogfoodable agent-surface
  evidence class, distinguishes seeded fixtures from real/degraded data, treats a
  typed-skip as proof of honest unavailability (not journey success), and at plan
  close BLOCKS or requires explicit disposition for declared consumer-facing
  outcomes on product-class plans. Extends objective_contract, the EvidenceRef
  schema, the runtime-evidence harness, and completion_auditor rather than
  re-implementing them.
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

The originating critique is right: DontPanic "accepted the wrong evidence class
for the claim being closed" — a gate-design problem — and the follow-up sharpens
it: human and agent consumers are two first-class surface families. Lock-review
adds the decisive constraint: **enforcement posture**. A readiness gate that stays
warn-by-default does not prevent the failure mode it exists for ("plan completes
even though the consumer outcome was not proven"). So this v0 enforces at close.

Grounding shows the substrate exists but the gate does not:

| Concern | Status today | File |
|---|---|---|
| 8 surface classes incl. `agent / MCP tool`, "enter the real surface" | exists, **advisory** | `docs/qa-sufficiency-contract.md` |
| `surface_proof_missing` lint | exists, **warn-only**, human-UI keyword-biased | `plan_review/lint.py` |
| Journey model (`surfaces[]`, `states`, `acceptance_signals`, `required_evidence`) | exists | `objective_contract.schema.json` |
| Journey coverage at close (`journey_gap`) | exists, **uri-substring, non-blocking** | `completion_auditor.py` |
| `EvidenceRef.type` enum (screenshot, log, test_output, diff, audit_json, commit, url, file) | exists | `features.schema.json` |
| Human/app evidence capture (web/iOS/Android/backend, typed-skip honesty) | exists, mature | `runtime_evidence/` |
| Honest degradation (`missing_extractor`, typed-skip, render-truth) | exists, per-subsystem | architecture-evidence-contract; render-truth |
| Agent-surface evidence class; consumer families; **close-time enforcement**; seeded-vs-real marker | **ABSENT** | — |

## Enforcement posture (the core of this revision)

> Warn during implementation. **Block or require disposition at plan close** for
> declared consumer-facing outcomes on product-class plans.

- **Feature implementation:** evidence-class mismatch is advisory (warn).
- **Plan close, product-class plans** — `goal_type ∈ {parity, new_feature,
  migration, incident}` (exactly the set that already requires an
  `objective_contract`) **with declared consumer journeys**: close is **BLOCKED**
  unless each declared consumer outcome is (a) satisfied by matching, real (or
  honestly-degraded) evidence, (b) explicitly deferred as a non-goal, or (c)
  operator-dispositioned.
- **Internal substrate plans** — `goal_type ∈ {mechanical, infra, refactor}`:
  advisory unless the plan opts in.

This maps the critique's "product/migration/readiness → block" onto the existing
`goal_type` enum (there is no `product`/`readiness` goal_type; the
objective-contract-required set is the product-class proxy) and preserves low
false-positive risk without making the gate toothless.

## Features

- **F001 — Consumer-family taxonomy + evidence vocabulary (schema).** Map the 8
  existing surface classes into two families (`human`, `agent`); add `consumer`
  (`human | agent | both`) to the journey model. Add an `evidence_class`
  vocabulary as a NEW optional field on `EvidenceRef` — **without inventing new
  `EvidenceRef.type` enum values**; each `evidence_class` maps to a valid existing
  `type`. Add a `data_provenance` marker (`seeded | real | degraded`) on
  `EvidenceRef`. (agent-conventions schema + model + validator + VERSION bump.)
- **F002 — Evidence-class typing rule.** Pure function from surface_class/consumer
  → required `evidence_class`(es), plus a checker that matches a claim's evidence
  by `evidence_class` AND `data_provenance`. **Seeded evidence does not satisfy a
  consumer-readiness claim unless the journey is explicitly `fixture_only`**
  (emits `seeded_masks_readiness`). Mismatch emits `evidence_class_mismatch`.
  Severity is warn at implementation time; the close gate (F005) decides blocking.
- **F003 — Agent-surface evidence class in the harness.** Three dogfoodable
  `EvidenceSource` adapters (CLI non-interactive transcript; in-process MCP
  tool-call transcript via DontPanic's own `mcp_server`; schema/contract check),
  each setting `evidence_class` + a valid existing `EvidenceRef.type`
  (log/test_output/file) + `data_provenance`, with honest typed-skip. Reuses
  `harness.py` Protocol composition.
- **F004 — Per-family degraded honesty + structured cross-surface agreement.** Add
  `required_data_sources` + `allowed_degraded_modes` (keyed by a shared
  data-source key, e.g. capability id) to the journey contract. A checker reports
  `degraded_dishonest` when a required source is absent without an honest human
  label or a structured agent `capability_unavailable`; **a typed-skip
  EvidenceRef counts as evidence of honest unavailability, never as journey
  success**; and `cross_surface_disagreement` compares **structured** capability-
  availability/provenance claims keyed by the shared data-source key — **not
  prose**.
- **F005 — Close-time enforcement + disposition.** Extend `completion_auditor` to
  emit `consumer_outcome_unproven` and apply the enforcement posture: a pure
  posture function returns block|advisory by `goal_type`; at close, product-class
  plans BLOCK unless each declared consumer outcome is satisfied, explicitly
  deferred, or operator-dispositioned. **Typed-skip and seeded evidence do not
  count as consumer-surface captures.** Requires ≥1 real (non-seeded) end-to-end
  journey per objective claim per declared consumer.

## Non-goals (deferred / out of scope)

- **The QuantRE Product Readiness plan** (route inventory, persona journeys,
  maps/ATTOM checks, appraisal export, persona signoff) — a separate consumer-side
  plan in QuantRE's repo, authored against this gate. DontPanic governs; QuantRE's
  toolchain executes its human surfaces. (D004.)
- **Re-building human-surface capture** (web/iOS/Android/backend already exist).
- **Default-blocking on internal substrate plans** (advisory unless opted in).
- **Accessibility / visual-regression / empty-state depth** (demand-gated).
- **Webhook / background-job / repo-PR agent sources** beyond the dogfoodable
  CLI + MCP + contract trio (demand-gated).

## Surfaces touched

schema (`claude/shared/schemas/` — journey + EvidenceRef fields), engine
(`scripts/dontpanic_orchestrate/` — typing rule, harness agent sources,
completion-auditor enforcement, plan-review wiring). No new dashboard surface in
v0; findings flow through existing completion-audit / operator-triage rendering.

## Scope-lint note (advisory)

`plan-review` will flag `missing_prereq` on declared field/class/finding names
(`consumer`, `evidence_class`, `data_provenance`, `data_source`, `availability`,
`claim_kind`, `evidence_class_mismatch`, `seeded_masks_readiness`,
`capability_unavailable`, `degraded_dishonest`, `cross_surface_disagreement`,
`consumer_outcome_unproven`, `consumer_outcome_dispositions`, `required_data_sources`,
`allowed_degraded_modes`, `fixture_only`) — all introduced/declared here.
F003 may flag `over_surface` (engine module writing under `evidence/`) — the
established runtime-evidence harness pattern. Re-confirm at `pre_impl`.

## Decisions

See `decisions.jsonl`. Headline: D001 human/agent consumer families; **D002
enforcement is block/disposition at close for product-class plans, advisory for
substrate**; D003 build the agent evidence class first (dogfoodable); D004 QuantRE
is a separate consumer plan; D005 reuse-not-duplicate; D006 `evidence_class`/
`data_provenance` are new EvidenceRef fields, no invented `type` values; D007
seeded evidence cannot satisfy readiness unless `fixture_only`; D008 typed-skip is
honest-unavailability evidence, not success; D009 cross-surface agreement compares
structured claims by shared data-source key; **D010 alignment with the merged Agent
Channel Interop v0 (main `da48bb3`): cli_agent/mcp_tool are evidence/consumer
surfaces (not operator_surfaces); agent/runtime + operator-surface + capability ids
normalize through Plan 1's `normalize_identifier` canonical id spaces; consumer
family {human,agent,both} is cross-referenced to — not conflated with — the
operator-role value domain.** **D012–D018 (round-1 sufficiency tightening, 2026-06-15):
D018 pin `evidence_class` as one closed enum (reconcile F002↔F003 drift: `contract_check`,
`cli_transcript` vs `terminal_transcript`); D012 keyed availability lives in structured
EvidenceRef fields `data_source`+`availability` (not prose); D013 `consumer=both` requires
both families proven; D014 `required_evidence_classes(surface_class, consumer, claim_kind)`
disentangles claim kind from surface; D015 the ≥1-real requirement is journey-EXECUTION
provenance — honest in-journey data-source degradation still satisfies; D016 deferral/
disposition are structured (non_goal naming {journey,consumer} / `consumer_outcome_dispositions[]`),
not prose; D017 typed-skip = `availability=unavailable`+`data_provenance=degraded`, no new
provenance value. (D011 = the auto-recorded `--allow-oversize` scope-gate override.)** **D020–D024 (round-2 sufficiency tightening, 2026-06-15): D024 pin a CLOSED `surface_class` enum (8 structural classes; legacy `mutation`→`claim_kind`); D020 explicit set semantics for `required_evidence_classes` (groups conjunctive, `a|b` = at-least-one); D021 the close BLOCK is a DETERMINISTIC pre-flip `consumer_outcome_gate` in `completion_gate.close_plan`, independent of the codex F0 triage (whose only blocking triage is `child_plan`); D022 `opted_in` sourced from plan.md frontmatter `experience_readiness_opt_in`, substrate-no-contract = gate no-op; D023 typed-skip vs honest-degradation discriminated at the evidence-SET level (presence of a real journey-execution ref), not the tuple. (D019 = the round-2 auto-recorded scope-gate override.)**
