---
id: 2026-08-10-001-fix-gate-identity-in-approval-copy
title: Approval copy names the gate it actually paused on
type: fix
tier: cross-cutting
status: ready_for_audit
date: "2026-08-10"
description: >
  When the supervisor pauses for approval it renders a gate name that is not
  the gate it paused on. The emit site never records the pending gate, and the
  renderer fills the empty gate slot with the stage instead. The falsehood does
  not stop at prose: it reaches the copy-pasteable command, so the command
  offered to the operator names a gate that is not pending. This plan makes the
  pending gate an explicit fact at the emit site, stops the renderer inventing a
  gate from the stage, and adds a standing guard that fails any render naming a
  gate absent from its source event.
motivation: >
  Driving the real emitter proves it. Two of the four call sites pass a stage
  label that is not a gate at all — `supervisor.py:1316` passes
  `stage="general"` and `supervisor.py:2021` passes `stage="upfront"`, each
  with `pending_gates=gate_check.unmet`. `_gather_fields` derives the `{gate}`
  format field from `gate`/`subtype` only, and `subtype` is the stage, so the
  render reads:

      Supervisor paused at gate `general` (stage `general`).
      dontpanic approve <plan> general

  when the gate actually pending is `pre_merge`. `general` and `upfront` are
  not members of the gate vocabulary, so the printed command cannot succeed
  under any approval. An operator who pastes it does not clear the gate that is
  blocking. This is the honest-commands rule failing in the one place it exists
  to protect: the moment a human is asked to act.

  Post-F005 correction (2026-08-13, see evidence/2026-08-13-live-false-gate-capture.md
  and D003). This plan was first written against a pre-F005 emitter that
  published `technical_metadata={}`. 2026-08-09-002 F005 has since landed and
  **already publishes the pending gate** under `technical_metadata['pending_gates']`,
  which is why the reference line now names the real gate. F005 deliberately
  left the command path alone — its acceptance 7 forbade moving any exact
  command. So the emit-site half of this plan is done, and what remains is
  purely a renderer bug: the truth sits in the same mapping as the falsehood,
  one key away, and `_gather_fields` reads the wrong one.

  Two things kept this invisible. First, plan 2026-08-09-002 was written against
  an idealized description of this render — its motivation quotes "gate
  `pre_merge` (stage `implement`)", output the empirical capture shows has never
  been produced — so the plan meant to improve approval copy encoded the bug as
  its baseline. Second, `_reference_gate_stage` (2026-08-09-002 F005) already
  reasons correctly about this exact hazard, warning in its own docstring that
  "a reference line that names a gate it does not have is worse than one that
  stays quiet", but that judgement guards only the new reference line and never
  reached the template path that builds the command.

  The defect is deliberately not fixed inside 2026-08-09-002 F005. That feature
  is prose-only by contract — "Keep every exact command and the honest-commands
  rule unchanged" — and correcting the command is by definition a command
  change. See D016 on that plan.
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
  - ux
dependencies:
  - 2026-08-09-002-feat-decision-brief-at-gates
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Approval copy names the gate it actually paused on

## Target

```yaml
target_env: dev
target_project: none
```

- **repo:** `DontPanic` only. No other repository may be written.

## Problem / Motivation

The gate-pause render states a gate the supervisor did not pause on, and that
false gate propagates into the command the operator is told to run. Verified by
driving the real emitter at each of its real call sites, not by reading
templates:

| call site | `stage` passed | pending gate (truth) | rendered gate | rendered command |
|---|---|---|---|---|
| `supervisor.py:2352` | `pre_impl` | `pre_impl` | `pre_impl` ✓ | correct ✓ |
| `supervisor.py:2641` | `pre_merge` | `pre_merge` | `pre_merge` ✓ | correct ✓ |
| `supervisor.py:1316` | `general` | `pre_merge` | `general` | `dontpanic approve <plan> general` |
| `supervisor.py:2021` | `upfront` | `breaker:iteration_cap` | `upfront` | `dontpanic approve <plan> upfront` |

The two honest rows are honest by coincidence: their stage happens to equal
their gate, so the alias lands on the right answer. The two false rows can
never coincide, because `general` and `upfront` are not gates.

`technical_metadata` at emit is `{'pending_gates': 'pre_merge', 'stage': 'general'}`
— the truth is present. The rendered event carries `pending_gates: 'pre_merge'`
and gate `general` in the *same mapping*, disagreeing with each other. This is
a renderer reading the wrong key, not a producer omitting a fact.

## Proposed Approach

Point the renderer at the fact the emitter already publishes, remove the
fallback that concealed the gap, then make the class of bug non-recurring with
a guard rather than a spot test.

1. `_gather_fields` derives the `{gate}` field from `technical_metadata['pending_gates']`.
2. It stops falling back to `subtype`. A gate that is not known is not rendered
   — the precedent `_reference_gate_stage` already set.
3. Multi-gate pauses get a defined rendering. `pending_gates` is already a
   comma-joined string, so substituting it naively yields
   `dontpanic approve <plan> pre_merge, on_escalation`, which is not runnable
   either.
4. A standing invariant test: for every renderable kind, no rendered slot may
   name a gate that is not present in the source event.

## Scope (in)

- `supervisor._emit_gate_paused_discord` gate metadata
- the gate slot in `event_copy._gather_fields` and any template consuming it
- the rendered `exact_command` for gate-shaped kinds
- regression + invariant tests

## Scope (out)

- The impact-first headline rewrite (2026-08-09-002 F005 owns that prose).
- Any other field `_gather_fields` aliases. If the audit finds sibling
  aliases, they are recorded as findings, not fixed here.
- North-star README restyle (2026-08-13-001). F003 only adds the honest-command fact.

## Landing page

This is a **user feature**: every operator who pastes the approve command
is affected. Close does not update README. F003 is the named acceptance
for README + CHANGELOG. Prefer extending 2026-08-09-002 F010's line
over a new section.

## Dual lens

Dogfood: we were bitten by our own false command. User feature: any
project running DontPanic gates gets the true command. The README line
is how a stranger knows.

## Acceptance

Each feature's `acceptance` in `features.json` is the binding contract.

## Risks

- Other emit sites may depend on the subtype→gate alias to render a gate at
  all; removing it could silently blank a gate elsewhere. F002's invariant test
  is what converts that risk from silent to loud.
- `pending_gates` is a list. Multi-gate pauses need a defined rendering rather
  than an arbitrary first element.
