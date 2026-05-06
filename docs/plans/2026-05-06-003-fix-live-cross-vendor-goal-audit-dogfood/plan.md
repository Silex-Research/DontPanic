---
id: 2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood
title: Live cross-vendor goal-audit dogfood — validation wrapper around Plan G
type: fix
tier: local
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
  - 2026-05-05-003-feat-objective-contract-and-sufficiency-audit
  - 2026-05-06-001-infra-runtime-evidence-harness
  - 2026-05-06-002-feat-post-impl-completion-audit
description: |
  Validation wrapper for the live cross-vendor end-to-end run that was
  deferred at both F1 and F2 dogfood. Plan G is the source corpus; this
  plan is the validation wrapper. Plan G's history is preserved
  unchanged — its plan.md / features.json / decisions.jsonl /
  evidence/ tree are read-only from this plan's perspective.

  **Why this is its own plan, not a `dontpanic plan close` invocation:**
  this validates a platform trust property (real cross-vendor dispatch
  end-to-end against a real `ObjectiveContract`), not just close
  hygiene. If the live run surfaces issues, we need a decision log,
  acceptance criteria, and a clean place to classify fixes without
  rewriting Plan G's historical close-out.

  Single feature, direct path:

  **F001 — Live cross-vendor end-to-end dogfood against Plan G mirror.**

    1. Author retrospective `ObjectiveContract.json` for Plan G with a
       `goal_type` that engages the F2 pipeline (parity / new_feature),
       user_journeys covering G's five adapter sources (web / iOS /
       Android / backend / common harness), `required_evidence`
       matchers that map onto Plan G's actual close-out artifacts.
    2. Build a validation fixture under
       `evidence/g-mirror/synthetic-plan/` — plan.md (status=active,
       gated goal_type), features.json mirroring Plan G's six locked
       features (G0-G5), `evidence/goal-governance/post_impl/`
       populated by **copying** (not symlinking) the relevant evidence
       artifacts from Plan G's close-out tree. The fixture is
       reproducible and self-contained.
    3. Run F001 `run_completion_audit` against the fixture; capture
       `completion_findings.json` to the fixture's post_impl dir.
    4. Run F002 dispatch **LIVE** via the CLI:
       `dontpanic plan audit <fixture-path>` with NO
       `DONTPANIC_GOAL_AUDITOR_OFFLINE` env, NO
       `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR` env. The resolver
       must pick the non-implementer vendor (default: implementer
       claude → auditor codex). Verify the dispatched executor name
       matches the resolved auditor agent name by reading the
       envelope JSON.
    5. Run F003 `dontpanic plan close <fixture-path>` against the
       fixture. Capture decision matrix outcome (pass / block /
       blocking-with-disposition).
    6. Capture all artifacts under `evidence/g-mirror/transcripts/`:
       plan-audit stdout/stderr, plan-close stdout/stderr, audit
       envelope JSON, audit transcript text, completion_findings JSON,
       any override.json if recorded.
    7. Operator disposition: read findings + envelope dispositions;
       classify each finding into one of four buckets (D005):
       (a) real platform issue — file as separate follow-up plan;
       (b) prompt-tuning gap — patch
       `scripts/dontpanic_orchestrate/prompts/completion_audit_prompt.md`
       in scope only if the change conforms to D006's behavioral
       boundary (clarifies already-locked F2 semantics; no schema /
       policy / module changes) AND operator approves AND it gets
       recorded in the close-out memo;
       (c) spec-clarification — record in this plan's
       decisions.jsonl as a doc-only D-entry;
       (d) false-positive — record as a counter-example for the v2
       schema follow-up; no fix.
    8. Author `evidence/g-mirror/disposition.md` with operator-judged
       PASS / FAIL: PASS = real cross-vendor dispatch verified end-to-
       end, no blocking-class-(a) findings unresolved; FAIL =
       identifies the blocker class for follow-up.

  **What this plan IS:**
  - A platform-trust validation that F002's production path actually
    invokes the resolved non-implementer vendor against a real
    `ObjectiveContract`.
  - A decision-log surface for any finding-classification work that
    falls out of the live run.
  - A reusable fixture (the Plan G mirror) that future cross-vendor
    or contract-shape regressions can re-run against.

  **What this plan IS NOT:**
  - Not a re-close of Plan G. Plan G's `status: completed` stays.
    Plan G's plan.md is never mutated by this plan.
  - Not a v2 of Plan F2's auditor pipeline. The only in-scope code
    mutation is clarifying-only edits to the completion-audit prompt
    template, conforming to D006's behavioral boundary (no schema /
    policy / module changes). Anything that crosses the boundary is
    a separate follow-up plan.
  - Not a substitute for the queued real-plan dogfood (F2 D005) — but
    it substantively overlaps and combining the two motions in this
    one plan is the whole point.

  This plan's own close-out path: `goal_type=infra` → exempt from
  the F2 completion gate. F003's exempt-plan flow flips status
  active → completed without invoking the audit pipeline (which is
  correct — the validation IS the deliverable, not a thing to
  cross-vendor audit). Mirror of how F2 itself closed.

