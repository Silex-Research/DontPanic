# F001 Operator Close-Out

Plan: `2026-05-23-005-feat-dashboard-project-selector-v0`
Feature: `F001`
Status: operator-resolved after `stopped_no_progress`

## Volley Result

`dontpanic dispatch-from-plan 2026-05-23-005-feat-dashboard-project-selector-v0 --feature F001 --confirm`
ran two iterations:

- Iteration 0: implementer signed off; auditor returned `needs_changes` with
  four medium findings.
- Iteration 1: implementer remediated three findings; auditor returned
  `needs_changes` with one remaining medium finding.
- Supervisor stopped with `stopped_no_progress` because the auditor verdict was
  unchanged across two rounds.

## Remaining Finding

The final auditor finding was valid:

`projects_dashboard.build_project_state()` forwarded warnings through the
callback passed to `dashboard.build()` and then appended
`BuildReport.warnings`, double-counting the same dashboard warning in
`build-warnings.json` and fleet `warning_count`.

## Manual Remediation

The operator patched `projects_dashboard.build_project_state()` so the wrapper
forwards `dashboard.build()` warnings to the caller for terminal visibility but
only persists the returned `BuildReport.warnings` once.

A focused regression test was added:

`TestCacheLayout.test_dashboard_build_warnings_are_not_double_counted`

## Verification

Commands run:

```text
PYTHONPATH=scripts python3 -m pytest scripts/dontpanic_orchestrate/tests/test_projects_dashboard_f001.py -q
```

Result: `24 passed in 0.24s`

```text
PYTHONPATH=scripts python3 -m pytest scripts/dontpanic_orchestrate/tests/test_f002_projects_registry.py scripts/dontpanic_orchestrate/tests/test_f003_project_config.py scripts/dontpanic_orchestrate/tests/test_projects_dashboard_f001.py -q
```

Result: `124 passed in 3.52s`

```text
PYTHONPATH=scripts python3 -m pytest scripts/dontpanic_orchestrate/tests/test_dashboard_cli_f003.py -q
```

Result outside sandbox: `21 passed in 11.36s`

```text
PYTHONPATH=scripts python3 -m py_compile scripts/dontpanic_orchestrate/projects_dashboard.py scripts/dontpanic_orchestrate/projects_registry.py scripts/dontpanic_orchestrate/dashboard.py
```

Result: pass

```text
python3 scripts/sanitization_check.py
```

Result: `no campaign IDs or secret shapes in sanitized surface (1849 files scanned)`

## Close-Out Judgment

F001 acceptance is satisfied. The remaining auditor finding was narrow,
manually remediated, and pinned by a regression test. The auditor's test failure
for the dashboard serve suite was environmental in its sandbox; the same suite
passed outside the sandbox where localhost socket binding is permitted.
