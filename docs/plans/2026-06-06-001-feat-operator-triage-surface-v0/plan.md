---
id: 2026-06-06-001-feat-operator-triage-surface-v0
title: Operator triage surface v0 — one model, two renderers (agent brief + operator-console workbench)
type: feat
tier: cross-cutting
status: completed
date: "2026-06-06"
goal_type: new_feature
description: >
  The dashboard renders raw, unreconciled action inventory (313 fleet items at last
  count) as an undifferentiated wall, so the human cannot tell what needs them. The fix
  is a triage MODEL that is the single source of truth, rendered identically by an agent
  operator brief (CLI) and a dual-mode operator-console workbench (GUI). v0 builds the
  model first (a derived operator_bucket per item + dedupe + gate reconciliation + a
  data-quality envelope), then renders it as an agent brief and a three-pane workbench the
  human can both observe and operate from. Safe-tier application is opt-in, dry-run,
  logged, reversible. Every feature's acceptance is a named operator JOURNEY proven on
  real state, not DOM-render correctness — the gap that let the 313-card wall ship.
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
---

# Operator triage surface v0

## The reframe (locked with the operator)
> The dashboard is not the only place a human decodes DontPanic. One triage model is the
> source of truth; the CLI operator brief, the operator-console GUI, and any agent all
> render the SAME model. The agent brief is primary when the human is inside
> Claude/Codex/Cursor/terminal; the operator console is primary when the human operates
> from DontPanic directly. Neither is subordinate — they are two renderers of one model.

The human works wherever they are. So the GUI must be a first-class **dual-mode operator
console** (observe while working elsewhere, or operate directly), not a read-only audit
pane.

## What the prototype proved (and did not)
`docs/prototypes/triage_digest.py` bucketed the real 313 fleet items heuristically and
showed the SHAPE: the dashboard ships raw inventory instead of operator-ready triage. It
did NOT establish an exact human-workload number — that is an OUTPUT of this plan (after
dedupe + gate reconciliation + a derived bucket), never asserted ahead of the data
contract. (Hence: no `<=N` cap; see D014.)

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
- `uncertain`      — cannot be confidently classified; surfaced WITH needs-you, never silently hidden

`uncertain` is the render-truth contract (plan 2026-06-04-005) applied to triage. Axes kept
distinct, NOT collapsed: `resolution_class` (how it clears) / `automatable` (a command
exists, no judgment) / `safety_class` (may DontPanic apply it) / `operator_bucket` (who acts
now). `safety_class` stays in the repair projection; the classifier consumes it.

## The journeys (the acceptance contract)
Every renderer feature is accepted by proving a NAMED journey on real producer state.

Human (operator):
- H1 — "does anything need me?" → ALL unique live needs_auth+needs_decision, deduped, non-human collapsed.
- H2 — "what did the agent/auto do?" → verify from the activity log + evidence.
- H3 — "should I approve this gate?" → decide from evidence shown beside it, no source-reading.
- H4 — "why is this stuck, and the one move?" → the single unblock.
- H5 — glance → "is the install safe?" → one honest status line.
- H6 — distrust the triage → "show everything and WHY each item is where it is."
- H7 — operate from the console → decide/approve/copy/run with confirm-gating + evidence per bucket.

Agent (operator-agent):
- A1 — boot → run-plan + escalation list as data.
- A2 — about to act → safe-to-batch / ordering / human-gated, runs the safe set only.
- A3 — acted → report back truthfully (feeds the activity log).
- A4 — data incomplete → narrate uncertain, never fabricate.
- A5 — terminal/agent handoff → console hands off a run-plan, agent executes externally, result is marked-run + evidence-attached + triage refreshed.

