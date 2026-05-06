---
id: 2026-05-06-999-dogfood-synthetic-completion-audit
title: F2/F004 dogfood — synthetic completion-audit fixture
type: feat
tier: local
status: completed
date: "2026-05-06"
goal_type: parity
agents_required:
  - claude
  - codex
description: |
  Synthetic plan-local fixture for Plan F2 / F004 dogfood. NOT a real
  product surface — exists purely to exercise the F001 + F002 + F003
  pipeline end-to-end against a goal-gated plan with intentionally
  incomplete runtime evidence.

  Coverage by design (per F004 / D015 acceptance bar):

  - 4 of 5 ``required_evidence`` matchers DO have captured artifacts
    under ``evidence/goal-governance/post_impl/<source>/<journey>/``
    so F001 reports them as covered.
  - 1 matcher (``crash-NoneObserved``) is intentionally unmatched →
    F001 emits a ``missing_evidence`` finding.
  - 1 ``user_journey`` (``error_recovery``) has zero captured refs of
    any kind under any source surface → F001 emits a ``journey_gap``
    finding at severity='high'.

  F002 dispatch runs in OFFLINE mode for the dogfood (per F004's
  cross-vendor caveat handling clause): the synthetic
  ``dispatch_skipped_offline`` envelope lets the operator's manual
  cross-vendor sanity check serve as the second-vendor proxy on the
  findings JSON. F003 close path will refuse the close (offline status
  + no override) and then honor a recorded
  ``--ignore-completion-findings`` override.
links:
  objective_contract: ./objective_contract.json
---

# F2/F004 dogfood — synthetic completion-audit fixture

This plan is a fixture under
``docs/plans/2026-05-06-002-feat-post-impl-completion-audit/evidence/dogfood/synthetic-plan/``.
It is consumed by the F004 dogfood run; it is NOT a real product plan
and should never be dispatched against by the supervisor.

The dogfood narrative is captured in the sibling
``../disposition.md`` file. Re-running the dogfood is operator-driven:
delete ``override.json`` (if present) and reset ``status: completed``
back to ``status: active`` in this frontmatter, then re-run
``dontpanic plan close`` against this directory.
