---
id: 2026-05-11-001-infra-state-projection-adapters-meta
title: State-projection adapters meta — orchestrate plans 010 + 004 via DontPanic itself
type: infra
tier: local
status: completed
date: "2026-05-11"
goal_type: infra
surfaces:
  - infra
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  no_progress_threshold: 2
  wall_clock_hours: 8
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-09-003-feat-state-projection-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
description: |
  Umbrella plan that drives plan 2026-05-10-001 (printing-press-adapter
  skill) and plan 2026-05-09-004 (Firebase realtime adapter) through
  DontPanic's own supervisor/dispatch_volley loop instead of operator-
  driven hand-coding. Two purposes: (1) deliver both downstream plans,
  (2) dogfood the orchestrator on real work and convert every terminal-
  non-success into a finding for DontPanic itself.
motivation: |
  Plan 2026-05-09-003 just closed: state-projection contract +
  redaction + CLI + MCP + governance + dashboard exporter all green
  through 7 features. The orchestrator now has the substrate it needs
  to consume its own output. Until we run it against non-trivial real
  work, we don't know which of the orchestrator's failure modes still
  produce surprises in practice. This plan is the controlled dogfood:
  drive two non-trivial real downstream plans through the loop, capture
  every terminal-non-success in 2026-04-19-001 decisions.jsonl, promote
  to a `harness_frictions_v3` plan when findings cluster (≥3).

  Per memory pattern: harness_frictions_v1 (gate-state reconciliation +
  pre_impl auto-clear + verdict taxonomy) shipped after live volleys
  surfaced gaps; v2 (verdict-mismatch detector + plan-status sync +
  env-blocker short-circuit) shipped from a second batch. v3 inherits
  this lineage — only drafted when this plan's dogfood produces ≥3
  clustered findings.
---

# State-Projection Adapters Meta

## Thesis

DontPanic has reached the eat-your-own-dogfood threshold. We've shipped:

- 7-feature state-projection v0 (CLI + MCP + dashboard exporter)
- agent-conventions v1.6.0 schemas
- 8-tool MCP surface (read tools + mutating tools with confirm gate)
- Three rounds of harness-friction fixes (v1 + v2 shipped)

Two real downstream plans are draft/active and need to ship:

- **Plan 2026-05-10-001** (printing-press-adapter skill, active): 3
  features — author skill files, bump agent-conventions to v1.7.0,
  dogfood one external API.
- **Plan 2026-05-09-004** (Firebase realtime adapter, draft): 5
  features — repoint dashboard, sync daemon, Cloud Functions for
  mutations, Firestore rules, end-to-end smoke.

Rather than hand-code these, this meta plan drives both as **children
via nested orchestration** (per plan 2026-05-02-003 v1 mechanics).
Operator (you) approves pre_impl gates per feature; implementer agent
(Claude or Codex CLI) writes the code; auditor agent (the other vendor)
verifies; supervisor manages the loop with the circuit breakers we
already shipped.

The self-improvement loop:

- Every volley_terminal event lands in this plan's INBOX.
- Non-success terminations classify against the v0 taxonomy
  (`feature_defect / regression / interpretive_disagreement /
  redundant / already-known / spec-clarification` per memory).
- Findings appended to BOTH this plan's decisions.jsonl AND the
  long-running umbrella ledger `2026-04-19-001-infra-cross-agent-
  orchestration/decisions.jsonl`.
- At ≥3 clustered findings, draft `2026-05-1X-XXX-fix-harness-
  frictions-v3` plan with concrete fixes.

## Scope

In scope (this plan):

- Lock + drive plan 2026-05-10-001 (PP skill) features F001–F002 via
  dispatch_volley. Defer plan-010 F003 dogfood per operator quota
  policy.
- Lock + drive plan 2026-05-09-004 (Firebase adapter) features
  F001–F002 via dispatch_volley. Pause F003–F005 (deploy steps)
  until operator engages on Firebase/Tailscale credentials.
- Append each volley_terminal classification to decisions.jsonl
  (here) + cross-post to 2026-04-19-001 ledger.
- Promote clustered findings (≥3) to a v3 frictions plan when
  threshold tripped.

Out of scope:

- The actual deploy steps in plan 004 F003–F005 (Tailscale Funnel,
  Cloud Functions deploy, Firestore rules deploy). Operator-side.
- Plan-010 F003 paid PP invocation. Operator selects target service.
- Any change to the children's locked AC.
- Authoring a v3 frictions plan before the ≥3 threshold trips.

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance Summary

- Children plans 010 + 004 carry orchestration blocks pointing at
  this plan_id. Bidirectional metadata enables graph traversal.
- ≥1 feature per child shipped via supervisor.dispatch_volley
  (real volley, not hand-coded). Evidence: the corresponding INBOX
  + signoff.json artefacts in the child's evidence/.
- Every terminal-non-success on a dispatched volley classified and
  appended to BOTH ledgers within the same operator session it
  surfaces.
- Pre-impl + pre-merge human gates honored on each child feature —
  operator approval required per dispatch.
- When findings reach ≥3 cluster, a v3 frictions plan exists in
  `docs/plans/` (draft status acceptable).