Parallel operations (GUI + Cursor + multiple terminal agents at once, local-machine):
- P1 — GUI open while Cursor acts on the SAME project → item shows running, then refreshes to handled/evidence.
- P2/P4 — terminal agent on a DIFFERENT project / a global config issue appears → scope chips separate `[PROJECT:x]` vs `[GLOBAL]`; no confusion.
- P3/P6 — two agents touch the same plan/gate, or the view is stale → conflict + stale (state_revision drift) surfaced BEFORE handoff/approval-intent.
- P5 — GUI ↔ terminal round-trip → work correlates back by `dedupe_key`/`run_id`; no duplicate item.

## Layout — the operator workbench (D017)
One model, three coordinated panes + status bar + activity strip + two modes.

```
+----------------------------------------------------------------------+
| DontPanic . Fleet Triage   SAFE . 4 need you . 178 handled . 3 unsure |
| Project: All v   Mode: Operator v   Refresh   Copy Brief   Terminal v |
+---------------+--------------------------------------+----------------+
| TRIAGE (left) | CURRENT WORK (center)                | CONTEXT (right)|
| Needs You 4   | Approval needed                      | [Evidence]     |
|  Auth 2       | onboarding-v0 . pre_merge            |  Plan          |
|  Decide 2     | Why now: features pass, merge gated. |  Diff          |
| Uncertain 3   | Actions:                             |  Tests         |
| - handled -   | [Approve][Request changes][Reject]   |  History       |
| Agent Can 174 | [Copy command][Send to agent v]      |  Why Hidden    |
| Auto-safe 4   |   (evidence lives in the right pane, |                |
| Quiet 109     |    not duplicated here)              |                |
+---------------+--------------------------------------+----------------+
| 12:04 Agent ran reconcile baseline . evidence saved                   |
| 11:59 Fleet refreshed . 313 -> 27 unique -> 4 need you                 |
+----------------------------------------------------------------------+
```

- **Left — Triage queue (F006).** Default-filtered to Needs You; `Uncertain` sits WITH it
  (honesty bucket, not buried). Handled buckets show as counts for trust. Counts FILTER the
  left queue — they never open a separate grid. The workbench is the only view.
- **Center — Current work (F008).** The active item, rendered per bucket, with a one-line
  *why now* and the bucket-appropriate actions. Evidence is NOT re-summarized here.
- **Right — Context/evidence (F007).** Tabs (Evidence/Plan/Diff/Tests/History/Why-Hidden);
  for a decision this is what makes the GUI useful — decide without opening files.
- **Top bar (F006).** Compressed status (`Safe . N need you . M handled . K unsure`),
  project selector, Mode toggle, Refresh, Copy Operator Brief, Terminal handoff.
- **Activity strip (F007).** One evidence source rendered as an ambient log; carries the
  `313 -> N unique -> M need you` pipeline line (render-truth made visible).
- **Two modes.** Observer = read-only (copy/inspect, controls hidden). Operator = shows
  approve/request/reject INTENT + safe-tier commands as COPY/OPEN handoff; nothing executes
  from the browser (D018). Operator mode is visually unmistakable.
- **Narrow viewport** collapses to status -> bucket-tabs -> selected item -> evidence
  accordion -> activity; Needs You stays first.

## The four phases -> features
1. **Triage data honesty (model).** F001 derived `operator_bucket` + data-quality envelope;
   F002 dedupe by `dedupe_key`; F003 gate reconciliation against plan status.
2. **Agent-facing operator brief.** F004 `dontpanic operator brief --json|--text` (CLI
   render of the model; model parity asserted separately).
3. **Safe-tier engine (command-line).** F005 `triage apply --safe` over `auto_safe` only —
   dry-run / logged / reversible / refuses creds-approvals-mutations; a command the
   human/agent runs in a terminal.
4. **Operator-console workbench.** F006 left+top (triage queue, status, modes shell);
   F007 right+activity (context/evidence tabs, what-was-handled log, why-hidden);
   F008 center per-bucket COPY/OPEN handoff AFFORDANCES (presentation only, executes nothing);
   F009 handoff LIFECYCLE + refresh (mode switch, mark-run-externally, attach-evidence,
   refresh, your-own-view stale); F010 PARALLEL operation awareness (scope chips, running/
   conflicted state, activity grouped by actor+project, stale/conflict surfacing, journeys P1-P6).

