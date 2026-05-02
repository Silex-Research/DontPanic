---
id: 2026-05-02-003-feat-nested-orchestration-v1
title: Nested orchestration v1 — safe parent/child plan nesting
type: feat
tier: local
status: active
date: "2026-05-02"
description: |
  Establish the minimum primitives for nested plan orchestration: a parent
  plan's auditor finding (or operator-manual decision) can mint a bounded
  child plan that runs to signoff before the parent resumes. Three
  features, intentionally narrow:
    F001 — parent/child metadata + depth/cycle/repeated-finding guards
    F002 — child charter + commit policy (minimal, enforced at close-out)
    F003 — parent pause/fan-in protocol (pre_resume_after_child gate,
           INBOX, events, parent fan-in memo, no implicit re-entry)
  Out of scope for v1: governance assessment, ADR proposals, standards
  gaps, stage-aware matrices, UX/QA matrix geometry. Those are designed
  in `project_jarvis_nested_orchestration_v1.md` (memory) but deferred
  to a second plan once safe-nesting primitives are exercised.
motivation: |
  Manual cross-harness paste-between-Claude/Codex (the F002 confirmation
  remediation in plan 005 D011 is the canonical example) is the current
  bottleneck for working through the platform plan backlog. The volley
  failure-taxonomy memory documented during plan 005 close-out names the
  exact pain: when a parent volley needs a sub-plan to fix an underlying
  platform issue, today's primitive forces the operator to (a) manually
  capture the parent's audit envelope, (b) draft a separate plan.md by
  hand, (c) shepherd both plans' state across harnesses, (d) re-enter
  the parent context after the child closes. That coordination tax is
  the manual-paste-between-vendors workflow we're trying to eliminate.
  This plan ships the smallest set of primitives that make nesting
  safe — bounded depth, cycle detection, repeated-finding hard stop,
  child charter, parent pause/resume — without yet shipping the
  governance-discovery layer (which is its own scope).
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
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/maintainer/refresh-costs.sh
dependencies:
  - 2026-05-01-005-feat-target-context-platform-fix
  - 2026-05-02-002-fix-audit-envelope-filename
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Nested orchestration v1 — safe parent/child plan nesting

## Anti-recursion thesis

A nested plan is **bounded child work that serves a specific parent
finding or operator objective**. It is NOT a license to spawn arbitrary
feature-ettes. Every spawned child must be tied to a named parent
acceptance item or auditor finding, must declare a return condition,
and must be subject to depth/cycle/repeated-finding guards. The
platform refuses to dispatch a child plan that cannot answer those
questions; it refuses to re-enter a parent without operator approval;
and it hard-stops a chain that re-files the same finding across depth.

Without this discipline, "nested orchestration" becomes the failure
mode it's meant to fix — agents inventing local rules and turning
adversarial findings into recursive scope expansion. The v1 design
scope (this plan) is deliberately narrow: ship the safe-nesting
machinery, dogfood it on a real recursive finding, then in a second
plan add the governance discovery layer (objective_contract,
governance_assessment, standards_gap, ADR proposal). Order matters:
governance bolted onto unsafe nesting compounds the risk.

## Scope

In scope (3 features, deliberately tight):

- **F001 — parent/child metadata + depth/cycle guards.** plan.md
  frontmatter gains an optional `orchestration` block with
  `parent_plan_id`, `parent_audit_id`, `spawn_reason` (`auditor_finding |
  operator_manual`), `spawn_finding_id` (required when reason =
  `auditor_finding`), and `depth_limit` (default 3, operator-override
  via CLI flag). Plan loader validates the chain at dispatch time:
  walks parent_plan_id transitively, computes nesting depth, refuses
  dispatch if depth > depth_limit (without override). Cycle detection:
  refuse if same plan_id appears twice in the chain. Repeated-finding
  hard stop: refuse if a parent plan in the chain already has the same
  `(spawn_finding_code, spawn_finding_class)` pair recorded — prevents
  "fix the same finding via increasingly nested children" infinite
  recursion.

