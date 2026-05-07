---
id: 2026-05-07-002-fix-cross-vendor-dogfood-fixture-runtime-artifacts
title: Live cross-vendor dogfood — fair fixture + parser-corrected re-run
type: fix
tier: local
status: draft
date: "2026-05-07"
goal_type: infra
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
dependencies:
  - 2026-05-06-001-feat-goal-governance
  - 2026-05-06-002-feat-post-impl-completion-audit
  - 2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood
  - 2026-05-07-001-fix-completion-dispatch-codex-stream-parser
description: |
  Bounded follow-up to Plan 003 (live cross-vendor dogfood) and Plan
  2026-05-07-001 (parser fix). The parser fix at commit `080b907` taught
  F002 to recognize codex's JSONL streaming protocol; this plan
  exercises the now-clean end-to-end loop against an enriched Plan G
  mirror fixture.

  Single feature, direct path:

  **F001 — Enrich the Plan G mirror fixture per D001 (fair source
  coverage + runtime-like artifacts), perform exactly ONE live codex
  invocation per D002, parse the envelope (parser fix should produce
  `agree`/`disagree`, NOT `dispatch_response_malformed`), classify
  codex findings through the existing 4-bucket taxonomy from Plan 003
  D005, and exercise the close/override path on real parsed
  findings.**

  ## What this plan validates

  Plan 003's narrow validation property — "F002's production path
  actually invokes the resolved non-implementer vendor" — was met,
  but the dogfood couldn't fully exercise the close/override decision
  branches because every envelope landed at `dispatch_response_malformed`.
  Plan 2026-05-07-001 fixed the parser. This plan proves the chain
  end-to-end:

  1. Live cross-vendor dispatch is invoked (codex runs).
  2. Parser produces a structured envelope (`status='agree'` or
     `'disagree'`).
  3. Findings are classified through the 4-bucket taxonomy.
  4. Close path is exercised — without override (if agree) OR with
     override citing classified follow-ups (if disagree).

  ## Why this plan can be smaller than Plan 003

  Plan 003 had to:
  - validate that production-path dispatch actually invokes the
    resolved vendor (not the test seam);
  - verify the cross-vendor invariant (D003) holds at the envelope;
  - exercise the override path on a malformed envelope (forced).

  All three are now proven. This plan only:
  - rebuilds the fixture so codex sees a fair representation of the
    Plan G surface;
  - runs the corrected pipeline once;
  - records what codex says about a fair fixture and what to do about
    it.

  ## Scope (narrow, per operator-locked D001 + D002)

  In-scope:
  - Enrich the Plan G mirror fixture per D001 (this plan's
    operator-locked enrichment boundary):
    - all relevant adapter / source modules
      (`web.py`, `ios.py`, `android.py`, `backend.py`, `harness.py`)
      plus minimal config modules needed to interpret them;
    - runtime-like artifacts per source (web
      screenshot/DOM/console/network sample; iOS
      screenshot/log/crash-or-no-crash sample; Android
      screenshot/logcat/tombstone-or-no-tombstone sample; backend
      log/JSONL sample);
    - Plan G plan dir stays read-only — copy artifacts into THIS
      plan's evidence fixture.
  - Single live codex invocation per D002.
  - Parse the envelope with the parser fix from `080b907` in place.
  - Classify each finding_disposition through Plan 003 D005's
    4-bucket taxonomy: (a) real platform issue / (b) prompt-tuning
    gap / (c) spec-clarification / (d) false-positive.
  - Exercise the close path appropriate to the classified outcome.

  Out-of-scope (queued as separate follow-ups; cross the boundary →
  abort and queue):
  - Matcher tuning. The fixture's `objective_contract.json`
    `required_evidence` list stays identical to Plan 003's. Only the
    captured artifacts are enriched. (Operator: "Do not tune
    matchers to force pass.")
  - F2 module patches. If the parsed run reveals a real platform
    issue, the default response is a queued follow-up, NOT an
    in-plan F2 patch. Tiny patches require explicit operator
    approval. (Operator: "Do not patch F2 unless the parsed run
    reveals a truly blocking issue, and even then default to
    follow-up unless it is tiny and explicitly approved.")
  - Prompt template changes. (Carry-forward from D006 of parent
    parser plan; same rationale.)
  - Plan G plan dir edits. Plan G is the source corpus, read-only.
  - Additional live codex invocations beyond the budgeted one
    (D002). Operator approval required for any second run.
  - Reactive scope-creep into "more sources" or "more artifacts"
    beyond D001's three categories. The enrichment boundary is the
    contract.

  ## What this plan IS NOT

  - Not a fixture rebuild from scratch. Builds on Plan 003's existing
    `evidence/g-mirror/synthetic-plan/` mirror with additive
    enrichment.
  - Not a Plan G v2 design. Plan G's contract semantics are frozen.
  - Not a completion-audit prompt rewrite. Default is parser-only
    (D006 carry-forward).
  - Not a "make it pass" plan. Acceptance is "real run + classified
    findings + close/override exercised," NOT "clean PASS." A
    `disagree` envelope with classified follow-ups is a successful
    outcome.

motivation: |
  Plan 003 closed with three queued follow-ups recorded in its
  close-out memo. Plan 2026-05-07-001 cleared the first (parser fix).
  The remaining two are both addressed here: fixture-fairness +
  parser-corrected re-run.

  After this plan closes, the Goal Governance V1 cross-vendor
  end-to-end story is fully demonstrated against a real plan
  surface (Plan G's mirror) with no synthetic short-circuits in the
  loop. Future cross-vendor runs against any real plan inherit the
  same clean envelope shape.

  Why now (vs. deferring): the parent dogfood revealed a real defect
  (parser format mismatch). That defect is now fixed. Deferring the
  re-run leaves the parser fix unverified at the integration
  boundary that motivated it. One bounded run closes the loop at low
  cost.

  Why bounded vs. open-ended: an unbounded "rerun until clean" plan
  would invite matcher tuning and defect-chasing. The operator-
  locked D001/D002 boundaries forbid that. Acceptance is the
  decision being recorded honestly, not a particular envelope
  status.
---

# Live cross-vendor dogfood — fair fixture + parser-corrected re-run

Single-feature plan. Re-runs the live cross-vendor goal-audit
dispatcher against an enriched Plan G mirror fixture, with the
parser fix from commit `080b907` in place. Records what codex says
about a fair fixture and how the close/override path resolves it.

Sequence position: queued follow-up after parser plan
`2026-05-07-001-fix-completion-dispatch-codex-stream-parser` ✓
(closed at `916b4b6`); itself a follow-up to Plan 003
(closed at `616ad94`).

## Feature roadmap

| Feature | Phase | Surface |
|---|---|---|
| F001 | 1 | Enrich fixture (D001) → single live codex run (D002) → parse envelope → classify findings (4-bucket) → exercise close/override path |

Direct path. Single feature.

## Boundaries (lock-time)

- **D001 — Fixture enrichment boundary (operator-locked).**
  Enrich the Plan 003 mirror fixture ONLY to address the three
  fairness gaps surfaced in the parent dogfood:
  - **Adapter / source modules** — include all relevant adapter
    sources: `web.py`, `ios.py`, `android.py`, `backend.py`,
    `harness.py`, plus any minimal config / shared modules required
    to interpret them (e.g. base classes that the adapters extend).
    The bar is "fair representation of the Plan G surface as a
    cross-vendor auditor would expect to see it," not "ship every
    file from runtime_evidence/".
  - **Runtime-like artifacts per source** — for each adapter, at
    least one runtime-like artifact: web (screenshot + DOM dump +
    console log + network sample); iOS (screenshot + log slice +
    crash-or-no-crash marker); Android (screenshot + logcat slice +
    tombstone-or-no-tombstone marker); backend (log.jsonl request
    sample). "Synthetic but plausibly-shaped" is acceptable;
    operator pre-approves stub-quality artifacts since the fixture
    is for the auditor's pattern-matching, not real session
    capture.
  - **Plan G read-only invariant** — Plan G's plan dir
    (`docs/plans/2026-05-06-001-feat-goal-governance/`) stays
    untouched. Artifacts are COPIED into this plan's evidence
    fixture under
    `docs/plans/2026-05-07-002-…/evidence/g-mirror/`, never moved
    or symlinked. Plan G's history remains a frozen source corpus.

- **D002 — Cost discipline (operator-locked).**
  Exactly ONE live codex invocation is budgeted in this plan. Any
  second invocation requires explicit operator approval before the
  call is made. (Plan 003's three-codex-call regret is the
  cited precedent — D009 of that plan recorded the redundant Step 1
  invocation as an implementer-side mistake costing ~$1.)

  **Acceptance is "parsed live envelope + classified findings +
  close/override path exercised," NOT "clean PASS."** A `disagree`
  envelope with classified follow-ups is a SUCCESSFUL outcome of
  this plan. Status flip happens regardless of whether codex
  agreed; the plan's value is the recorded honest decision, not a
  particular verdict.

  Three release valves are forbidden by default:
  - Matcher tuning to force a pass.
  - F2 module patches in this plan; default response to a real
    platform issue is a queued follow-up plan. Tiny patches require
    explicit operator approval before being made.
  - Prompt template tuning; default is parser-only (carry-forward
    from parser plan D006).

- **D003 — Cross-vendor invariant preserved (carry-forward from
  Goal Governance V1 §5 / Plan 003 D003).**
  Same-vendor refusal stays default. NO `DONTPANIC_GOAL_AUDITOR_
  ALLOW_SAME_VENDOR=1` is set in this plan. The auditor must be
  codex (different vendor than implementer=claude) by F1 resolver
  default. Verified at envelope level: `envelope.auditor_agent ==
  'codex'` AND `envelope.implementer_agent == 'claude'`.

- **D004 — Worktree boundary.**
  Permitted writes:
  - Anywhere under
    `docs/plans/2026-05-07-002-fix-cross-vendor-dogfood-fixture-runtime-artifacts/`
    (this plan dir, including `evidence/g-mirror/` fixture tree).

  Forbidden writes:
  - `scripts/dontpanic_orchestrate/` and ALL submodules — no
    F2 module changes (`completion_dispatch.py`, `completion_auditor.py`,
    `completion_gate.py`, `cli.py`, `supervisor.py`, etc.); no F1
    surface changes; no `runtime_evidence/` adapter changes; no
    test code changes; no fixture-file additions under
    `tests/fixtures/` (parser plan's territory).
  - `scripts/dontpanic_orchestrate/prompts/completion_audit_prompt.md`
    — prompt template untouched; release valve requires
    operator-approved D-entry (carry-forward from parser plan D006).
  - `claude/shared/` — agent-conventions subtree.
  - All other plan dirs (Plan G, Plan F2, Plan 003, Plan
    2026-05-07-001 parser fix). Read-only.

  Verified at commit time via
  `git diff --name-only HEAD` confined to this plan dir.

- **D005 — Finding-classification taxonomy.**
  Each codex `finding_disposition` is classified through the
  4-bucket taxonomy locked in Plan 003 D005:
  - **(a) real platform issue** — codex's disposition flags a
    genuine F2 / parser / dispatcher / auditor defect. Default
    response: queued follow-up plan. In-plan patch ONLY if tiny
    AND operator-approved (D002 release valve).
  - **(b) prompt-tuning gap** — codex's disposition reflects a
    real ambiguity in the auditor prompt that a parser-only fix
    cannot address. Default: queued follow-up plan; in-plan prompt
    edit forbidden by D002.
  - **(c) spec-clarification** — codex's disposition is correct
    given current spec but reflects a vocabulary / matcher
    convention drift, not a defect. Record + dismiss.
  - **(d) false-positive** — codex's disposition is incorrect.
    Record + dismiss.

  Per-finding decision recorded in this plan's decisions.jsonl
  with explicit (a)/(b)/(c)/(d) tag.

- **D006 — Plan G is the source corpus (carry-forward from Plan
  003 D001).**
  Plan G's plan dir is read-only. Artifacts are COPIED, never
  moved or symlinked, into this plan's evidence fixture.

- **D007 — Close-path discipline.**
  Plan close goes through one of three honest paths based on the
  parsed envelope:
  - **Envelope `status='agree'`** → close without override.
    Suspicious if first run; investigate carefully before
    accepting. Possible if v1 correctly captured the gap and
    codex agreed.
  - **Envelope `status='disagree'`, all findings classified (c)/(d)**
    → close with override, citing the classified findings as
    the reason text in the override.json. All four D004 hashes
    (features + objective_contract + completion_findings +
    evidence_manifest) recorded.
  - **Envelope `status='disagree'`, any finding classified (a)/(b)**
    → close with override, citing the queued follow-up plan(s)
    in the override reason. The override is the deliberate
    operator choice, NOT a workaround; the follow-up captures
    the real work.
  - **Envelope `status='dispatch_response_malformed'`** → STOP
    and escalate. This would mean the parser plan didn't fully
    solve the format gap; do NOT close with override; surface
    a new D-entry, no plan flip. (D007 escape clause; expected
    not to fire after parser plan.)

  Override usage is exercised, not avoided. The point of this
  plan is to drive a real envelope to a real close.

## Acceptance bar

This plan's F001 acceptance:

1. **Fixture enrichment is bounded by D001.** Diff under
   `docs/plans/2026-05-07-002-…/evidence/g-mirror/` confined to
   the three categories: source modules, runtime-like artifacts,
   read-only Plan G provenance. NO additions outside those
   categories.
2. **NO matcher tuning.** The fixture's `objective_contract.json`
   `required_evidence` list is byte-identical to Plan 003's
   mirror. Only captured artifacts are enriched. (Asserted by
   diff against Plan 003 fixture.)
3. **Exactly ONE live codex invocation** is performed (D002),
   recorded by transcript filename + token-cost numbers in the
   close-out memo.
4. **Parser fix verified at envelope level.** `envelope.status`
   ∈ {`agree`, `disagree`}. NOT `dispatch_response_malformed`. If
   it IS malformed, D007 escape clause fires and plan does NOT
   close.
5. **Cross-vendor invariant verified at envelope level (D003).**
   `envelope.auditor_agent == 'codex'` AND
   `envelope.implementer_agent == 'claude'` AND no
   `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR` set.
6. **Each codex `findings_dispositions` entry classified through
   the 4-bucket taxonomy (D005).** Per-finding decision recorded
   with (a)/(b)/(c)/(d) tag in this plan's decisions.jsonl.
7. **Close path exercised end-to-end (D007).** Operator-judged
   path (without override / with override + reason / escalate)
   recorded in close-out memo. Override.json (if used) carries
   all four D004 input-bound hashes.
8. **Worktree boundary preserved (D004).** Diff confined to this
   plan dir. Zero diffs to F1 / F2 module code, runtime_evidence/
   adapters, executors/, cli.py, supervisor.py, agent-conventions
   schemas, prompt template, parent plan dirs, tests/, or
   `tests/fixtures/`.
9. **NO module / test / fixture / prompt edits.** Parser plan's
   territory is closed. F2 patches only via operator-approved
   tiny-fix release valve (D002).
10. **Cumulative orchestrate suite stays green** (no module
    changes → no regression risk; smoke-checked anyway). Same
    1357-passed baseline as parser plan close.
11. **Plan-level close via exempt-plan flow** (`goal_type=infra`):
    `dontpanic plan close` exits 0; supervisor backstop silent.

This plan closes the cross-vendor end-to-end loop. After it
closes, Goal Governance V1's "real cross-vendor adversarial
review" property is demonstrated end-to-end against a real plan
surface, with the close/override decision branches exercised on
real parsed findings — not synthetic envelopes, not malformed
envelopes, not test-seam stubs.
