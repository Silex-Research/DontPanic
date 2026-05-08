# S603 (subprocess_without_shell_equals_true) — disposition

**Before**: 5 runtime findings (10 in tests/ — handled via D007 carve-out).
**After**: 0.

| File:line | Disposition | Rationale |
|---|---|---|
| dontpanic_doctor.py:201 | noqa | trusted argv + shell=False default per D001 |
| dontpanic_doctor.py:322 | noqa | trusted argv + shell=False default per D001 |
| dontpanic_orchestrate/notify.py:59 | noqa | trusted argv + shell=False default per D001 |
| dontpanic_orchestrate/subprocess_runner.py:140 | noqa | trusted argv + shell=False default per D001 |
| sanitization_check.py:141 | noqa | trusted argv + shell=False default per D001 |

**Disposition mix**: 5 noqa, 0 fix, 0 behavioral change. All shell=False; argv lists are
trusted (operator config + hardcoded tool names).
