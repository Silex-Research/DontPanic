---
id: 2026-05-02-002-fix-audit-envelope-filename
title: Audit envelope filename includes feature_id (forward-only)
type: fix
tier: local
status: completed
date: "2026-05-02"
description: |
  Include `feature_id` in the audit envelope filename so multiple features
  within a single plan no longer overwrite each other's audit envelopes.
  Current filename pattern (F005a-1) is `{agent}-{role}-i{n}.json`, scoped
  to plan_dir/audit/. When a plan ships multiple features (F001, F002,
  F003 …) and each feature dispatches its own volley, the LATER volley's
  envelopes overwrite the EARLIER feature's at the same path. New pattern:
  `{agent}-{role}-{feature_id}-i{n}.json`. Forward-only — existing files
  at the old pattern remain readable (supervisor consumes audit envelopes
  as explicit `list[Path]` accumulated during dispatch, not via filename
  glob, so old-named files are unaffected by the change).
motivation: |
  Real platform finding from plan 2026-05-01-005-feat-target-context-
  platform-fix's F002 confirmation volley (D013): F002's volley overwrote
  F001's i0+i1 envelopes in working tree. F001 versions survived only
  because they had been committed at `836c71d` before F002's dispatch;
  if F001's volley had not yet committed, its envelopes would have been
  lost. The workaround for plan 005 was a manual copy to
  `evidence/f002/audit-original-volley/` before F002's confirmation
  volley dispatched. That workaround is operator-paperwork that the
  platform should make unnecessary. Including feature_id in the filename
  is the smallest fix: collision-free for any plan-feature pair, no
  schema change, no migration of historical files.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  no_progress_threshold: 2
  wall_clock_hours: 2
  hard_stop: false
privacy_tier: internal
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/maintainer/refresh-costs.sh
dependencies:
  - 2026-05-01-005-feat-target-context-platform-fix
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Audit envelope filename collision fix

## Thesis

The audit envelope filename pattern `{agent}-{role}-i{n}.json` collides
within a plan that ships multiple features. Including `feature_id` in
the filename makes multi-feature plans collision-free without any
schema change, migration, or audit-event-model redesign. Forward-only
— existing envelopes stay valid; readers consume `Path` objects, not
filename globs.

## Scope

In scope (1 feature, deliberately tight):

- **F001 audit envelope filename includes feature_id.** New write-side
  filename pattern: `{agent}-{role}-{feature_id}-i{n}.json`. Single
  callsite change inside `audit_writer.write`; threading `feature_id`
  through from `supervisor.dispatch_volley` (which already knows it).
  Tests prove that running two volleys against the same plan dir with
  different `feature_id` produces non-colliding files, and that an
  envelope persisted under the old pattern remains readable to any
  caller that already holds a `Path` to it.

Out of scope (recorded in decisions.jsonl when locked):

- **Schema changes** to `audit.schema.json` — the new filename component
  is derived from the existing `feature_id` parameter already threaded
  through `build_audit`. No new fields on the audit dict.
- **Backfill of existing envelopes** to the new naming pattern — the
  platform's job is to make NEW envelopes correct, not retroactively
  rename committed evidence. Plan 005's audit/ envelopes stay at their
  current names.
- **Audit event model redesign** — there is no general "audit event" type
  to revisit. The change is to the file-naming convention only.
- **Nested orchestration** — the v1 design (memory:
  `project_jarvis_nested_orchestration_v1.md`) is a separate plan,
  slotted after this fix.
- **Signoff filename change** — the signoff file is named
  `signoff-{plan_id}.json` and is one-per-plan (not per-feature), so it
  does NOT exhibit the same collision pattern. If a future need for a
  per-feature signoff arises, that's a separate plan.
- **gate-state.json / transcript.md / INBOX.md filename changes** —
  those are also one-per-plan (not per-feature), no collision.

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance summary

- F001:
  - `audit_writer.write` produces filenames matching
    `{agent}-{role}-{feature_id}-i{n}.json` where `feature_id` matches
    the existing schema regex `^F\d{3}$` (per
    `agent-conventions/schemas/v1.0/features.schema.json`). Validation
    happens at the writer's entry, BEFORE any disk I/O — invalid input
    raises `ValueError` and no file lands.
  - Both production audit-writing dispatch paths thread `feature_id`:
    `supervisor.dispatch_volley` (line 1342, post-volley persist) AND
    `supervisor.dispatch_single_agent` (line 595, single-shot persist).
    Verified by greppable test that asserts each callsite passes
    `feature_id` and that wrapping each with `feature_id=None` raises.
  - Two synthetic volleys against the same plan dir with `feature_id`
    F001 and F002 produce 4 distinct envelope files (impl-i0 + aud-i0
    per feature) coexisting under `audit/` — no overwrite, no shared
    filename. Verified by parametrized test counting files post-dispatch.
  - Readers that hold a `Path` to an envelope at the old pattern (e.g.
    historical plan 005 envelopes committed under
    `claude-implementer-i0.json`) continue to be readable. Verified by
    a test that copies one such historical envelope into tmp_path and
    invokes the supervisor's read paths (`circuit_breakers.check_*`
    suite, `_findings_block` from prompts.py) on it.
  - **Negative test**: `audit_writer.write(audit, plan_dir)` without a
    `feature_id` kwarg, or with `feature_id=None`, or with a string
    that doesn't match `^F\d{3}$` (e.g. `"F1"`, `"feat-1"`, empty
    string, path traversal `"F001/../escape"`) raises `ValueError`
    BEFORE creating the audit/ directory or writing any bytes.
  - Existing `test_audit_writer_normalize.py` and
    `test_audit_writer_f002_supervisor_integration.py` updates needed:
    any glob/expectation for the old filename pattern under tmp_path
    must accept the new pattern when the audit was written by F001-of-
    this-plan or later.
  - **Payload audit_id identity is unchanged**: the audit dict's
    existing `audit_id` field stays `{plan_id}#{agent}#{iteration}` —
    not extended to include feature_id. Two features within the same
    plan can therefore still produce envelopes with identical payload
    `audit_id` strings; this fix addresses filename collision only,
    not payload identity. Recorded as D001 of this plan: filename
    uniqueness is fixed in F001; payload-identity expansion (e.g.
    embedding feature_id in audit_id) is deferred to a future plan if
    a need surfaces.
  - Plan 005's committed audit envelopes are NOT modified, NOT renamed.
    The originating-context evidence in this plan references plan 005
    via copy-into-`evidence/finding/` (no edits to plan 005 itself).
  - All existing orchestrate test modules stay green; no schema bump,
    no historical envelope rename.
