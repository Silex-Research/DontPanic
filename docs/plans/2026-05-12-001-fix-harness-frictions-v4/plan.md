---
id: 2026-05-12-001-fix-harness-frictions-v4
title: Harness frictions v4 — fixes from plan 004 + plan 010 cross-repo dogfood
type: fix
tier: local
status: draft
date: "2026-05-12"
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
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-11-002-fix-harness-frictions-v3
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
orchestration:
  parent_plan_id: 2026-05-11-001-infra-state-projection-adapters-meta
  spawn_reason: operator_manual
  depth_limit: 3
child_charter:
  kind: implementation
  parent_objective: "Fix four supervisor robustness gaps clustered from the plan 004 + plan 010 + SpinDine cross-repo dogfood so subsequent volleys terminate cleanly and operator can trust the harness on more dispatches."
  parent_acceptance_item: "Parent plan ledger D026 cluster-trigger reached (≥3 supervisor frictions). v4 closes the loop on each: verdict-vs-finding mismatch, lock-time inconsistency check, shlex-safe command handling, supervisor checkpointing."
  allowed_paths:
    - "scripts/dontpanic_orchestrate/**"
    - "scripts/dontpanic_doctor.py"
    - "scripts/jarvis_doctor.py"
    - "docs/plans/2026-05-12-001-fix-harness-frictions-v4/**"
  forbidden_decisions:
    - "Do not modify shipped plan-002/v3 artifacts (gate-state reconciliation, verdict-mismatch detector, env-blocker short-circuit, taxonomy)."
    - "Do not regress any existing test in the current sweep (1873 baseline)."
    - "Do not bypass existing F004 close-out CLI — extend it if needed, never sidestep."
  return_condition_summary: "All 4 v4 features pass; full orchestrate sweep stays green; next docs-heavy dispatch verifies no shlex crash, no orphaned terminal state, and operator-friendly lock-time doctor surface."
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
description: |
  Fourth round of harness frictions, clustered from this week's cross-
  repo dogfood (plan 004 F002, plan 010 F002, SpinDine v2 dispatch).
  v1 shipped gate-state reconciliation + pre_impl auto-clear + verdict
  taxonomy. v2 shipped verdict-mismatch detector + plan-status implicit
  sync + env-blocker short-circuit. v3 shipped doctor quota-cap surface
  + cost-lever amortization + spec_ambiguity class + operator-resolved
  close-out CLI. v4 fixes four robustness gaps surfaced in real volleys:
  (D022) auditor verdict-string trumped finding-class taxonomy; (D024)
  lock-time inconsistencies (allowed_paths vs feature paths, acceptance
  items naming deferred-elsewhere resources) caught by manual review
  but not by doctor; (D025) shlex parse error during auditor invocation
  killed dispatch mid-run with no terminal record; (orphaned state)
  same D025 — implementer envelope persisted but no checkpoint/recovery.
motivation: |
  The v3 work demonstrated the harness CAN catch real volley issues and
  recover cleanly (clean 2-iter convergences on F001+F003, F004 CLI
  dogfood worked first-try). But cross-repo dogfood this week surfaced
  three NEW classes of supervisor failure that v3's fixes don't cover:
    * D022 (plan 010 F002): codex returned `audit_status=blocked`
      because its sandbox couldn't run pytest. Its only finding was
      severity=advisory. Supervisor terminated `blocked after 1 round`
      because the verdict STRING was 'blocked' — not because findings
      warranted termination. F003 ENVIRONMENTAL_BLOCKER short-circuit
      fires on a finding-class, not on the verdict string.
    * D024 (plan 004 pre-lock): two pre-dispatch inconsistencies
      (allowed_paths still axiom/-only after D006 rename; F001 acc #4
      requiring credentials that parent_acceptance_item defers) were
      caught by manual lock-time review. Mid-dispatch discovery would
      have cost ~9M tokens. Worth a doctor preflight check.
    * D025 (plan 004 F002): shlex.split() somewhere in command_guard
      or supervisor post-iter processing hit "No closing quotation"
      after implementer iter0 envelope was written. Killed the volley
      before codex auditor was invoked. NO terminal record. NO
      auditor envelope. Just an orphaned implementer envelope + a
      missing close-out signal. Operator had to verify work locally +
      use F004 CLI to close out manually.
  Three distinct gaps. ≥3 = v4 cluster trigger per parent ledger D026.
---

# Harness Frictions v4

## Thesis

Cross-repo dogfood this week (plan 010 F002, plan 004 F001+F002,
SpinDine v2 dispatch) ran 4 real volleys with cross-vendor claude+codex.
Three terminated cleanly; one (plan 004 F002) terminated badly enough
to require operator hand-recovery via F004 CLI. The bad terminal exposed
two compounding gaps:

1. **shlex fragility** — somewhere in command_guard's post-hoc
   validation pipeline, `shlex.split()` choked on the implementer's
   commands_run text and raised "No closing quotation". The volley
   crashed mid-run with no terminal event, no auditor envelope, no
   recovery hook. The implementer envelope persisted because it landed
   before the crash; everything after is silent.