## Parallel operations (concurrency model — D022-D024)
The real workflow is concurrent: GUI on fleet triage, Cursor using DontPanic on one project,
terminal-1 running Claude on a plan, terminal-2 running Codex on a feature, the human resolving
global config in the GUI. So concurrency is a MODEL concern, not a layout one: F001 carries
per-item `scope` (global/project), a derived `run_state` (idle/running/conflicted), a coarse
actor label, and a `state_revision` fingerprint — all DERIVED read-only by joining each item's
`plan_id` to live `SupervisorEntry` records in the existing active-supervisors registry (the
only producer change is an optional `register` enrichment for agent vendor + session). Every
surface (brief/CLI/MCP/GUI) then sees parallelism, not just the GUI. v0 SURFACES running/
conflicted/stale; it does not COORDINATE — item-level claim/lease, conflict resolution, and
refusal-before-mutation are deferred (D023; refusal pairs with 002). Scope is local-machine
multi-process (the described setup); multi-machine needs a shared ledger and is future (D024).

## Constraints / decisions
- `operator_bucket` is DERIVED by one classifier; producers stay dumb (D003).
- `safety_class` stays in the repair projection; the classifier consumes it (D004).
- `uncertain` = render-truth for triage; never silently hidden (D005).
- The GUI is a dual-mode operator console, not an optional glance (D012).
- v0 console affordances are COPY/OPEN/HANDOFF/REFRESH only — the console originates NO
  mutation; it expresses intent and hands off the exact command (D018/D020).
- No `<=N` cap; show ALL unique live human items; the 313->N collapse is a separate fixture
  assertion (D014).
- F005 is a command-line safe-tier engine the human/agent runs in a terminal; F008 only
  HANDS OFF (copies) the command — no browser apply (D015/D018).
- Safe-tier apply stays opt-in, dry-run-first, off by default (D006).
- Naming: `dontpanic operator brief` (D008). Narration must not outrun the data contract (D002).

## Bugs this fixes (surfaced by the prototype — D010)
- `operator_bucket`/`safety_class` absent from the ActionItem envelope -> fail-closed
  human-required mislabel. Fixed by the derived classifier (F001).
- Approval items duplicated 6-8x per gate. Fixed by F002.
- Stale gates from closed/abandoned plans surfaced as live. Fixed by F003.

## Non-goals (v0)
- **Browser-originated governed mutation** (a console button that actually runs
  `dontpanic approve` or `triage apply --confirm` through a local backend) + its threat
  model (local-server auth, CSRF, origin restriction, command allowlist, confirmation
  semantics, evidence atomicity, failure recovery, replay/idempotency, audit-log integrity,
  stale-tab handling) → SEPARATE plan **2026-06-06-002 Governed GUI Action Channel v1** (D018).
- No embedded shell/PTY and no browser-originated execution. v0 affordances are
  copy/open/terminal handoff only.
- Live dispatch to a RUNNING agent (claude/codex/grok) is deferred to the OpenClaw/Hermes
  runtime; v0 `send to agent` = copy-run-plan / open-in-terminal (D017).
- No BLOCK enforcement; v0 surfaces and hands off only (it applies nothing from the console).
- **Item-level claim/lease, conflict RESOLUTION, and multi-machine awareness** are out (D023/D024):
  v0 SURFACES running/conflicted/stale read-only from the local active-supervisors registry; it
  does not reserve items, resolve conflicts, or coordinate across machines.
- Fleet-state serve-path unification (build writes `~/.dontpanic/dashboard/`, serve reads
  `<repo>/dashboard/state/`) is a NAMED dependency of F006, resolved there or deferred (D011).

## Target

```yaml
target_env: dev
target_project: none
```
