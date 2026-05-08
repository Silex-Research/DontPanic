# S101 (assert in non-test code) — disposition

**Before**: 5 runtime findings (0 in tests/ — the D007 carve-out covers test S101).
**After**: 0.

| File:line | Disposition | Rationale |
|---|---|---|
| dontpanic_orchestrate/cli.py:960 | **fix** | replaced `assert removed is not None` with explicit `if removed is None: raise RuntimeError(...)` — projects-registry race window is real, asserts strip under `python -O` |
| dontpanic_orchestrate/ec5_classifier.py:106 | **fix** | replaced `assert expected is not None` with explicit `raise RuntimeError(...)` — render_prelude/parse_prelude_block round-trip drift would silently return wrong verdict |
| dontpanic_orchestrate/execution_environment.py:85 | **fix** | replaced type-narrowing `assert self.root is not None` with explicit `if self.root is None: raise RuntimeError(...)` — `_require_active()` already guarantees this; explicit narrowing keeps mypy happy without strip-under-O risk |
| dontpanic_orchestrate/smoke_test_storage.py:50 | noqa | smoke-test script abort-fast on storage round-trip mismatch |
| dontpanic_orchestrate/smoke_test_storage.py:51 | noqa | smoke-test script abort-fast on non-200 |

**Disposition mix**: 3 fix, 2 noqa. Per D006: prefer FIX where the invariant
is real and stripping under `python -O` would silently break behavior. Use
noqa only when the assert is genuinely defensive coding documented as such
(smoke_test_storage is a smoke-test script that should abort fast on storage
mismatch — semantically equivalent to a test assertion, just lives outside
`tests/`).

Behavioral changes documented in the per-fix code comments. No tests broke
(full sweep stayed at ≥1443 passed).
