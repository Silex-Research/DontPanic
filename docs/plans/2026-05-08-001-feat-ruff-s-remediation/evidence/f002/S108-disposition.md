# S108 (hardcoded_tmp_directory) — disposition

**Before**: 0 runtime findings (22 in tests/ — handled via D007 carve-out).
**After**: 0.

No runtime walk needed. The 22 test-side findings were exempted via the
`**/tests/**` per-file-ignore extension (D007). Test fixtures using
hardcoded `/tmp` paths are test-idiomatic; runtime code uses `tempfile`
module helpers and didn't trigger the rule.

**Disposition mix**: 0 fix, 0 noqa, 0 behavioral change. Zero runtime work.
