# S110 (try_except_pass) — disposition

**Before**: 1 runtime finding.
**After**: 0.

| File:line | Disposition | Rationale |
|---|---|---|
| dontpanic_orchestrate/patch_completeness_gate.py:268 | noqa | INBOX write is documented best-effort; pragma:no cover above |

The site is the F003 gate's INBOX-event write inside a try/except around the
`PatchCompletenessError`-raising path. The INBOX write must NEVER swallow the
operator-facing exception, so `except Exception: pass` is the right shape —
the documented contract is "INBOX is best-effort; never block the actual gate
behaviour." The existing `# pragma: no cover` comment names the rationale.
Added noqa with one-line cite.

**Disposition mix**: 1 noqa, 0 fix.
