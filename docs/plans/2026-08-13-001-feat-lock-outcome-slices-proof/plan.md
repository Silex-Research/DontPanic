---
id: 2026-08-13-001-feat-lock-outcome-slices-proof
title: Every lock names outcome, slices, and proof — in part or whole
type: feat
tier: architectural
status: completed
date: "2026-08-13"
description: >
  Every locked plan is scored on an outcome, the MECE slices that deliver it,
  and a cheap first-principle proof per slice. Missing outcome (and nothing to
  inherit) blocks lock. Everything else is a gap that can be accepted and paid
  at close. This is the user-facing product increment, not a DontPanic-only
  scorecard.
motivation: >
  Agents ship the right code for the wrong product. Sufficiency today grades
  whether a completion_test string exists, not whether the work named what
  becomes true, whether the slices overlap, or what measurement would falsify
  delivery. The contract must apply to every plan a user locks — a checkout
  fix and a new surface alike — without becoming a form.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  hard_stop: false
privacy_tier: internal
surfaces:
  - backend
  - docs
  - ux
dependencies:
  - 2026-08-09-002-feat-decision-brief-at-gates
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Every lock names outcome, slices, and proof

## Target

```yaml
target_env: dev
target_project: none
```

- **repos:** `agent-conventions` (F001) and `DontPanic` (F002–F003).
- **env:** local only. No network.
- **command:** conventions contract tests; `dontpanic plan lock` on fixtures.

## Dual lens

This plan **is** the user feature. Any repo that locks a DontPanic plan
gets the score. Dogfood is the same contract applied to this directory
(lite: one outcome, three slices, cheap proofs) — not a second PRD tree.

DontPanic does **not** start maintaining PRDs or ADRs for itself or for
users. The locked contract *is* the product document. `source_of_truth`
may point at a PRD the user already has. We do not author one.

## Problem

`delivers[]` names audience + capability + which features prove it. Close
still grades `passes` and heuristic evidence strings. There is no
**metric** — the measurement that would show the capability is true.

A nine-feature plan can lock with no outcome. A one-line fix is asked
the same nothing. Both are wrong.

## Proposed approach

One contract, sized to the work.

| | Fix | New product |
|---|---|---|
| Outcome | Inherit parent. One-line delta. | Required. No outcome, no lock. |
| Slices | Usually one. | MECE set. Overlap or a missing necessary slice is a gap. |
| Proof | One walk, request, or named test | One cheap metric per slice |

**Inherit. Infer. Block on one thing.** Missing proofs and messy slices
print as accepted gaps and become close checks. If defining the proof is
harder than the work, the proof is wrong.

Three features only. Do not grow this into a wizard, an intake engine,
or a README restyle beyond F003.

## Scope (in)

- `delivers[]` optional `proof` `{metric, method, surface?}` and optional plan-level `inherits`
- Lock score: outcome / slices / proofs; refuse only on missing outcome with nothing inherited
- README + CHANGELOG one-block (F003)

## Scope (out)

- `dontpanic intake` / Phase C placement interview (later child)
- PRD or ADR authoring
- Claude Design / Figma routing
- Admitted-claim handoff (`2026-08-12-001`)
- Parallel feature diamonds
- Making volleys faster except insofar as smaller plans are lockable

## Pace

This plan is three features. F003 is a cheap docs slice — do not volley
it through iteration-cap restarts. The contract exists so *later* user
plans stay one-slice when the work is a fix, which is the only way
calendar time drops from days to a sitting.

A 7M-token implementer turn is still a harness bug (`2026-08-12-001`
F005). This plan does not fix that.

## Acceptance

A fixture fix plan that inherits a parent locks with one delta slice and
one proof. A fixture new-feature plan with no outcome and no inherit
refuses lock. A fixture with an outcome and an accepted missing proof
locks and fails close until the proof runs or is deferred. README states
the rule in operator language.

## Risks

- Fat contract. Mitigation: block on one thing; inherit; cheap proofs.
- Two sources of truth (`delivers[]` vs a new object). Mitigation: extend
  `delivers[]`, do not add a parallel schema.
- Users feel a form. Mitigation: infer defaults (user-facing → walk the
  path; infra → named test); confirm, do not compose.
