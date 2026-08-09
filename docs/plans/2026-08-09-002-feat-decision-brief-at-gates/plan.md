---
id: 2026-08-09-002-feat-decision-brief-at-gates
title: Decision brief at gates — ask for approval in product terms, not orchestration terms
type: feat
tier: cross-cutting
status: active
date: "2026-08-09"
description: >
  When DontPanic pauses for a human decision it asks the question in
  orchestration vocabulary — plan id, F-number, gate name, stage name — and says
  nothing about what is being built or what the person using the product will
  experience differently. The operator is asked a product question in a
  language that cannot express product. This plan adds a declared user-impact
  field to the feature contract, threads it to every approval surface as a
  three-part decision brief, and refuses to synthesize impact copy when it was
  never declared.
motivation: >
  The current gate_hit template renders "Approval needed on 2026-08-08-001 F003
  / Supervisor paused at gate `pre_merge` (stage `implement`)." Everything in
  that sentence describes the orchestrator. Nothing describes the change. The
  operator either approves blind, or re-derives the product context by hand from
  plan.md every single time — which is the tax that makes gates feel like
  bureaucracy rather than judgment. ActionItem carries `plain_consequence`, a
  slot for "one plain-language line a non-technical human can read for what
  happens if I do this"; on the event path it is populated with
  `rendered.detail`, so the plain-language field holds the orchestration prose
  rather than a consequence. The slot exists, is wired, and is filled with the
  wrong thing.
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
dependencies:
  - 2026-05-24-004-feat-event-messaging-v1
  - 2026-06-02-001-feat-control-plane-action-spine
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Decision brief at gates

## Target

```yaml
target_env: dev
target_project: none
```

- **repo:** `DontPanic`, plus `agent-conventions` for the schema bump (F001).
  No other repository may be written — F009 asserts this.
- **env:** local only. No cloud project, no deploy, no network. `target_env: dev`
  is the lowest rung the enum offers; nothing in this plan contacts a service.
- **command:** `pytest`, `dontpanic approve --help`, `dontpanic next`,
  `dontpanic dashboard build` for behavioral evidence.

## Problem / Motivation

Every human decision point in DontPanic — `pre_impl`, `pre_merge`,
`on_escalation`, `tier_promotion`, `cost_trigger`, and the seven circuit
breakers — reaches the operator through `event_copy.render()`. The templates
are structurally incapable of carrying product context:

```python
"gate_hit": _Template(
    headline="Approval needed on {plan_label}",     # → "2026-08-08-001 F003"
    why="Supervisor paused at gate `{gate}` (stage `{stage}`). "
        "Operator must approve before dispatch continues.",
    action="dontpanic approve {plan_id} {gate}",
)
```

`_plan_label()` resolves to `<plan_id> F00X`. `_Template` has exactly three copy
fields — headline, why, action — and none of them has anywhere to put "this
changes what people see when they open the Closet tab."

Three consequences, in increasing order of cost:

1. **The operator re-derives context by hand.** Open plan.md, find F003, read
   the description, reconstruct the product stake. Every gate, every time.
2. **Approval quality degrades.** The cheapest correct-looking action is to
   approve, because the prompt supplies no grounds on which to object. A gate
   that cannot be meaningfully declined is not a gate.
3. **The wrong reviewer is summoned.** A change with real UX consequence and a
   change with none produce identical-looking prompts, so there is no signal
   that this particular one warranted a designer's eye.

The repo already records the preferred register — `USER.md:15` asks for
"product outcome, architecture/infrastructure capability, and user/agent
experience" as the headline, with "F-ids, gates, schema validation, and verdict
names as supporting references." That is a stated preference with no mechanism
behind it. This plan is the mechanism.

## Proposed Approach

A **decision brief**: three elements the renderer must supply before asking a
human to decide.

| Element | Field | Source |
|---|---|---|
| **What changes** | `what_changes` | `features.json` description + plan title — already present |
| **Who feels it** | `user_impact` + `affected_audience` | **New declared field — cannot be derived** |
| **What approving does** | `decision_consequence` + `reversible` | Gate semantics — present but currently discarded |

Two structural obstacles, both verified against the code rather than assumed:

**The live path carries no metadata.** `event_copy.render()` accepts
`plan_meta` and `feature_meta`, but the production dispatcher in
`notify_event.py` calls `render(event)` and supplies neither. Any feature that
reads those parameters alone is dead code in practice, and every real gate
would keep reporting "impact undeclared." F003 therefore snapshots a typed
`DecisionBrief` onto `NotifyEvent` at pause-emission time, where plan and
feature data are genuinely in scope. One immutable snapshot then serves all
four sinks instead of each re-deriving at a different moment.

