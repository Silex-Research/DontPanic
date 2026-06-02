---
status: signed_off
reason_class: feature_complete
plan_id: 2026-05-30-001-feat-universal-agent-repo-onboarding-v0
feature_id: F015
closed_at: 2026-06-02T15:35:00Z
latest_audit_status: signed_off
---

# Closeout memo — 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 / F015

## Operator decision

F015 (skill auto-run ALLOWLIST artifact + approval gating — split from F011 per
D060) is closed `signed_off` and finalized `passes:true` via the no-paid
finalizer. codex `signed_off` on run1 iter1; the volley terminal was `blocked`
ONLY because the two new test files were untracked (the D025 patch-completeness
backstop) — not a quality issue. The operator staged + committed the deliverables
(`26ed410`), independently verified, then ran `dontpanic finalize` (no paid call).

## Return Condition

status: satisfied

F015 returns complete when:

- The auto-run allowlist is a versioned, auditable artifact: `AllowlistEntry`
  carries exactly one of `command_template`/`command_prefix` plus owner /
  approved_by / approved_at / rationale; the file carries `schema_version`, a
  monotonic `version`, and a `content_hash`. A hand-edit that does not re-stamp
  the hash is detected as STALE/untrusted (AC4/AC5).
- The allowlist is consumed by F011's injected `SkillInvocationContext.
  is_command_allowlisted` predicate: a read-only skill is auto_run-eligible ONLY
  when inputs exist AND its exact command matches an allowlist entry; deny by
  default (AC4).
- doctor/reconcile and the F008 config inventory surface MISSING/STALE/
  conflicting allowlist state (`AllowlistStatus` OK/MISSING/MALFORMED/STALE)
  (AC5).
- Mutating/credentialed/networked/paid/external-write/indefinite-loop skills
  resolve to approval_required or suggest and are never silently executed (AC7).
- Tests prove command-allowlist enforcement (allowed vs absent vs prefix
  mismatch), doctor/reconcile/F008 allowlist visibility, and that
  approval-required skills are never invoked (AC14b).

## Verification

- codex `signed_off` (`audit/codex-auditor-F015-i1.json`).
- `pytest test_skill_allowlist_f015.py test_config_inventory_f008.py` → 125 passed;
  ruff clean on all F015 deliverables.
- Operator independently read `skill_allowlist.py` (AllowlistEntry fields +
  content_hash STALE detection + deny-by-default) and the F011 predicate seam.

## Evidence references

- `audit/codex-auditor-F015-i0.json` / `-i1.json` (i1 = `signed_off`).
- `audit/signoff-…json` — finalize-confirmed signoff envelope (repaired=False).
- commit `26ed410` — F015 deliverables (`skill_allowlist.py`, config_inventory/
  doctor/reconcile/home_reconcile updates, tests).
- decisions `D060` (F011 3-way split), `D062` (this close).
