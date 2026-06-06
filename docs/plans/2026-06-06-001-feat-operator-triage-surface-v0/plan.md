---
id: 2026-06-06-001-feat-operator-triage-surface-v0
title: Operator triage surface v0 — one model, two renderers (agent brief + glanceable GUI)
type: feat
tier: cross-cutting
status: draft
date: "2026-06-06"
goal_type: new_feature
description: >
  The dashboard renders raw, unreconciled action inventory (313 fleet items at last
  count) as an undifferentiated wall, so the human cannot tell what needs them. The fix
  is not a prettier screen; it is a triage MODEL that is the single source of truth, with
  the agent operator brief as the primary surface and a glanceable GUI as the inspectable
  evidence surface. v0 builds the model first (a derived operator_bucket per item +
  dedupe + gate reconciliation + a data-quality envelope), then renders it for an agent
  (operator brief) and a human (triage view). Safe-tier application is opt-in, dry-run,
  logged, and reversible. Every feature's acceptance is a named operator JOURNEY proven on
  real state, not DOM-render correctness — the gap that let the 313-card wall ship.
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
---

# Operator triage surface v0

## The reframe (locked with the operator)
> The dashboard should not be the primary place a human decodes DontPanic. The primary
> surface is the operator agent's brief: "here is what needs you, here is what I can run,
> here is what DontPanic already handled." The dashboard becomes a structured state
> projection and an inspectable evidence surface.

The human works inside Claude / Codex / Cursor / a terminal, not a dashboard. So the agent
operator reads the triage and guides the human; the GUI exists so the human can audit that
guidance.

## What the prototype actually proved (and did not)
`docs/prototypes/triage_digest.py` bucketed the real 313 fleet items heuristically and
showed ~26 reach a human, ~4 after dedupe. That demonstrates the **shape** — the dashboard
shows raw inventory instead of operator-ready triage — **not** an exact number. The real
number is an OUTPUT of this plan (after dedupe + gate reconciliation + a derived bucket),
never a claim made ahead of the data contract.

## The model (source of truth — F001)
A single, pure, total classifier assigns every item exactly one `operator_bucket`, derived
(never producer-asserted) from the reconciled inputs (`resolution_class`, `automatable`,
`audience`, gate-state reconciled against plan status, and `safety_class` consumed from the
repair projection):

- `needs_auth`     — a human with credentials must act (capability setup, cloud login)
- `needs_decision` — a human must judge (a LIVE gate approval)
- `agent_runnable` — a command resolves it, operator audience, no credentials/judgment
- `auto_safe`      — reversible derived-state DontPanic may apply (a strict subset of automatable)
- `quiet`          — info/advisory; suppressed by default but inspectable
- `uncertain`      — cannot be confidently classified; surfaced, never silently hidden

`uncertain` is the render-truth contract (plan 2026-06-04-005) applied to triage: when an
input is missing/stale, the item is surfaced as uncertain with a data-quality reason, not
fake-bucketed clean. Distinctions kept separate, NOT collapsed: `resolution_class` (how it
clears) / `automatable` (a command exists, no judgment) / `safety_class` (may DontPanic
apply it) / `operator_bucket` (who acts now). `safety_class` stays in the repair projection;
the classifier consumes it rather than moving it onto the ActionItem envelope.

## The journeys (the missing acceptance contract)
Every renderer feature is accepted by proving a NAMED journey on real producer state, not
by asserting a DOM node exists.

Human (operator):
- H1 — sits down → "does anything need me?" → ≤N human items in <10s, nothing else.
- H2 — agent ran things → "what did it do and change?" → verify without reading source.
- H3 — a gate waits → "should I approve?" → decide from the evidence in place.
- H4 — something is stuck → "why, and the one move?" → the single unblock.
- H5 — glance → "is the install safe to keep using?" → one honest line.
- H6 — distrusts the triage → "show everything and WHY each item is where it is."

Agent (operator-agent):
- A1 — boot → "state; what can I run alone; what must I escalate?" → run-plan + escalation list as data.
- A2 — about to act → "safe to batch / ordering / human-gated?" → runs the safe set only.
- A3 — acted → "report back truthfully" → feeds H2.
- A4 — data incomplete → "do not lie" → narrates uncertain, never fabricates.

## The four phases → features
1. **Triage data honesty (model).** F001 derived `operator_bucket` + data-quality envelope;
   F002 dedupe by `dedupe_key`; F003 gate reconciliation against plan status.
2. **Agent-facing operator brief.** F004 `dontpanic operator brief --json|--text` renders the
   model: needs-human / agent-runnable / auto-safe / quiet / uncertain, allow-list vs
   escalate-list, data-quality warnings, honesty contract.
3. **Safe-tier application.** F005 opt-in apply of `auto_safe` only — dry-run first, logged
   evidence, reversible, never credentials / approvals / project mutations.
4. **Glanceable GUI.** F006 the human triage default view (needs-you + health + blocked);
   F007 the inspection/evidence surfaces (decision drawer, what-was-handled log, why-hidden
   inspector).

## Constraints / decisions
- `operator_bucket` is DERIVED by one classifier; producers stay dumb. One function = one
  truth for both renderers.
- Auto-run is NOT default. Safe-tier apply is opt-in, dry-run-first, logged, reversible.
- The GUI is the inspectable evidence surface, not an optional glance. The agent compresses;
  the GUI audits the compression.
- Naming: `dontpanic operator brief` (not `brief`) — `dontpanic agent brief` already exists
  as the setup/operating brief.
- The narration must not outrun the data contract: the brief shows uncertainty/staleness
  rather than asserting a clean number.

## Bugs this fixes (surfaced by the prototype)
- `operator_bucket`/`safety_class` absent from the ActionItem envelope → everything
  fail-closes to human-required (the 180/313 mislabel). Fixed by the derived classifier.
- Approval items duplicated 6–8× per gate. Fixed by F002 dedupe.
- Stale gates from closed/abandoned plans surfaced as live approvals. Fixed by F003.

## Non-goals (v0)
- No embedded shell/PTY (governance read-only contract preserved; a command bar / safe-tier
  button is the bounded affordance, considered later).
- No BLOCK enforcement; v0 surfaces and applies-on-request only.
- No fleet-state serve-path unification (build writes `~/.dontpanic/dashboard/`, serve reads
  `<repo>/dashboard/state/`) — named as a dependency for the GUI feature, fixed there or deferred.

## Target

```yaml
target_env: dev
target_project: none
```