**The existing fields cannot carry three elements.** `plain_consequence` is
documented as "what happens if I do this" — that is element three, not element
two — and on the event path it is currently assigned `rendered.detail`, so the
plain-language slot already holds orchestration prose. `reversible` is
hardcoded `False` for every event-derived item. Repurposing `plain_consequence`
for product impact would leave no honest home for the decision consequence, so
the brief keeps four distinct fields and `plain_consequence` keeps its meaning.

The remaining features follow: **F005** rewrites the *renderable* approval-class
templates impact-first (only LIVE and DASHBOARD_ACTION kinds reach `render()`
at all); **F006** is the honesty rule — undeclared and stale impact are stated
plainly and **never synthesized**, because an LLM-invented UX claim inside an
approval prompt is fabrication at the exact moment a human has stopped
verifying and started trusting the text; **F007** and **F008** enforce surface
parity across CLI/INBOX and the notification sinks; **F009** captures the worked
example.

## Scope (in)

- `agent-conventions` feature-schema addition + version bump + subtree pull.
- `DecisionBrief` snapshot onto `NotifyEvent` at pause-emission time.
- `event_copy._Template` / `RenderedEvent` widening and `render()` population.
- Impact-first rewrite of the **renderable** approval-class templates.
- Undeclared / stale impact fallback copy + `plan lock` advisory lint.
- Parity across the four approval surfaces; tests and before/after evidence.

## Scope (out)

- **Generating `user_impact` from an LLM at render time.** See D002. Authoring
  help at *plan-writing* time is a separate, later question; the render boundary
  stays strictly non-generative.
- **Blocking on undeclared impact.** The lint warns; it never refuses. Making
  it blocking is a v1 decision to take from observed data.
- Changing gate semantics, the gate enum, or when pauses occur. This plan
  changes only what the human is told, never what the machine does.
- Backfilling `user_impact` across existing plans in other repos.
- Redesigning the dashboard's visual layout.

## Acceptance

1. A `pre_merge` gate emitted through the **real supervisor path** — with no
   caller passing `plan_meta` or `feature_meta` — renders a brief naming what
   changes, who feels it, and what approving does, with the plan id and gate
   name present but demoted below the product line.
2. The same gate on a feature with no declared `user_impact` renders "user
   impact not declared" and no synthesized claim; a stale declaration renders
   marked as stale rather than current. A test asserts no template interpolates
   model-generated prose.
3. All four surfaces (CLI approve, INBOX, notify, dashboard) render the same
   brief from the single snapshot; a parity test compares them field by field.
4. `dontpanic plan lock` on a plan whose features touch ux/ios/web/android
   surfaces without `user_impact` prints an advisory naming each feature, and
   exits 0.
5. Render coverage holds in four parts, replacing the incorrect "all 27 still
   render" claim — only LIVE and DASHBOARD_ACTION kinds ever reach `render()`:
   every one of the 27 kinds retains exactly one disposition; every previously
   renderable kind still renders; every renderable `needs_action` variant
   receives a brief; and featureless / plan-level events get a distinct honest
   fallback rather than a feature-shaped one.
6. `plain_consequence` on an event-derived ActionItem carries the decision
   consequence and is never equal to `rendered.detail`; `reversible` reflects
   the brief rather than a hardcoded `False`.
7. Before/after copy is captured in `evidence/` from a DontPanic-owned fixture
   with recorded provenance — no file outside DontPanic and `agent-conventions`
   is modified.

## Risks

- **Declared impact goes stale.** `user_impact` is authored once and the
  feature evolves. The feature schema carries only `verified_at` — there is no
  feature-modified or impact-declared timestamp, so a timestamp comparison is
  not available. D005 instead binds the declaration to the text it was written
  against via `description_hash`; a digest mismatch marks the brief
  possibly-stale rather than presenting old copy as current.
- **Ceremony creep.** A required field on every feature makes trivial plans
  more expensive to write. Mitigated by keeping it optional (D003) with
  `audience: none` as a first-class, one-word answer for genuinely internal work.
- **Copy bloat.** Three elements per notification could make Discord and
  terminal-notifier output unreadable. D006 caps summary length at render and
  defines per-surface truncation, with the dashboard as the only unabridged
  surface.
- **Two schemas to move.** The conventions bump must land and be subtree-pulled
  before F002 can consume it; F001 is deliberately phase 0 and alone.
