---
status: operator_resolved
reason_class: evidence_shape_disagreement
plan_id: 2026-05-30-001-feat-universal-agent-repo-onboarding-v0
feature_id: F002
closed_at: 2026-05-30T19:41:33Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 / F002

## Operator decision

This feature was closed under class `evidence_shape_disagreement` after operator review of a `stopped_no_progress` terminal. The audit finding is recorded as non-defect; the close-out workflow generated this template, cleared `breaker:no_progress`, wrote the signoff envelope, and flipped `features.json` `passes: true` for this feature.

## Latest auditor envelope summary (lifted automatically)

## Target context
- Repo: DontPanic
- Env: dev
- Project: (none)
- Command: 4 (see structured target_context.commands_run)

[F002] Repo: DontPanic
Env: dev
Project: (none)

Overall verdict: needs_changes.

FINDING (medium, correctness): `dontpanic orchestrate <plan> --bad-flag` does not print the generated brief/canonical workflow for invalid input. Evidence: it falls through to `dispatch-from-plan` argparse and prints only dispatch usage/error, missing `DontPanic operating brief` and `CANONICAL WORKFLOW`. Recommendation: catch/handle invalid forwarded argv in the `orchestrate` gateway and append the teaching output on exit 2, or narrow the spec/tests if this shape is intentionally delegated.

The implementer’s audit summary correctly declares `Repo: DontPanic`, `Env: dev`, and `Project...

## Rationale (operator — fill in)

**Correction to auto-lifted summary above:** the memo lifted the STALE `codex-auditor-F002-i1.json` (needs_changes, 14:02) from the *prior* volley. The actual final verdict was `codex-auditor-F002-i0.json` **signed_off** (14:26) on the re-dispatch with `--max-iterations 5`. The frontmatter `latest_audit_status: needs_changes` is wrong for the same reason — the finalizer/close path picks "latest" by iteration index, and i1 > i0 even though i1 is older wall-clock. This is the audit-filename-reuse hazard (re-dispatch reuses `iN` filenames; a later run with fewer iterations leaves a higher-index stale envelope).

**Why no re-dispatch:** codex signed off the code. The volley terminated `blocked` only on the patch-completeness backstop — the new test `scripts/dontpanic_orchestrate/tests/test_f002_agent_surface_cli.py` was untracked, so fresh-clone pytest discovery would skip it (D025 root-cause #2). Resolved out-of-band: `git add` of the F002 deliverables (`agent_surface.py`, `agent_manifest.py`, `cli.py`, the test) + confirmed 21/21 tests green before close-out.

**Follow-up to file:** (1) finalizer/close "latest auditor envelope" selection should tie-break by mtime, not just iteration index, OR re-dispatch should purge stale higher-index envelopes — file as a DontPanic harness D-entry. (2) The `(latest auditor envelope not located)` evidence-ref line is a second symptom of the same lookup gap.

## Evidence references

- `audit/signoff-2026-05-30-001-feat-universal-agent-repo-onboarding-v0.json`
- `(latest auditor envelope not located)`