motivation: |
  The same caveat appeared in both F1 and F2 dogfood:

  - F1's F005 dogfood ran with `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR=1`
    set because production dispatch wasn't wired (closed by F2/F002).
  - F2's F004 dogfood ran with `DONTPANIC_GOAL_AUDITOR_OFFLINE=1`
    set deliberately because offline mode is the design-mandated
    escape hatch for air-gapped close-outs (per F002 D013).
    Operator second-vendor sanity check on findings JSON served
    as the cross-vendor proxy.

  Offline / self-audit was acceptable for **framework proof**, but
  production trust needs **one real cross-vendor run** end-to-end
  against a real plan's `ObjectiveContract`. F002's production path
  is unit-tested (`test_production_path_invokes_resolved_executor`
  in `test_completion_dispatch.py`) but never exercised end-to-end
  with an actual subprocess invocation against a real prompt + real
  contract.

  Plan G is the natural target. G's own close-out pre-dates F003 and
  was operator-driven (no F003 close gate existed yet). Applying F003
  retroactively against a fixture mirroring G's close-out state
  exercises the entire post-impl pipeline against a real contract
  shape, with both vendors actually invoked.

  This is the highest-leverage queued follow-up because it closes the
  one open trust gap that survived F2's ship. After this plan closes:

  - F002 production path proven end-to-end (not just unit-tested).
  - F002 prompt template proven against a real auditor's actual
    parsing behavior (not just stub responses).
  - F003 decision matrix proven against real-world finding
    distributions (not just synthetic-fixture distributions).
  - Cross-vendor invariant (D003 / Goal Governance V1 §5) proven
    in production posture, not just refusal-time.
---

# Live cross-vendor goal-audit dogfood — validation wrapper around Plan G

The platform-trust validation that closes the offline-mode caveat
carried forward from F1 + F2 dogfood. Plan G is the source corpus.
This plan is the validation wrapper.

Sequence position: queued follow-up after Goal Governance V1 / F2 ✓
(per F2 plan-f2-closeout-memo.md "What's next" §1).

## Feature roadmap

| Feature | Phase | Surface |
|---|---|---|
| F001 | 1 | Live cross-vendor end-to-end dogfood against Plan G mirror — author retrospective contract, build fixture, run live audit + close, classify findings, operator disposition |

Direct path. No phase gating; F001 is the entire deliverable.

## Boundaries

- **D001:** Plan G is the source corpus; do NOT mutate
  `docs/plans/2026-05-06-001-infra-runtime-evidence-harness/`.
  Plan G's plan.md status stays `completed`; its plan dir is read-
  only from this plan. Optional: cite G's close-out commit
  (`0715bc7`) + close-out memo as a back-pointer evidence_ref under
  THIS plan only.
- **D002:** This plan is `goal_type=infra` so it is exempt from the
  F2 completion gate at its own close-out (the validation IS the
  deliverable, not a thing to cross-vendor audit). Mirrors F2's own
  exempt close. The retrospective contract authored INSIDE the
  fixture has a gated `goal_type` (parity / new_feature) so the F2
  pipeline engages on the fixture; this plan's outer goal_type is
  separate.
- **D003:** Live cross-vendor required:
  - NO `DONTPANIC_GOAL_AUDITOR_OFFLINE` env set during the run.
  - NO `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR` env set during the
    run.
  - The fixture's `agents_required` lists `[claude, codex]` so the
    F1 resolver picks the non-implementer vendor by default.
  - Verification step (F001 step 4): read the captured envelope
    JSON; assert `auditor_agent != implementer_agent` AND
    `status != 'dispatch_skipped_offline'`. If either assertion
    fails, the run is INVALID and must be re-run before disposition.
- **D004:** Validation fixture lives entirely under THIS plan's
  `evidence/g-mirror/` tree (synthetic-plan/ + transcripts/ +
  disposition.md + completion_findings + audit envelopes + any
  override). Plan G's evidence files are COPIED (not symlinked) into
  the fixture so it is reproducible without depending on Plan G's
  on-disk state. Mirrors F004 dogfood layout under F2's
  `evidence/dogfood/`.
