# F001 operator close-out - 2026-05-20

Plan: `2026-05-20-001-infra-external-integrations-bridge-v0`
Feature: `F001`

## Dispatch terminal

`dontpanic dispatch-from-plan ... --feature F001 --implementer claude --auditor codex --confirm` ran two implementation/audit rounds and terminated `stopped_environmental_blocker`.

The final round had one real actionable finding and one host-reproduction finding:

- `medium/documentation`: the Linear PM-tool wrapper was documented as the canonical `<=100` line per-service wrapper but was 127 lines.
- `advisory/test_coverage`: the Codex auditor could not run pytest in its read-only sandbox because no usable temporary directory was available.

The supervisor classified the aggregate as `environmental_reproduction_failure`, non-blocking, and recommended operator-local verification.

## Operator remediation

The line-count finding was valid. The implementation was narrowed without changing behavior:

- `scripts/dontpanic_orchestrate/integrations/linear_pm_tool.py` is now 98 lines.
- The wrapper still composes `LinearPPAdapter`, `PMToolMappingConfig`, and the PM-tool sync record helpers.
- The service boundary remains unchanged: Linear-specific code stays in `linear_pm_tool.py` / `linear_pp_adapter.py` and not in the generic PM-tool contract modules.

The environmental breaker was cleared with:

```bash
dontpanic approve 2026-05-20-001-infra-external-integrations-bridge-v0 breaker:environmental_blocker
```

`pre_merge` was not cleared manually. `dontpanic approve ... pre_merge` refused because that lifecycle gate was not currently pending.

## Verification

Checks run after the line-count remediation:

```bash
wc -l scripts/dontpanic_orchestrate/integrations/linear_pm_tool.py
ruff check scripts/dontpanic_orchestrate/integrations/linear_pm_tool.py
ruff format --check scripts/dontpanic_orchestrate/integrations/linear_pm_tool.py
PYTHONPATH=scripts pytest -q scripts/dontpanic_orchestrate/tests/test_pm_tool_contract_f001.py
GIT_CONFIG_GLOBAL=/dev/null GIT_AUTHOR_NAME=DontPanic GIT_AUTHOR_EMAIL=dontpanic@example.invalid GIT_COMMITTER_NAME=DontPanic GIT_COMMITTER_EMAIL=dontpanic@example.invalid PYTHONPATH=scripts pytest -q scripts/dontpanic_orchestrate/tests
```

Results:

- `linear_pm_tool.py`: 98 lines.
- Ruff check: all checks passed.
- Ruff format check: already formatted.
- Targeted F001 contract tests: 22 passed.
- Full orchestrator sweep with isolated git identity/config: 2183 passed, 7 skipped, 1 warning.

The first full-sweep attempt without git isolation failed in 15 architecture hook/supervisor tests because temporary `git commit` calls tried to use the operator machine's 1Password signing agent. That was host configuration, not an F001 regression; the isolated rerun passed.

## Acceptance disposition

F001 is accepted as operator-verified after the stopped-environmental-blocker volley because:

- The implementer committed the PM-tool category contract, Linear PP adapter bridge, Linear PM wrapper, mapping example, extension guide, and F001 tests in `e14c01f`.
- The auditor's remaining real finding was remediated locally.
- The local verification covers the changed wrapper and the full orchestrator suite.
- The environmental reproduction issue was resolved by running the tests in this writable operator shell.
