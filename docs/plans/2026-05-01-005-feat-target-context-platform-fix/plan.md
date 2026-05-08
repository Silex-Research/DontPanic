---
id: 2026-05-01-005-feat-target-context-platform-fix
title: Target-context platform fix — EC5 as a formatting/signaling concern, not agent-behavior retraining
type: feat
tier: local
status: completed
date: "2026-05-01"
description: |
  Fix EC5 (target-context prelude requirement) at the platform layer. Today
  the implementer/auditor envelope carries a fully-populated structured
  `target_context: {env, project, commands_run}` field, but the prose
  `summary` typically omits a human-readable prelude block. The auditor
  files this as a recurring high-severity finding even though the trust-
  bearing data is right there in the same JSON file. This plan reframes
  EC5 as platform-owned: the supervisor / audit_writer normalizes the
  persisted summary by injecting a canonical prose prelude derived from
  the structured `target_context`, and the auditor's prompt + finding
  semantics are updated so missing-prose-with-valid-struct is downgraded
  to format-only (i0). Missing or invalid structured context — and
  commands-ran-without-target-metadata — still block.
motivation: |
  Surfaced 2026-05-01 by operator review of repeated audit volleys on
  recent plans (changelog-skill 2026-04-29-001 i0 + i1, security-baseline
  F001/F002 i0, onboarding-ux F002 i0) — every one carries an EC5 finding
  about a missing prose target-context header even when the structured
  field is correctly populated and validated. The auditor cannot tell
  from prompt context alone whether to treat this as a real signal or a
  format gripe; it consistently treats it as i1, which (a) inflates
  finding counts misleadingly, (b) trains the wrong attention onto a
  cosmetic issue, and (c) drowns out actual i1s. The fix is two-sided:
  (1) make sure every persisted summary actually has the prelude (write-
  side normalization), and (2) update the auditor's evaluation rule so
  missing-prelude-with-valid-struct ≠ blocking finding (read-side
  semantics). Neither side is agent retraining — both live in code +
  templates the platform owns.
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
surfaces:
  - infra
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/maintainer/refresh-costs.sh
dependencies:
  - 2026-04-19-001-infra-cross-agent-orchestration
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Target-context platform fix

## Thesis

EC5 is a platform formatting concern, not an agent-behavior problem. The
structured `target_context` field already carries the trust-bearing data;
the prose prelude is a derived rendering of that data. Asking agents to
hand-author the prelude on every summary is brittle and trains attention
onto cosmetics. Generating it at write-time and downgrading the
auditor's severity rule for prose-missing-but-struct-valid closes the
loop without any agent retraining, while keeping the safety contract
intact for real failure shapes (struct missing, struct invalid, or
commands ran without target metadata).

## Scope

In scope (3 features):

- **F001 normalization spec + regression fixtures.** Define the
  canonical prose prelude shape (markdown block format, field order,
  required vs derived fields). Capture the historical EC5 failure
  shapes as test fixtures: (a) implementer summary missing prelude with
  valid struct, (b) auditor self-finding (auditor's own summary missing
  prelude), (c) golden — valid struct + valid prelude, (d) struct
  absent → must block, (e) struct invalid (missing required key) → must
  block, (f) commands_run non-empty but env/project absent → must block.
  Pure design + fixtures; no behavior change.

- **F002 supervisor / audit_writer normalization.** Implement the
  prelude injector. When `audit_writer` finalizes an envelope: if the
  structured `target_context` validates and the persisted summary
  lacks the canonical prelude, prepend the rendered prelude to the
  summary string. If `target_context` fails validation (missing key,
  empty env when commands ran, etc.), audit_writer raises a
  validation error — the envelope does NOT land, so the implementer
  is forced to fix the structured side rather than slip past on a
  rendered prelude.

- **F003 auditor prompt + finding-severity update.** Update the
  auditor prompt template + finding-severity helper so EC5 missing-
  prelude-with-valid-struct is filed as `severity: i0` (format /
  observation, not blocking). Missing struct, invalid struct, or
  commands-without-target stay at `i1` (blocking). The change lives
  in the prompt template + a `classify_ec5(envelope) -> severity`
  helper consumed when scoring findings; no agent retraining.

Out of scope (recorded in decisions.jsonl):

- **Patch-completeness gate** — its own plan
  (`feat-patch-completeness-gate`).
- **Delivery-profile classifier** — future plan.
- **Verifier-environment declaration** (`required_environment` /
  `verifier_capabilities` / `fallback_verification` / `waiver_reason`)
  — future plan.
- **Role-specific volleys** (security_audit, qa_verification, etc.)
  — future plan.
- **Schema bump for target_context** — the existing schema already
  carries the structured field; this plan does NOT add new schema
  fields. If the canonical prelude shape needs schema-level
  recognition later (e.g. a `summary_format_version` discriminator),
  that's a separate conventions-bump plan (D006).
- **Backfilling existing audit envelopes** — historical envelopes
  stay as-is. Forward-only normalization. (D007)

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance summary

- **F001:** canonical prelude shape defined as a constant in code +
  documented; six regression fixtures named (3 valid-with-variants,
  3 must-block) land under `evidence/f001/fixtures/`; fixture loader
  helper imports cleanly.
- **F002:** `audit_writer` injects prelude when struct valid + prose
  missing; raises `TargetContextError` when struct invalid; envelope
  does NOT land in invalid-struct case; tests cover all six F001
  fixtures with correct outcome.
- **F003:** auditor finding-severity helper classifies the six fixtures
  to the right severity (3 → i0/format, 3 → i1/blocker); auditor
  prompt template updated to surface the rule; integration test
  shows a fresh volley against the changelog-skill regression
  envelope produces no spurious EC5 i1.
- All existing orchestrate test modules stay green.
- No CLI behavior changes for plans whose envelopes already carry
  valid struct + prelude (the gate is invisible in the happy path).