- **D005:** Finding-classification taxonomy (4 buckets). Every
  blocking finding surfaced by the live run must be classified into
  exactly one of:
  - **(a) Real platform issue** — defect in F001 / F002 / F003 logic
    or in a runtime adapter. File as separate follow-up plan; do
    NOT fix in scope.
  - **(b) Prompt-tuning gap** — auditor template wording surfaces a
    consistent misinterpretation. Patch
    `scripts/dontpanic_orchestrate/prompts/completion_audit_prompt.md`
    in scope ONLY IF the change conforms to D006's behavioral
    boundary (clarifies already-locked F2 semantics; no schema /
    policy / module changes) AND operator approves AND it gets
    recorded in the close-out memo. Anything that crosses the
    behavioral boundary → separate follow-up.
  - **(c) Spec-clarification** — finding is technically correct but
    surfaces ambiguity in the contract spec or operator workflow.
    Record as a doc-only D-entry in this plan's decisions.jsonl;
    no code change.
  - **(d) False-positive** — finding is wrong. Record as a counter-
    example feeding the v2 completion-test schema follow-up (F2
    D011's release valve). No fix in this plan.
- **D006:** In-scope prompt changes are limited to **clarifying** the
  completion-audit prompt so it better follows already-locked F2
  semantics. They must NOT change schema, add new gap classes, alter
  same-vendor / offline policy, change override behavior, or modify
  F001 / F002 / F003 module code. Any prompt change requires explicit
  operator approval and must be recorded in the close-out memo. If
  the live run reveals a need for code changes or semantic policy
  changes, F001 stays unresolved and a follow-up plan is opened.
  (Pre-lock amendment: original draft used a ~30-line cap on diffs;
  reframed as a behavioral boundary because line-count is bad
  governance — a 12-line change can be conceptually risky and a
  50-line change can be purely clarifying.)
- **D007:** No changes to F001 / F002 / F003 module code, no changes
  to runtime_evidence/ adapters, no changes to F1 surface. Only
  permissible code mutation in this plan: prompt template clarifications
  conforming to D006's behavioral boundary. Worktree-boundary
  verification at commit time.

## Acceptance bar

This plan's F001 acceptance:

1. Retrospective `ObjectiveContract.json` for Plan G validates
   against agent-conventions v1.4.0 schema; declares a `goal_type`
   in the F2-gated set; user_journeys cover G's 5 adapter sources;
   `required_evidence` matchers map onto G's actual close-out
   artifact filenames.
2. Validation fixture under `evidence/g-mirror/synthetic-plan/` is
   complete: plan.md (status=active, gated goal_type) + features.json
   (≥1 feature, passes:true) + objective_contract.json + copied
   evidence artifacts under
   `evidence/goal-governance/post_impl/<source>/<journey>/`.
3. Live audit run completed: captured envelope JSON shows
   `auditor_agent=codex` (or whichever non-implementer vendor
   resolved), `status ∈ {agree, disagree, dispatch_response_malformed}`
   — explicitly NOT `dispatch_skipped_offline`.
4. Captured artifacts under `evidence/g-mirror/`:
   `synthetic-plan/evidence/goal-governance/post_impl/completion_findings.json`,
   `audit/audit-<auditor>-<iter>.{json,transcript.txt}`,
   `transcripts/{plan-audit,plan-close}.{stdout,stderr}`.
5. F003 plan-close decision recorded: pass (status flipped) OR
   block-with-classification (override.json + decision summary).
6. Every blocking finding classified into D005 taxonomy (a/b/c/d) in
   `disposition.md`.
7. Operator-judged PASS in `disposition.md`: real cross-vendor
   dispatch verified end-to-end + no unresolved class-(a) findings
   AND any in-scope class-(b) prompt change conforms to D006's
   behavioral boundary (clarification only, no semantic changes) +
   explicitly approved + recorded in the close-out memo.
8. Cumulative orchestrate suite still green; if a prompt-template
   diff landed, the F002 greppable-framing tests still pass.
9. ruff + sanitization clean.
10. Worktree boundary preserved: zero diffs to Plan G's plan dir,
    zero diffs to F001/F002/F003 module code (unless D006-approved
    prompt patch), zero diffs to runtime_evidence/ or F1 surface.
    Only additions under this plan's `evidence/g-mirror/` tree +
    decisions.jsonl + plan-level close-out memo.
11. D-entry per finding-classification surfaced (one D-entry per
    classified finding, OR one combined D-entry summarizing N
    findings if all fall in the same bucket); plus the operator
    PASS/FAIL D-entry at close-out.
