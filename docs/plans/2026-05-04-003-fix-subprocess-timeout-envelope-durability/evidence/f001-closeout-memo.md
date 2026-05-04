# F001 close-out memo — 2026-05-04

Plan: `2026-05-04-003-fix-subprocess-timeout-envelope-durability`
Feature: F001 — shared subprocess runner.

## Direct-Path Rationale

F001 is a mechanical refactor plus a new helper module. The semantic envelope and supervisor-classifier changes are deliberately left to F002 and F003. Direct execution was locked in D009 so volley budget stays available for F003, where adversarial review has real value.

## What Landed

| Surface | Change |
|---|---|
| `subprocess_runner.py` | New `SubprocessResult` dataclass and `run_subprocess()` helper using `Popen(start_new_session=True)`, process-group SIGTERM → grace → SIGKILL, stdout/stderr byte capture, bounded env-var parsing, and optional git worktree snapshots. |
| `executors/claude_cli.py` | Delegates to `run_subprocess()` instead of `subprocess.run(... timeout=600)`. Decodes stdout bytes for Claude JSON parsing and attaches `subprocess_result` to `DispatchResult`. |
| `executors/codex_cli.py` | Same delegation for Codex NDJSON parsing. |
| `executors/base.py` | Adds internal `DispatchResult.subprocess_result`, explicitly not serialized into audit JSON. |
| Tests | New `test_subprocess_runner.py` plus executor argv tests updated to mock the shared runner rather than `subprocess.run`. |

## Acceptance Coverage

| Area | Evidence |
|---|---|
| Shared runner exists | `scripts/dontpanic_orchestrate/subprocess_runner.py` |
| Process-group kill | `test_timeout_kills_grandchild_process_group` verifies a forked grandchild does not survive timeout. |
| SIGTERM grace then SIGKILL | `test_timeout_sigterm_drains_partial_output` and `test_timeout_escalates_to_sigkill_when_sigterm_ignored` |
| Env-var parsing | `test_parse_timeout_env_matrix` covers valid, absent, unparseable, below-min, above-max. |
| Worktree detection | git clean / git changed / non-git / git failure tests. |
| Captured byte counts | happy path and timeout path assert byte counts. |
| Executor delegation | executor argv tests now mock `run_subprocess`; grep confirms no executor `subprocess.run(... timeout=...)` calls remain. |

## Verification

| Check | Result |
|---|---|
| Baseline before edits | 886 passed, 6 skipped (`test_ec5_classifier.py` excluded) |
| Focused F001 suite | 36 passed, 6 skipped |
| Full orchestrate suite after F001 | 899 passed, 6 skipped |
| Ruff check | All checks passed |
| Ruff format --check | 6 files already formatted |
| Sanitization | 0 findings, 677 files scanned |
| Executor timeout grep | no `subprocess.run(... timeout=` hits under `scripts/dontpanic_orchestrate/executors/` |
| Historical plan-dir durability | no `docs/plans/` diff outside this plan's own directory |

## Remaining Work

F002 consumes `DispatchResult.subprocess_result` and renders timeout evidence into schema-valid audit envelopes. F003 consumes the F002 markers and changes the supervisor classifier so timeout-with-work does not count as zero progress.
