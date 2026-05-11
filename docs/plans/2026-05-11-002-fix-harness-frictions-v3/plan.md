---
id: 2026-05-11-002-fix-harness-frictions-v3
title: Harness frictions v3 — fixes from plan 2026-05-11-001 dogfood
type: fix
tier: local
status: draft
date: "2026-05-11"
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
  - 2026-05-11-001-infra-state-projection-adapters-meta
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
description: |
  Third round of harness frictions fixes. v1 shipped gate-state
  reconciliation + pre_impl auto-clear + verdict taxonomy. v2 shipped
  verdict-mismatch detector + plan-status implicit sync + env-blocker
  short-circuit. v3 fixes four frictions clustered from the dogfood
  in parent plan 2026-05-11-001 (PP skill volley): doctor missing
  cap-entry surface, no_progress taxonomy gap on documentation
  findings, signoff_writer workflow on operator-resolved non-success,
  prompt-template token bloat.
motivation: |
  Parent plan 2026-05-11-001 dispatched plan 010 F001 via real
  supervisor.dispatch_volley (cross-vendor claude+codex). Volley
  terminated stopped_no_progress with the v0 taxonomy classifier
  returning [unknown] aggregate. Four distinct frictions surfaced:
  (D005) quota_caps.json missing entries surfaced as stderr warnings
  not as actionable doctor checks; (D007) implementer consumed
  6.84M input tokens for a 763-line docs feature — prompt template
  is too heavy; (D008) no_progress classifier has no class for
  "documentation finding about file placement" so audit verdicts
  block operator until manual review; (D009) signoff_writer skipped
  on stopped_no_progress because operator close-out memo path is
  not discoverable. ≥3 findings clustered → v3 plan drafted per
  parent F004.
---

# Harness Frictions v3

## Thesis

Real volley dogfood (cross-vendor claude+codex on plan 010 F001) exposed
four orchestrator frictions that the v1+v2 fixes don't cover. The volley
delivered substantively complete work (763 lines of skill files including
real sanitization logic) but terminated `stopped_no_progress` because:

1. The auditor's iteration 1 finding was a documentation placement
   nit (spec-ambiguity), not a defect — but the v0 taxonomy can't
   classify it, so the supervisor blocks pending operator review.
2. Operator review reveals the work is fine; close-out should be
   trivial but the signoff_writer needs a closeout-memo at a path
   no current docs mention.
3. The volley cost 6.84M input tokens for 763 lines of output —
   100:1 input:output ratio suggests prompt-template context bloat.
4. Pre-flight surfaced 3 quota_caps.json gaps as buried stderr
   warnings instead of actionable `doctor` findings.

v3 closes these four loops so the next dogfood run terminates cleanly
on similar features without operator intervention.

## Scope

In scope:

- **F001** (D005): `dontpanic doctor` quota-cap surface. Add a check
  that walks `~/.jarvis/quota_state.json` vendors × windows, cross-
  references `~/.jarvis/quota_caps.json` entries, and emits one
  actionable warning per missing (vendor, window) pair. Bonus: also
  flag stale calibration (>7 days old).
- **F002** (D007): prompt-template trimming for the implementer. Audit
  `scripts/dontpanic_orchestrate/supervisor.py` + `audit_writer.py` for
  what context the implementer prompt loads. Measure baseline (this
  plan's own F001 dispatch as fixture); identify cuttable surfaces;
  trim to 50% (target: <1.5M input tokens for a docs-only feature).
- **F003** (D008): no_progress taxonomy expansion. Add a
  `spec_ambiguity` class to the v0 taxonomy alongside the existing 6
  (feature_defect / regression / interpretive_disagreement / redundant
  / already-known / spec-clarification). The classifier should match
  documentation-category findings about file/path placement, naming,
  or convention adherence to `spec_ambiguity` and emit a non-blocking
  recommended_action: "Operator-review for spec gap before retry".
- **F004** (D009): close-out workflow on stopped_no_progress. The
  signoff_writer should accept an `--operator-resolved` flag that
  generates a minimal closeout-memo template at the expected path
  + closes the feature without requiring a second dispatch. Document
  the path conventions in INBOX events.

Out of scope:

- Re-runs of the plan 010 F001 dispatch (already operator-resolved).
- Changes to the v0 finding-taxonomy classes themselves (just adding
  one new class).
- Token-cost rewrites for the auditor prompt (focus is implementer).
- Refactoring `quota_caps.json` schema (just adding a doctor check).

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance Summary

- F001: `dontpanic doctor` lists missing cap-entry pairs as
  actionable warnings with copy-paste config snippets. Verified
  against current operator state (3 known-missing pairs from
  parent plan dispatch).
- F002: implementer prompt template trimmed; re-dispatch a small
  fixture feature and confirm <1.5M input tokens (baseline 2.48M
  from D007). Regression sweep stays green.
- F003: `spec_ambiguity` class added; no_progress classifier returns
  this class (not `unknown`) for documentation-category findings.
  Fixture tests cover the new pattern.
- F004: `--operator-resolved` flag on signoff_writer; minimal
  closeout-memo template generated; INBOX event documents the
  recommended path. Re-dogfood plan 010 F001 path as smoke (no
  re-dispatch — just exercise the close-out CLI).
