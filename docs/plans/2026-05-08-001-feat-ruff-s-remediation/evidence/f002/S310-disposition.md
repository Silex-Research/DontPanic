# S310 (suspicious_url_open_usage) — disposition

**Before**: 2 runtime findings.
**After**: 0.

| File:line | Disposition | Rationale |
|---|---|---|
| dontpanic_orchestrate/runtime_evidence/backend.py:208 | noqa | operator-supplied URL passed through urllib.Request |
| dontpanic_orchestrate/smoke_test_storage.py:42 | noqa | smoke-test fetch of operator-supplied signed URL |

Note: backend.py already had a S310 noqa at line 210 (urlopen call) but ruff also
fires at line 208 (the Request() constructor). Both lines now carry noqa with rationale.

**Disposition mix**: 2 noqa, 0 fix. No urls are user-controlled in production paths;
backend.py probes operator-defined endpoints and smoke_test_storage exercises a
deliberately-fetched signed URL.
