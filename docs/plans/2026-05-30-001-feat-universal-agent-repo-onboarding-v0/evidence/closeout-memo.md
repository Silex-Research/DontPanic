---
status: operator_resolved
reason_class: operator_judgment
plan_id: 2026-05-30-001-feat-universal-agent-repo-onboarding-v0
feature_id: F010
closed_at: 2026-06-02T17:39:38Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 / F010

## Operator decision

F010 (dashboard singleton guard + availability discovery + final docs — the plan's
FINAL feature) is closed `operator_resolved` (class `operator_judgment`). With it,
the plan reaches **16/16**.

The volley ran 3 codex rounds (findings moved 4→3→3, no timeout) and terminated
`stopped_no_progress`. The residual findings were **real defects** (NOT a no-defect
close); the operator finished them and independently verified.

## Operator action (commit e3bb3c2)

1. **(HIGH, security)** `--replace` no longer signals an arbitrary/reused PID.
   `_write_singleton_record` stamps a unique `guard_token`; a new
   `_pid_is_dashboard_process(pid)` POSITIVELY confirms — via `ps -p <pid>
   -o command=` (shell=False, fixed args) matched against a dashboard-serve
   signature (`dashboard`+`serve` or `dontpanic`+`serve`) — that the live PID is a
   dontpanic dashboard BEFORE any SIGTERM/SIGKILL. On any failure (ps missing,
   non-zero exit, timeout, empty) it returns False and the process is never
   signaled. `_supersede_existing_singleton` now gates on it: an alive-but-
   unconfirmed PID is left untouched (record cleared, serve proceeds) — fail safe.
2. **(MEDIUM, correctness)** same-process `replace=True` raises a typed
   `SameProcessReplaceError` instead of silently binding a second in-process
   server; the test asserts the refusal + that the original record is intact.
3. **(LOW, ruff)** the F010-introduced `S101` (assert→raise in `_make_server`) and
   `I001` are cleared; the `ps` subprocess `S607` is suppressed inline per the
   file's existing subprocess convention.

The dashboard availability hint is single-sourced through `dashboard.render_hint_line`
(operations_guidance / config_inventory / skill_recommendation route through it,
per the codex i1 architecture finding). Final docs updated (README / GETTING_STARTED
/ CHANGELOG).

## Return Condition

status: satisfied

F010 returns complete when:

- A serve-singleton record is detected/pruned (`detect_active_dashboard`), a second
  serve refuses or `--replace` supersedes the prior live server, and a guard prevents
  accumulating local servers.
- `--replace` only ever signals a process POSITIVELY confirmed to be a dontpanic
  dashboard (PID-reuse safe); same-process replace fails loudly rather than double-
  binding.
- The dashboard availability hint is implemented once and routed through by every
  consumer surface (CLI/agent guidance).
- Final operator docs (README quickstart / GETTING_STARTED / CHANGELOG) reflect the
  shipped onboarding-v0 surface.
- Tests cover detection/prune, refuse-second-serve, confirmed-vs-foreign supersede,
  same-process refusal, and the guard_token.

## Verification

- 117 pytest pass (`test_dashboard_singleton_f010.py` + `test_dashboard_inventory_f013.py`
  + `test_config_inventory_f008.py`); the F010-introduced ruff S101/I001 are clean
  (5 remaining ruff errors are PRE-EXISTING CLI-path S101/S112, not F010 code).
- Operator independently re-ran the suite and read the security fix: confirmed
  `_supersede_existing_singleton` gates on `_pid_is_dashboard_process` (positive
  `ps` confirmation, fail-safe). Mechanical fix delegated to a subagent; verification
  by the operator.

## Evidence references

- `audit/codex-auditor-F010-i0/i1/i2.json` — verdicts `needs_changes` (findings 4→3→3).
- `audit/signoff-…json` — operator-resolved signoff envelope (`operator_judgment`).
- commit `e3bb3c2` — F010 deliverables (singleton guard + identity verification +
  hint single-sourcing + docs).
- decisions `D064` (this close).
