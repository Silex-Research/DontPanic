---
id: 2026-05-09-002-fix-verdict-status-environmental-frictions
title: Auditor verdict mismatch, plan-status gate sync, environmental volley short-circuit — phase 2 harness frictions
type: fix
tier: local
status: completed
date: "2026-05-09"
goal_type: infra
surfaces:
  - infra
agents_required:
  - claude
human_gates: []
loop_caps:
  max_iterations: 2
  no_progress_threshold: 1
  wall_clock_hours: 3
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-08-003-fix-harness-volley-frictions
protected_paths:
  - claude/shared/
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
description: |
  Phase 2 of the harness-volley friction fixes. Plan 2026-05-08-003
  closed three frictions (gate-state reconciliation, dispatch-time
  pre_impl auto-clear, auditor verdict taxonomy) but did not address
  three additional defects called out in the original spec and confirmed
  against the SpinDineSwift vibe-mode-ranking-and-parity dispatch audit
  trail. This plan ships those three.

  F001 — Auditor verdict mismatch detection. The audit envelope's
  ``summary`` field can carry a narrative verdict line (``**Verdict:
  signed_off**``) that disagrees with the structured ``audit_status``
  field. The supervisor reads only the structured field today, so a
  signed-off narrative paired with a needs_changes status silently
  produces another iteration. F001 adds a parser + typed
  ``VerdictMismatchError`` so contradictions fail loud, mirroring the
  command_guard / gate_pause discipline.

  F002 — Plan-status → gate-state sync for ``pre_impl``. Phase 1's F002
  (``2026-05-08-003``) auto-clears ``pre_impl`` on direct CLI dispatch.
  That covers operator interactive use but not the case the original
  spec named: an operator (or tooling) flips ``plan.md`` status to
  ``active`` without invoking dispatch. F002 here adds a post-
  reconciliation sync step (NOT a mutation inside the documented-pure
  ``reconcile_gate_state`` helper) that clears ``pre_impl`` when the
  plan's status is exactly ``active`` (the single status that signals
  "lock complete, ready for implementer" — ``ready_for_audit`` /
  ``in_audit`` / ``completed`` are post-implementation states and do
  NOT enable dispatch). The clearance writes a distinct gate event
  actor and INBOX entry so operators can audit which path cleared
  ``pre_impl``.

  F003 — Environmental volley short-circuit. Phase 1's F003 added an
  advisory taxonomy classifier at the no_progress trip site; the
  breaker still fires on env-only auditor rounds, and the volley
  continues running through max_iterations until an implementer round
  the agents demonstrably cannot complete. F003 here moves the
  classifier into the auditor verdict-evaluation path so a single
  ``needs_changes`` auditor round whose findings classify as
  ``environmental_reproduction_failure`` (advisory aggregate, all
  findings env, no defects mixed in) terminates the volley
  immediately with a distinct ``stopped_environmental_blocker`` status
  — BEFORE the next implementer round dispatches. The operator gets
  an INBOX ``environmental_blocker_short_circuit`` event naming the
  cited finding and the recommended action ("run the verification
  locally on a host that has the missing capability"). The volley
  terminal stays non-success — F003 does not auto-sign-off, just
  routes the operator-local verification path explicitly.
motivation: |
  Concrete repro from the spec: SpinDineSwift `2026-05-08-001-feat-vibe
  -mode-ranking-and-parity` F001 dispatch produced 2 paid iterations and
  a `stopped_no_progress` halt, despite codex producing working code.
  Three defects in the audit trail:

  1. `claude-auditor-F001-i1.json` — `summary` carries
     `**Verdict: signed_off**` narrative; `audit_status: needs_changes`
     structured field. Verdict mismatch the supervisor never noticed.
  2. `gate-state.json` + INBOX `gate_hit` event — operator-locked plan
     (status flipped, lock D-entry appended) still paused on `pre_impl`.
  3. `claude-auditor-F001-i1.json` `findings[0]` — `severity: high`,
     `category: test_coverage`, with the auditor itself acknowledging
     "same gradlew invocation refused by Claude Code permis[sions]".
     Both agents lacked the capability; the breaker fired anyway.

  Phase 1 (`2026-05-08-003`) addressed adjacent surfaces but not these
  three. Each is a paid-iteration cause the operator pays for every
  dispatch that hits it.
---

# Auditor verdict mismatch, plan-status gate sync, environmental breaker exclusion

## Thesis

Three independent defects in the harness, each producing wasted paid
iterations on the SpinDine vibe-plan-001 dispatch. None require
agent-conventions schema changes; each builds on a seam the
`2026-05-08-003` plan already established.

## Boundaries

- No agent-conventions schema bump.
- No new supervisor commands or CLI surfaces.
- No pre-flight env-capability check (the spec's optional Option 2 for
  F003 — defer as its own platform-integrity plan; it requires a
  host-capability registry that does not exist yet).
- F002 covers the `pre_impl` lifecycle gate only. Other gates
  (`pre_merge`, `on_escalation`, breaker:*, defer:*) keep their
  existing manual semantics.
- F002 trigger is `plan.status == "active"` exactly; the post-
  implementation states (`ready_for_audit`, `in_audit`, `completed`,
  `abandoned`, `blocked`) do NOT trigger implicit clearance. A
  completed plan should not be re-dispatchable through this seam.
- F002 keeps `gate_pause.reconcile_gate_state` documented-pure: the
  read-only contract added in plan `2026-05-08-003` F001 is invariant.
  The implicit clearance lives in a separate post-reconcile sync
  helper that the supervisor invokes after a successful (non-raising)
  reconciliation.
- F003 short-circuits only on the `environmental_reproduction_failure`
  aggregate (every finding env, none mixed). Mixed, defect-only,
  evidence-shape, scope-overreach, and unknown aggregates all keep the
  existing iterate-until-no_progress-or-cap behavior.

## Acceptance Summary

- F001 raises `VerdictMismatchError` when the auditor envelope's
  narrative `**Verdict: X**` line disagrees with the structured
  `audit_status` field. Tests cover the SpinDine F001-i1 fixture and
  three derived agreement / single-source / structured-only cases.
- F002 lets a plan whose `plan.md` status is `active` (via a direct
  edit + lock D-entry, no separate `dontpanic approve <plan> pre_impl`)
  dispatch cleanly. The implicit clearance happens in a post-
  reconciliation sync step inside the supervisor, NOT inside the
  documented-pure `reconcile_gate_state` helper. INBOX records the
  implicit clearance with a distinct actor.
- F003 short-circuits the volley to a `stopped_environmental_blocker`
  terminal on the FIRST auditor round whose findings classify as
  entirely `environmental_reproduction_failure`, before any further
  implementer round dispatches. Saves the (implementer + auditor)
  pair the volley would otherwise pay for to confirm what the
  classifier already determined. Mixed, defect-only, scope-overreach,
  evidence-shape, and unknown aggregates all keep the existing
  iterate-until-cap behavior.
- All three features ship with EvidenceRef-shaped `evidence_refs[]`.
- Full orchestrate sweep stays at 1529 passed under raw pytest +
  no env-var hygiene (the `2026-05-09-001` baseline).

## Target

```yaml
target_env: dev
target_project: none
```
