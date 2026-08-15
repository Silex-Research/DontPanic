---
id: 2026-08-12-001-infra-admitted-state-and-process-behaviors
title: Admitted shared state and hidden process behaviors
type: infra
tier: architectural
status: draft
date: "2026-08-12"
description: >
  The next worker in a volley receives a rewritten findings list, not admitted
  state. This plan adds claim, decision, and hidden behavior contracts to
  agent-conventions, changes the implementer handoff to admitted claims plus an
  unfold pointer, and judges a small deterministic process set off envelopes
  DontPanic already writes.
motivation: >
  Today's research review (DeLM verified shared context, Google/MIT sequential
  penalty, Basis process supervision) maps onto one DontPanic hole: the
  implementer/auditor hop is still a summary bullet list. DecisionBrief already
  fixed the same class of decay for the operator. This plan applies that
  pattern to the agent-to-agent hop and adds process grades that do not depend
  on the final answer being right.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  hard_stop: false
verification:
  command: python3 claude/shared/schemas/v1.0/validate.py docs/plans/2026-08-12-001-infra-admitted-state-and-process-behaviors
privacy_tier: internal
surfaces:
  - backend
  - docs
dependencies:
  - 2026-08-09-002-feat-decision-brief-at-gates
  - 2026-04-19-001-infra-cross-agent-orchestration
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Admitted shared state and hidden process behaviors

## Target

```yaml
target_env: dev
target_project: none
```

- **repos:** `agent-conventions` (F001–F004) and `DontPanic` (F004–F007). No other repository may be written.
- **env:** local only. No cloud project, no deploy, no network.
- **command:** `pytest` for orchestrate + conventions contract tests; `python3 claude/shared/schemas/v1.0/validate.py` over existing plan dirs.

## Problem / Motivation

DontPanic's control plane is already the architecture the papers recommend: a deterministic supervisor, a cross-vendor validation bottleneck, durable contracts, fail-closed Evaluate. The remaining production failure is **admission**.

Round N+1 of a volley does not inherit grounded state. `prompts._findings_block` compresses the prior auditor into `[severity, category] issue → recommendation`. Evidence, failed hypotheses, and binding constraints drop. The full JSON still exists on disk; it is not what the next model is shown.

That is DeLM's "constraint softened in the merge" failure, inside a system that otherwise refuses LLM merges.

Separately, the platform grades **outcomes** (`features.passes`, `acceptance`, `completion_test`) and almost never grades **process**. An implementer can skip the named test, skip the primary evidence, and still get `signed_off` if the patch looks right. Basis's behavior specs are the missing object: hidden from the worker, judged on the trajectory.

## Proposed Approach

1. Add three contracts to agent-conventions in the existing house style (closed enums, `additionalProperties: false`, Pydantic twin, fixture parity tests).
2. Publish via VERSION bump + subtree pull. Existing plans must keep their current validation exit codes.
3. Change `_findings_block` / audit write path so the next implementer sees admitted claims and a path to unfold, not a rewritten narrative.
4. Judge a closed deterministic behavior set off `commands_run`, vendor pair, and declaration fields already on the audit envelope.
5. Document non-goals so later work does not absorb Hermes, a vector context layer, NOOA, or Claude-authored supervisor graphs.

The supervisor stays Python. Workers still do not declare victory into the ledger.

## Scope (in)

- `claim`, `decisions`, and `behavior` schemas + models + fixtures in agent-conventions
- Subtree pull into `claude/shared/`
- Findings handoff uses admitted claims + unfold pointer
- Deterministic behavior judges persisted beside the volley
- Platform-doc non-goals and harness/loop/graph vocabulary

## Scope (out)

- anydoc / Phase C intake (blocked on the intake runtime; adapter contract can be a later child)
- Independent-feature `parallel()` diamond
- LLM-as-judge for semantic behaviors
- Dashboard / INBOX rendering of claims and behaviors (may consume the new files later)
- Replacing Cursor, Replit, Claude Code, or any harness
- Activation UX / interactivity of DontPanic itself (plan `2026-08-13-001`)
- Outcome / slices / proof at lock (that is `2026-08-13-001`, not this)
- PRD or ADR authoring — DontPanic maintains work receipts, not a living PRD/ADR tree
- README restyle — this plan is not operator-landing-page work; F007 is PLATFORM.md only
- Hermes / AG-UI, vector indexes, knowledge graphs, NOOA rewrite, LangGraph

## Dual lens

Every feature in this plan is a **user feature**, not dogfood-only. agent-conventions consumers get the schemas (F001–F003). Any repo that runs a DontPanic volley gets admitted findings + unfold (F005) and deterministic process grades (F006). F007 is the only dogfood-shaped item (our PLATFORM.md), and it must state the user-facing rule, not only our architecture.

## Pace

This plan exists partly because a single implementer turn on `2026-08-09-002` read up to 7.5M tokens. F005 (gist + unfold) is the pace fix. Do not add features that start another nine-feature volley. Docs (F007) are a cheap slice: no adversarial cap-and-restart.

## Relationship to the lock contract

`2026-08-13-001` is the product increment: every locked plan names outcome, slices, and proof, in part or whole. This plan is the trust increment *after* a plan exists. Do not merge the two. Shipping better handoffs into a door people cannot open does not implement the north star.

## Acceptance

A later implementer in a fixture volley is shown only admitted claims and a resolvable audit path; rejected or ungrounded prose does not appear. Three-to-five deterministic behaviors produce `adhered | violated | n/a` from a real audit envelope without a model call. Every previously valid plan directory still validates. Docs name the non-goals.

## Risks

- Schema sprawl: three new contracts in one plan. Mitigation: each has its own feature and fixture set; F004 is the only publish step.
- Prompt change alters live volley quality. Mitigation: fixture-first; keep the full JSON path; do not invent claim text.
- Behavior judges that are too clever become a second LLM. Mitigation: V0 is boolean checks on existing fields only.
- This plan improves trust *after* a plan exists. It does not make DontPanic easier to start. That gap is explicit (D006) and belongs to the north-star audit, not this slice.

## Sequencing

F001 → F002 → F003 can land in agent-conventions in any order, then F004 publishes all three. F005 and F006 depend on F004. F007 can land anytime after D001–D005 are written.
