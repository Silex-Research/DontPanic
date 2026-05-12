"""Plan 2026-05-09-004 — Firebase realtime adapter.

Lives outside `scripts/dontpanic_orchestrate/` per plan D001 adapter
boundary: this adapter CONSUMES the projection contract from plan
2026-05-09-003 (`dontpanic state snapshot --json` envelope) and mirrors
it into Firestore under the single-tenant `projects/{project_id}/...`
shape (D002).

F002 (this file's tree) ships the local-side sync daemon. F003-F005 —
Cloud Functions, Firestore rules, real `jarvis-a6ee1` smoke test — are
operator-deferred per parent_acceptance_item / D007 (credential gate).
"""
