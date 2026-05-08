# S607 (start_process_with_partial_path) — disposition

**Before**: 12 runtime findings (28 in tests/ — handled via D007 carve-out, not walked here).
**After**: 0.

| File:line | Disposition | Rationale |
|---|---|---|
| dontpanic_doctor.py:123 | noqa | PATH-relative gcloud invocation per D001 |
| dontpanic_doctor.py:141 | noqa | PATH-relative firebase invocation per D001 |
| dontpanic_doctor.py:202 | noqa | PATH-relative git invocation per D001 |
| dontpanic_orchestrate/git_state.py:118 | noqa | PATH-relative git invocation per D001 |
| dontpanic_orchestrate/git_state.py:134 | noqa | PATH-relative git invocation per D001 |
| dontpanic_orchestrate/nested_orchestration.py:951 | noqa | PATH-relative git invocation per D001 |
| dontpanic_orchestrate/runtime_evidence/android.py:655 | noqa | PATH-relative adb invocation per D001 |
| dontpanic_orchestrate/runtime_evidence/ios.py:456 | noqa | PATH-relative xcrun invocation per D001 |
| dontpanic_orchestrate/subprocess_runner.py:85 | noqa | PATH-relative tool invocation per D001 |
| dontpanic_orchestrate/target_context_prelude.py:115 | noqa | PATH-relative git invocation per D001 |
| quota_check.py:429 | noqa | PATH-relative claude invocation per D001 |
| sanitization_check.py:142 | noqa | PATH-relative git invocation per D001 |

**Disposition mix**: 12 noqa, 0 fix, 0 behavioral change. All sites cite D001 verbatim.
