# S104 (hardcoded_bind_all_interfaces) — disposition

**Before**: 1 finding (in tests/ — but S104 is NOT in the D007 carve-out, so the
finding still surfaces under S checks).
**After**: 0.

| File:line | Disposition | Rationale |
|---|---|---|
| dontpanic_orchestrate/tests/test_f002_mcp_server.py:566 | noqa | test asserts mcp_server.py has no 0.0.0.0; the literal here is the assertion needle |

The test exists specifically to verify that the MCP server module never binds
non-loopback (per D003 of plan 2026-05-03-003). The `"0.0.0.0"` literal is
the test's needle — it grep-asserts the module SOURCE does not contain that
string. Ruff fires S104 because the literal string IS present. This is the
exact inverse of the security concern S104 catches; the noqa cites the test's
intent verbatim.

**Disposition mix**: 1 noqa, 0 fix. S104 was deliberately excluded from the
D007 tests/** carve-out because it's a one-off pattern; the noqa here is
per-line and cites the test's purpose.
