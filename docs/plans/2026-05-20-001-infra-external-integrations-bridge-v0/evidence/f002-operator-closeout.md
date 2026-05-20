# F002 operator close-out - 2026-05-20

Plan: `2026-05-20-001-infra-external-integrations-bridge-v0`
Feature: `F002`

## Dispatch terminal

`dontpanic dispatch-from-plan ... --feature F002 --implementer claude --auditor codex --confirm` ran two implementation/audit rounds and terminated `stopped_no_progress`.

The final Codex audit had two substantive findings:

- `high/correctness`: `dontpanic plan close` did not actually write `evidence/external_sync.json` for declared refs because `_run_external_refs_at_close` passed `loaded.external_refs`, but `loaded` was undefined in that scope. The broad close-time exception handler meant the hook could crash silently while close still succeeded.
- `medium/test_coverage`: F002 tests covered `external_refs_sync.run_close_push()` directly but missed the CLI integration path where the bug lived.

These were real implementation defects, so the stopped-no-progress terminal was not accepted as-is.

## Operator remediation

The CLI integration bug was fixed in `scripts/dontpanic_orchestrate/cli.py` by passing the parsed `refs` list to `external_refs_sync.run_close_push()`.

The missing coverage was added to `scripts/dontpanic_orchestrate/tests/test_external_refs_sync_f002.py`:

- `test_plan_close_cli_writes_external_sync_evidence`
- `test_plan_close_cli_dry_run_writes_pending_without_vendor_call`
- `test_plan_close_cli_mixed_failure_writes_evidence_and_does_not_block`

These tests exercise the real `dontpanic plan close` CLI path with `completion_gate.close_plan` and `_RESOLVER_FACTORY` monkeypatched, so the broad defensive exception handler can no longer hide a broken external-ref hook.

## Verification

Checks run after remediation:

```bash
PYTHONPATH=scripts pytest -q scripts/dontpanic_orchestrate/tests/test_external_refs_sync_f002.py
ruff check scripts/dontpanic_orchestrate/cli.py scripts/dontpanic_orchestrate/tests/test_external_refs_sync_f002.py scripts/dontpanic_orchestrate/external_refs_sync.py scripts/dontpanic_orchestrate/plan_loader.py
ruff format --check scripts/dontpanic_orchestrate/cli.py scripts/dontpanic_orchestrate/tests/test_external_refs_sync_f002.py scripts/dontpanic_orchestrate/external_refs_sync.py scripts/dontpanic_orchestrate/plan_loader.py
GIT_CONFIG_GLOBAL=/dev/null GIT_AUTHOR_NAME=DontPanic GIT_AUTHOR_EMAIL=dontpanic@example.invalid GIT_COMMITTER_NAME=DontPanic GIT_COMMITTER_EMAIL=dontpanic@example.invalid PYTHONPATH=scripts pytest -q scripts/dontpanic_orchestrate/tests
python3 scripts/sanitization_check.py
```

Results:

- Targeted F002 tests: 22 passed.
- Ruff check: all checks passed.
- Ruff format check: all checked files formatted.
- Full orchestrator sweep with isolated git identity/config: 2205 passed, 7 skipped, 1 warning.
- Sanitization check: clean, 1437 files scanned.

## Acceptance disposition

F002 is accepted as operator-verified after remediation because:

- The schema, loader, lock hook, close hook, dry-run path, resync command, adapter registry, contract doc, and tests landed in `de5b966`.
- The final auditor's high-severity CLI-path finding was fixed before the feature flip.
- CLI-level regression tests now cover close, close `--dry-run`, and mixed failed/skipped evidence.
- Local verification covers both the focused F002 surface and the full orchestrator suite.