- **F002 — child charter + commit policy (minimal).** plan.md
  frontmatter gains an optional `child_charter` block (only valid when
  `orchestration.parent_plan_id` is set). Required fields: `kind`
  (`implementation` only — governance kind is deferred to v2),
  `parent_objective` (text), `parent_acceptance_item` (text — the
  parent acceptance clause this child unblocks), `allowed_paths`
  (list — child writes are restricted to these), `forbidden_decisions`
  (list — text pointers), `return_condition` (one observable signal),
  `may_edit_product_code` (bool, defaults true for kind=implementation),
  `may_spawn_children` (bool, defaults false — keeps grandchild
  spawning out of scope). Optional `commit_policy` block: `mode`
  (`child_commit | evidence_only` for v1, defer `parent_squash`),
  `requires` (subset of `[patch_completeness, tests_pass,
  evidence_packaged]`). Enforcement is **at close-out / evidence
  packaging time, not pre-impl gating**: signoff_writer checks that
  modified files lie within `allowed_paths`, that `return_condition`
  is recorded as observed in close-out memo, that `requires` items are
  documented as satisfied. No runtime sandboxing of agent file access
  in v1.

- **F003 — parent pause/fan-in protocol.** New gate type
  `pre_resume_after_child` automatically armed on a parent plan whose
  `orchestration.parent_plan_id` is set on a referenced child. Parent
  volley enters this gate when the child plan is detected as in-flight
  (via active-supervisor registry from F023 EC13). INBOX gains a
  `nested_child_pending` entry shape that surfaces the child plan_id +
  resume command. events.jsonl gains two entries: `volley.spawn_child`
  (recorded when child dispatch validates) and `volley.return_to_parent`
  (recorded when child signoff lands). Parent fan-in memo template at
  `evidence/fan-in-from-{child_plan_id}.md` — operator-authored, surfaces
  what changed in the child + how the parent's `return_condition` was
  observed. **No implicit re-entry**: the parent volley does NOT
  auto-resume on child signoff; operator must `jarvis approve
  pre_resume_after_child --child <child_plan_id>` (parity with the
  resume-gate-discipline contract from plan 2026-05-02-001).

Out of scope for v1 (recorded in decisions.jsonl when locked):

- **Governance assessment / objective contract / standards gaps / ADR
  proposals** — the full delivery-governance layer documented in memory
  `project_jarvis_nested_orchestration_v1.md`. These need their own
  plan, slotted after v1 is exercised on a real recursive finding.
- **Stage-aware geometry / matrix / sentinel / tournament patterns**
  — v1 ships `linear_chain` only (parent blocks on child). Sidecar /
  fan-out / matrix are deferred. Single-child-at-a-time is the
  enforced pattern.
- **Implementer self-spawn** — only auditor findings or operator
  manual spawns can mint a child plan in v1. Implementer self-spawn
  is the easiest path to scope creep and is explicitly rejected.
- **Grandchild spawning** — `may_spawn_children` defaults false; the
  nesting tree is depth-2 (parent + child) until v2 lifts this.
- **Runtime file-access sandboxing for child plans** — `allowed_paths`
  enforcement is close-out-time only; the child volley still runs
  with the same permission policy as a top-level plan. Adding runtime
  enforcement is its own platform plan.
- **Cross-plan-tree analytics / dashboard** — observing nested chains
  is operator-driven (read events.jsonl + plan_dirs); no aggregation
  surface in v1.

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance summary

- **F001**: `orchestration` frontmatter block validated at plan load;
  spawn metadata uses structured identity (`parent_audit_id`,
  `finding_id`, `finding_code`, `finding_class`, `finding_signature`);
  `dispatch_volley` / `dispatch_single_agent` refuse to start a child
  plan when (a) depth > limit without `--allow-depth N` CLI override
  (frontmatter can lower the cap but cannot raise it), (b) plan_id
  appears in the parent chain (cycle), or (c) `finding_signature`
  matches a parent's `finding_signature` (repeated-finding hard stop —
  uses the deterministic hash, not just `(code, class)`). Parametrized
  tests cover all three guards + override + signature collision.
