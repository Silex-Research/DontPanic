---
id: 2026-06-05-004-feat-applicable-conventions-disposition-gate-v0
title: Applicable skills/conventions disposition gate v0 — awareness → accountability
type: feat
tier: cross-cutting
status: draft
date: "2026-06-05"
goal_type: new_feature
description: >
  DontPanic checks whether a plan's DECLARED tests + acceptance pass. It does not yet
  reliably ask: "given the surfaces this change touches, which skills/conventions SHOULD
  have been applied, and did the plan dispose of each?" That gap is why dashboard design
  inconsistency slipped through every gate — the dashboard plans proved functional
  behavior ("the button copies the right command") but never had to prove product-surface
  quality ("a human understands the button copies rather than runs"). The pieces exist —
  skill_applicability.py (advisory match), skill_recommendation.py (recommend/invoke),
  sufficiency_auditor.py (textual contract coverage), sufficiency_gate.py (blocks on
  declared findings), plan_review/lint.py (surface tagging + surface_proof_missing warn),
  and agent-conventions resolver (trigger→skill reachability) — but they give DontPanic
  skill/convention AWARENESS, not ACCOUNTABILITY. It can recommend the right capabilities;
  it does not require the plan to DISPOSE of them (applied / not_applicable / deferred /
  waived-with-reason). This plan adds that disposition mechanism, seeds the dashboard/
  frontend sufficiency pack as the first concrete worked example, and wires an advisory
  plan-review check. v0 is warn-only; BLOCK for user-facing/mutation surfaces is deferred
  (demand-gated, needs false-positive data — mirrors 2026-06-05-002 F006).
---

# Applicable skills/conventions disposition gate v0

## The gap (sharp statement)
> DontPanic has skill/convention awareness, but not skill/convention accountability.

A plan can satisfy its own declared tests while never being forced to answer "what
standards apply to the surfaces I touched, and where is the evidence I applied them?"
The fix is a **disposition** primitive: for each skill/convention the platform deems
applicable to a plan's surfaces, the plan must record one of `applied`, `not_applicable`,
`deferred`, or `waived` (the last three require a reason).

## Correction to the original proposal
The proposal said "amend 2026-06-05-002." That plan is CLOSED (completed 6/6, committed) —
amending a closed plan by adding a feature breaks the locked-AC discipline. So this is a
NEW plan that builds ON 002's shipped pieces (qa-sufficiency-contract.md, the
surface_proof_missing lint, the surface tagging in plan_review/lint.py). It is also kept
SEPARATE from the dashboard UI remediation (plan 2026-06-05-003): this is orchestrator
governance, that is product UI. Different surfaces, different risk profiles, different
reviewers.

## Canonical surface mapping (load-bearing — added after review)
The four vocabularies in play do NOT naturally match: plan-review lint tags
(`dashboard`, `cli`, `schema`, `persistence`, `orchestration`, `core`), the
qa-sufficiency surface classes (read-only UI, interactive UI, mobile, command,
agent/MCP, mutation, external-integration, service/batch), the skill `applies_to`
values (`web`, `ux`, `backend`, `infra`, `security`), and agent-conventions topics.
Without a canonical bridge, awareness routes to the wrong (or no) standard — e.g.
`agent-browser` declares `[web, ux]` but a dashboard plan derives `dashboard`. F001
defines ONE closed canonical vocabulary + an alias map. The seed table:

| canonical id | aliases folded in |
|---|---|
| `frontend-ui` | dashboard · read-only UI · interactive UI · web · ux |
| `command` | cli · command |
| `backend-api` | backend · api · service/batch · persistence · schema |
| `mobile-app` | mobile · ios · android |
| `agent-tool` | agent/MCP tool |
| `infra-deploy` | infra · deploy |
| `security-review` | security |
| `mutation` | mutation |

Unknown inputs resolve to an explicit `unrouteable` marker (never silently dropped).

## Scope boundary
- IN: **the canonical surface vocabulary + alias map (F001)**; derive a plan's canonical
  surfaces from its declared surface class + changed/declared paths (F002); a declarative
  sufficiency-pack registry keyed by canonical surface (F003) **plus an unrouteable-skills
  inventory** (skills with missing/malformed `applies_to` are listed, not silently skipped);
  the disposition vocabulary + a **dedicated per-plan ledger at `docs/plans/<id>/conventions.json`**
  (F004); an ADVISORY plan-review check (F005); and the **frontend pack seeded as the one
  concrete worked example**, dogfooded against BOTH a synthetic plan AND one real historical
  plan (the dashboard plan that missed the design-system disposition) (F006).
- OUT — STATED PLAINLY: this plan does NOT yet govern backend/API, mobile (iOS/Android),
  CLI, agent/MCP, external-integration, or infra/deploy sufficiency. It builds the registry
  shape + canonical mapping and seeds ONLY the frontend pack; the other packs are NAMED,
  demand-gated stubs whose item content is authored when a plan in that surface needs it.
- OUT (deferred): BLOCK enforcement (escalating the warn to a hard block for user-facing /
  mutation / security surfaces — incl. applied-without-evidence); auto-inference of
  disposition; cross-repo convention sync.

## Why this generalizes (per the proposal)
Frontend/mobile are most exposed (surface quality lives in layout/affordance/state/a11y
that unit tests miss), but the gap is platform-wide: CLI can pass unit tests with bad help
text / wrong exit codes / unsafe copy-paste; agent/MCP tools need schema clarity + secret
redaction + dry-run; backend needs contract/auth/idempotency/migration proof; infra needs
dry-run/rollback/observability. The registry models all of them; v0 only POPULATES the
frontend pack and leaves the rest as demand-gated stubs.

## Verification posture
This is a CLI/plan-review surface (not UI). Proof = pure-function unit tests over the
derivation + disposition check + registry, plus a dogfood run over a synthetic plan that
demonstrates the gate WOULD have flagged the Repair gap (a dashboard-surface plan with no
design-system disposition warns; a fully-disposed one is clean). Branch stays unmerged.

## Decision log
See decisions.jsonl.

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal: a plan-review governance mechanism (surface derivation + pack
registry + disposition ledger + advisory check). Pure-function + CLI surface; no
external services; no production deploy.