2. **No checkpointing** — if anything in the supervisor's post-iter
   processing raises, there's no transactional commit to a known state.
   You get exactly what landed before the exception. The operator has to
   reconstruct from the orphaned implementer envelope what should have
   happened.

Plus two non-crash patterns worth fixing while we're in here:

3. **verdict-string vs finding-class mismatch** (D022): the F003
   taxonomy correctly classifies findings, but the supervisor's terminal
   decision uses the auditor's verdict STRING. An advisory-only finding
   set + verdict=blocked = supervisor terminates as blocked. Should be
   a paused/environmental terminal instead.
4. **lock-time doctor gap** (D024): the kinds of plan inconsistencies
   that a quick manual review catches (allowed_paths drift from feature
   paths; acceptance items demanding credentialed resources that the
   plan itself defers) are deterministic. Worth a `dontpanic doctor`
   check on locked plans so future drafts aren't caught mid-dispatch.

## Scope

In scope:

- **F001** (D024): plan-doctor cross-check. Add `validate_plan_cohesion()`
  to `dontpanic_doctor.py`: for each feature with steps, check that file
  paths referenced in step text are reachable from the plan's
  `child_charter.allowed_paths` (when present); flag acceptance criteria
  that reference resources (`<firebase-project-id>`, specific project IDs, real
  service names) when `parent_acceptance_item` says those resources are
  deferred. Lock-time advisory; doesn't block lock, just surfaces deltas
  before the operator hits paid dispatch.
- **F002** (D022): supervisor reconcile verdict-string vs finding-class.
  When auditor returns `audit_status=blocked` AND all findings classify
  as advisory-only (per F003 v3 taxonomy), promote terminal from
  `blocked after 1 round` to `paused_on_environmental` (or treat as
  signed_off-with-environmental-note, matching the F003 ENVIRONMENTAL_-
  BLOCKER short-circuit semantics). Don't trust the verdict string alone
  — trust the findings. Update `circuit_breakers` + `supervisor.py`
  terminal-decision branch.
- **F003** (D025): shlex-safe command-string handling. Audit every
  `shlex.split()` call in `command_guard.py` + `prompts.py` + supervisor.
  Wrap with try/except `ValueError` (which is what shlex raises on
  "No closing quotation"); on failure, emit a structured warning into
  the audit envelope + skip the affected command (don't crash the
  volley). The implementer's prose is untrusted input — never let it
  raise unhandled exceptions in the supervisor.
- **F004** (D025 root cause): supervisor checkpoint after each iter.
  Wrap each iter (implementer + auditor) in a try/except that, on
  failure, writes a `terminal-state.json` artifact recording the
  exception + what stage failed + what evidence persisted. Operator
  can recover by reading that file instead of grepping the (often
  empty due to tee buffering) dispatch log. Pairs with F003: when
  shlex catches the bad command, the iter still produces a clean
  failure record instead of an orphaned implementer envelope.

Out of scope:

- Tee buffering of dispatch logs (operator can copy from the bash
  task output file; not a supervisor-side fix).
- Pre-existing other-plan finding (plan with `target_env: local`
  outside the projection enum — separate cleanup).
- iterN cost reduction (D019 candidate — defer to v5 if it clusters
  with other cost signals).
- Retry-on-shlex-crash. F003+F004 deliver clean failure surfaces;
  automated retry is a separate concern.

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance Summary

- F001: `dontpanic doctor` (with `--include-projects` or its own flag)
  cross-checks each locked plan's `child_charter.allowed_paths` against
  feature step paths + acceptance items vs `parent_acceptance_item`
  deferral language. Surfaces deltas as WARN findings. Fixture tests
  cover both the allowed_paths-vs-step-paths case and the
  acceptance-vs-deferred-resource case. Reproduces both plan-004
  pre-lock issues (D024).
- F002: supervisor's terminal decision reconciles auditor verdict
  string against finding-class taxonomy. When verdict=blocked and all
  findings are advisory-only, terminate as
  `paused_on_environmental` (or signed_off-with-env-note). Fixture
  test replays the plan 010 F002 codex envelope and asserts the new
  terminal classification.
- F003: every `shlex.split()` in command_guard/prompts/supervisor is
  wrapped with try/except. Fixture tests cover at least: unbalanced
  single-quote, unbalanced double-quote, unescaped backslash. On
  shlex failure, the supervisor produces a clean per-command warning
  and continues; volley reaches a real terminal (signed_off /
  needs_changes / blocked) instead of crashing mid-run.
- F004: each iter writes a `terminal-state-iter{N}.json` checkpoint
  artifact. On exception in either implementer or auditor invocation,
  the checkpoint records the exception + the last-good evidence
  paths. Operator can `cat docs/plans/<plan>/audit/terminal-state*.json`
  to recover. Fixture test forces a crash inside the auditor wrapper
  and asserts the checkpoint file shape.