- **F002**: `child_charter` parsed from frontmatter; `commit_policy.mode`
  defaults to `evidence_only` (no implicit code-writing authority);
  implementation children require explicit `mode: child_commit` AND
  `may_edit_product_code: true`. signoff_writer cross-checks modified
  files (from git) against `allowed_paths` AND parses a designated
  `## Return Condition` section in close-out memo, asserting
  `status: satisfied|blocked|superseded` (only `satisfied` permits
  parent re-entry via F003) AND the `requires` items appear in the
  signoff. Negative tests cover: child writes outside `allowed_paths`,
  missing `## Return Condition` section, malformed status value, child
  with `mode: child_commit` but `may_edit_product_code: false`.
- **F003**: parent volley with a referenced child enters
  `pre_resume_after_child` gate when `jarvis ps` shows the child
  active; INBOX entry surfaces child plan_id; events.jsonl records
  spawn + return (best-effort, append-only — see decisions D006);
  explicit `approve pre_resume_after_child --child <id>` is required
  to resume AND child's close-out `Return Condition` status must be
  `satisfied` (else approve refuses with status name); bare `resume
  <plan>` does NOT clear this gate (parity with plan 2026-05-02-001
  D004). **Hermetic synthetic e2e test is the acceptance proof**;
  optional real-dogfood trial recorded as evidence if a feasible
  recursive-finding case surfaces during impl, but is NOT a hard
  acceptance criterion (D005).
- All existing orchestrate test modules stay green.
- Audit envelope filenames already include feature_id (plan 002 F001),
  so this plan's tests can dispatch multiple features in a single
  parent dir without colliding.

## Locked decisions (tightenings recorded in decisions.jsonl)

- **D001 — Structured spawn identity, not free-form.** Spawn metadata
  carries `parent_audit_id`, `finding_id`, `finding_code`,
  `finding_class`, AND `finding_signature` (deterministic hash of
  `{finding_code, finding_class, normalized_issue}`). Repeated-finding
  guard compares signatures, not just `(code, class)` pairs — `(EC5,
  correctness)` is too broad to gate on alone.
- **D002 — `--allow-depth N` is CLI-only, never frontmatter.**
  Frontmatter can declare a LOWER `depth_limit` than the default 3,
  but cannot raise it; only the operator can lift the cap at dispatch
  time, and the override is recorded in `validation_performed`. Intent
  is to keep depth expansion as an operator decision, not a per-plan
  default.
- **D003 — `commit_policy.mode` defaults to `evidence_only`.** Code-
  writing authority must be explicit. Implementation children that
  need to commit code declare both `mode: child_commit` AND
  `may_edit_product_code: true`. `evidence_only` children produce
  artifacts under `evidence/` only; signoff_writer enforces the path
  restriction.
- **D004 — `## Return Condition` section is a structured contract,
  not substring match.** Close-out memo must contain a section
  `## Return Condition` with a `status:` line whose value is one of
  `satisfied | blocked | superseded`. Only `satisfied` permits parent
  re-entry via F003's approve. Loose substring matching is rejected
  because it misclassifies "we tried but couldn't" as "done."
- **D005 — F003 acceptance is synthetic; dogfood is optional
  evidence.** The hermetic synthetic e2e test in F003 is the
  acceptance proof. Real-dogfood trial is welcomed as additional
  evidence if a clean recursive-finding case surfaces during
  implementation, but resurrecting plan 005's edge cases is NOT a
  hard requirement and the first implementation must not depend on
  it.
- **D006 — `events.jsonl` is append-only, best-effort trace; not
  canonical state.** Canonical state lives in plan files
  (`plan.md`, `features.json`), `audit/gate-state.json`,
  `audit/<envelope>.json`, and `audit/signoff-*.json`. Events are
  trace/index for human/operator visibility. Event-write failures
  must NOT corrupt orchestration state — `record_event` swallows
  IOError + logs a warning rather than propagating; missing events
  are an evidence-completeness issue, never a correctness issue.
