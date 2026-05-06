---
id: 2026-05-06-002-feat-post-impl-completion-audit
title: Plan F2 — Post-impl completion audit + cross-vendor goal-audit dispatch
type: feat
tier: cross-cutting
status: active
date: "2026-05-06"
goal_type: infra
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
dependencies:
  - 2026-05-05-002-feat-goal-governance-nested-orchestration-config
  - 2026-05-05-003-feat-objective-contract-and-sufficiency-audit
  - 2026-05-06-001-infra-runtime-evidence-harness
description: |
  **Plan F2 of the Goal Governance V1 sequence** (per
  `docs/GOAL_GOVERNANCE_V1.md` §9). Ships the second half of
  goal-completion governance: a post-impl completion auditor that
  walks the objective contract against feature close-out evidence +
  Plan G's captured `EvidenceRef` list, runs cross-vendor by default,
  classifies findings via F0's existing triage taxonomy, and gates
  plan-level close-out. Plan G unblocks F2 per D001 of Plan G; F2 is
  the consumer that turns G's harness output into a pass/fail gate.

  Four features split along independent verification and dependency
  boundaries (D001):

  - **F001 — Completion auditor module + findings/envelope.** Pure
    orchestration over already-shipped surfaces: reads
    `ObjectiveContract.completion_test.required_evidence` strings,
    walks each against the captured `EvidenceRef` list (from G's
    harness output), produces `CompletionFinding` objects, normalizes
    them into F0's `GoalGapFinding` shape so the existing classifier
    can run. **No new schema bump** (D002 — single-repo; existing
    agent-conventions v1.4.0 ObjectiveContract carries enough; richer
    completion-test rule shape lands in a follow-up after real use).
    No richer per-rule semantics in v1 — the matcher is exact-substring
    against `EvidenceRef.uri` / `EvidenceRef.note`, framed
    explicitly as a **v1 evidence-coverage heuristic, NOT a semantic
    completion proof** (D002). Findings envelope carries
    `audit_kind: "v1_evidence_coverage_heuristic"` so downstream
    consumers don't over-trust empty-findings as completeness. F1
    sufficiency pattern is the template.

  - **F002 — Cross-vendor dispatcher wiring for goal audit.** The one
    place we do NOT defer (D003): wire the existing
    `_resolve_goal_auditor_agent` (F003 of F1) into a real production
    dispatch path. Calls the resolved auditor (default: Codex when
    implementer was Claude) with the auditor prompt + completion
    findings, captures the audit transcript, and writes the result
    under `evidence/goal-governance/post_impl/audit/`. Honors the
    existing `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR` operator
    override; same-vendor refusal unchanged. F1's caveat (F005
    dogfood ran with same-vendor override) is what F2/F002 closes.

  - **F003 — Plan close/audit gate + CLI surface.** New CLI
    subcommand: `dontpanic plan close <plan-id>` runs F2's completion
    audit + cross-vendor dispatch + classification, then flips
    `plan.md` status from `active` → `completed` on success. Refuses
    when blocking findings exist unless `--ignore-completion-findings
    <reason>` is supplied. Operator override is durable but
    input-bound (D004): SHA-256 hashes of features.json + objective
    contract + completion findings + evidence manifest invalidate the
    override on drift. Mirrors F004 of F1's `dontpanic plan lock`
    pattern. Also adds a dispatch-time backstop in `supervisor.py`
    that catches hand-edited active→completed flips at the next tool
    action (mirror of F004's plan-lock backstop).

  - **F004 — Dogfood proof point + dispositions.** Plan-local static
    fixture: a synthetic completed-plan tree with intentionally
    incomplete runtime evidence (one missing required_evidence
    matcher, one journey gap). F2's auditor must surface ≥1
    materially-correct gap in each class (missing_evidence +
    journey_gap). Operator confirms PASS dispositions before flipping
    F004 to passes:true. Mirrors F1's F005 dogfood pattern but with
    plan-local fixtures only — no live historical-plan dogfood in v1
    (D005). Real-plan dogfood is queued as a follow-up.

  Single-repo plan (D002) — no agent-conventions schema bump in v1.
  Library-bound + CLI surface; no MCP exposure (D006). F0 triage is
  consumed via :func:`nested_orchestration.classify_goal_gap_cluster`
  unchanged; F2 normalizes its own findings into
  :class:`nested_orchestration.GoalGapFinding` and constructs the
  appropriate :class:`nested_orchestration.GoalGapClusterContext`
  before classifying (D007 — consume F0, do not redefine).

  **Capture-only invariant carried forward (Plan G D002).** F2 is
  audit, not capture. The harness call F2 makes is read-only against
  evidence already captured by feature close-outs; the harness itself
  is invoked through G5's `EvidenceCollector.collect()` only when an
  evidence manifest is missing for a still-active plan, which is the
  out-of-scope-in-v1 case (operator runs G's adapters at feature
  close-out time as today; F2 consumes the resulting refs).

  **Cross-vendor invariant carried forward (D006 / GG V1 §5).**
  Already enforced by F1's `_resolve_goal_auditor_agent` —
  same-vendor refusal unless
  `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR` is set truthy. F2/F002
  does NOT relax this; F2/F002 just adds the missing dispatch wiring
  so the resolved auditor is actually called.

  **No runtime adapters in F2 (D008).** F2 does not ship a new
  runtime evidence source. The five sources covered by Plan G (web /
  iOS / Android / backend / harness) are sufficient for v1.
  Additional sources land in their own plans, not here.

motivation: |
  F1 shipped the pre-impl half of goal-completion governance: a
  sufficiency auditor that catches gap classes before lock, plus a
  plan-lock gate that refuses lock on blocking findings. Plan G
  shipped the runtime evidence prerequisites: web / iOS / Android /
  backend / common harness adapters that capture EvidenceRef
  artifacts during feature close-out.

  Without F2, the post-impl half is missing: nothing checks that the
  EvidenceRef artifacts actually satisfy the
  `ObjectiveContract.completion_test.required_evidence` rules at
  plan-level close-out. The current close-out flow is operator-
  hand-edited (mirroring F1's pattern of writing a close-out memo +
  flipping status); operators can ship a plan as completed even when
  half the required evidence is missing. F1 deliberately left this
  gap because the post-impl audit needs runtime evidence to walk
  against — and that didn't exist until Plan G closed.

  G is now closed (commit `0715bc7`); F2 is unblocked per Plan G's
  D001. F2 is the next chunk that closes the loop:

  - F1 catches sufficiency gaps before lock.
  - Implementation produces EvidenceRef artifacts via Plan G adapters.
  - F2 catches completion gaps before close-out.

  The cross-vendor dispatcher is in F2 specifically because F1's F005
  dogfood ran with `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR=1` set
  (Claude was both implementer and auditor). That caveat was
  acceptable for a dogfood pass but not for the first production
  post-impl audit. Shipping F2 without real cross-vendor dispatch
  would repeat the F005 caveat at the production close-out boundary
  — exactly where adversarial review matters most.

  Per the F2 lock answers (operator turn 2026-05-06), defaults are
  conservative (single-repo, library + CLI, F004-pattern override,
  static plan-local dogfood) but the cross-vendor dispatcher is in
  scope because that's the one place deferring would repeat a known
  caveat at a worse place to deal with it.
---

# Plan F2 — Post-impl completion audit + cross-vendor goal-audit dispatch

The post-impl half of Goal Governance V1. Catches gaps between an
objective contract's `completion_test.required_evidence` declarations
and the actual `EvidenceRef` artifacts captured by feature close-outs.
Refuses plan-level close-out (`dontpanic plan close`) when blocking
findings exist unless an input-bound operator override is recorded.

Sequence position: **F0 ✓ → F1 ✓ → G ✓ → F2 (this plan)**.

## Feature roadmap

| Feature | Phase | Surface |
|---|---|---|
| F001 | 1 | Completion auditor module + findings/envelope (pure text-only orchestration) |
| F002 | 1 | Cross-vendor dispatcher wiring for goal audit (the one non-deferred bit) |
| F003 | 2 | Plan close/audit gate + `dontpanic plan close` CLI + supervisor backstop |
| F004 | 3 | Dogfood proof point — plan-local static fixture; auditor surfaces ≥1 materially-correct gap per class |

F001 + F002 are independent and can land in either order. F003
depends on F001 (consumes findings) + F002 (dispatches the audit).
F004 depends on F001+F002+F003 (the full pipeline) and is the
plan-level acceptance gate before close-out.

## Boundaries

- **D001:** Goal Governance V1 sequence dependency — F2 unblocks because
  Plan G closed (commit `0715bc7`); F1 + G are prerequisites and stay
  unmodified by F2.
- **D002:** Single-repo plan in v1; no agent-conventions schema bump.
  Existing v1.4.0 `ObjectiveContract.completion_test.required_evidence`
  string list is sufficient. **The substring matcher is a v1
  evidence-coverage heuristic, NOT a semantic completion proof.** It
  flags missing evidence (no captured ref matches a declared
  required_evidence string) and orphan journeys (zero captured refs
  for a contract user_journey); it does not certify journey
  correctness or assert that captured artifacts demonstrate intended
  behavior. Empty findings means "no obvious coverage gaps detected,"
  NOT "plan complete." Findings envelope carries
  `audit_kind: "v1_evidence_coverage_heuristic"` so downstream
  consumers (F003 plan-close gate, dogfood dispositions, future
  follow-ups) read the correct semantics. Richer per-rule schema
  (regex, structured assertions, journey-walk semantics) lands in a
  follow-up plan after real use shows the shape.
- **D003:** Cross-vendor dispatcher is IN SCOPE (F002). Reusing F1's
  `_resolve_goal_auditor_agent` for resolution; F2/F002 adds the
  missing dispatch wiring so the resolved auditor is actually called.
  Same-vendor refusal + `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR`
  override unchanged.
- **D004:** Override durability mirrors F004 of F1. SHA-256 input-bound:
  features.json + objective_contract + completion_findings +
  evidence_manifest. Override file persists at
  `evidence/goal-governance/post_impl/override.json`; drift in any
  input invalidates it.
- **D005:** Dogfood is plan-local static fixture in v1, NOT a live
  historical plan. Real-plan dogfood queued as a follow-up.
- **D006:** CLI yes (`dontpanic plan close <plan-id>`); MCP NO. External
  agent exposure follows after CLI behavior is stable.
- **D007:** F0 triage consumed unchanged via
  `nested_orchestration.classify_goal_gap_cluster()`. F2 normalizes
  its findings into :class:`GoalGapFinding`; classifier output drives
  the gate decision (`inline_fix` / `child_plan` / `follow_up_plan` /
  `operator_deferred`). If F0 shape is insufficient, record an F0
  follow-up — do NOT redefine in F2.
- **D008:** No new runtime adapters in F2. Plan G's five adapters
  (web/iOS/Android/backend/harness) are sufficient for v1.
- **D009:** Capture-only invariant from Plan G carries forward — F2 is
  audit, not capture. F2 reads existing EvidenceRef artifacts; it
  does not invoke G's adapters during the audit run (operators
  capture during feature close-out as today).
- **D010:** Dispatch-time backstop on plan-close path mirrors F004 of
  F1's plan-lock backstop. Hand-edited active→completed flips are
  caught at the next tool action that consults plan status.
- **D011:** Schema-insufficiency abort: if during F001 implementation
  the existing `ObjectiveContract.completion_test.required_evidence`
  string-list shape proves insufficient (e.g. matcher rules need
  structured fields), F001 STOPS and surfaces a cross-repo split
  proposal before committing. Default is single-repo; abort is the
  pressure-release valve.
