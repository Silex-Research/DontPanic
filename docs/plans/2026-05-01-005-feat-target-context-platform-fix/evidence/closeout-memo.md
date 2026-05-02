# F001 close-out memo — target-context prelude helpers

**Plan:** `2026-05-01-005-feat-target-context-platform-fix`
**Feature:** F001
**Captured:** 2026-05-02 (post-volley close-out)

## Volley arc

Two-iteration volley terminated on `stopped_no_progress` after both rounds
returned `needs_changes`. Implementer commit `95d3eeb` shipped the F001
deliverable verbatim per locked acceptance:

- `scripts/jarvis_orchestrate/target_context_prelude.py` — `PRELUDE_TEMPLATE`
  (D001 byte-exact), `render_prelude` (pure), `resolve_repo` (D002 cwd-fallback
  shim), `validate_target_context`, `parse_prelude_block`, `TargetContextError`.
  Implementer addressed i0 audit findings during the volley: split cwd I/O
  out of `render_prelude` to make it genuinely pure; tightened
  `parse_prelude_block` to require D001's trailing blank line.
- `scripts/jarvis_orchestrate/tests/test_target_context_prelude.py` — 65
  tests covering golden output, 100-call determinism, repo precedence
  (struct/cwd-fallback/hard-fail), project special-case rendering,
  validate_target_context invalid + valid shapes, parse_prelude_block
  parametrized over all 7 fixtures, fixture-files-load smoke test.
- `evidence/f001/fixtures/case-{a..g}.json` — 7 regression fixtures sourced
  from real recent envelopes, including case-g prelude-value-mismatch as the
  narrow-downgrade negative control.

## Test + lint state at close-out

```
$ PYTHONPATH=scripts python3 -m pytest scripts/jarvis_orchestrate/tests/test_target_context_prelude.py -q
65 passed in 0.14s

$ PYTHONPATH=scripts python3 -m pytest scripts/jarvis_orchestrate/tests/ -q
407 passed, 6 skipped in 8.35s

$ ruff check scripts/
All checks passed!

$ python3 scripts/sanitization_check.py
✓ no campaign IDs or secret shapes in sanitized surface (531 files scanned)
```

## Residual HIGH finding — meta-recursive, deferred to F002+F003

Auditor i1 reported one HIGH finding: implementer summary
(`claude-implementer-i1.json.summary`) is missing the canonical prose
`Repo / Env: dev / Project: (none) / Command: <count>` declaration block.

**Structured target_context is fully valid:**

| Field | Value |
|---|---|
| `env` | `'dev'` |
| `project` | `None` (host-local; matches plan.md `target_project: none`) |
| `commands_run` | populated, 7 entries (pytest invocations + ruff + cmp checks) |

The missing-prose-with-valid-struct case is exactly what this plan's own
**D005** (auditor severity is platform-enforced) and **F003** (narrow
downgrade rule: missing/malformed prose with valid struct → i0) exist to
fix. F001 only delivers helpers + fixtures; the consuming surfaces — auto-
injection at audit_writer (F002) and severity classifier with description
preservation (F003) — are subsequent features. F001 cannot contain its own
consumers' fix without absorbing F002+F003's scope.

This is the same shape as plan `2026-05-02-001-feat-resume-gate-discipline`'s
D006 close-out (HIGH command-accountability finding deferred to this plan).
The dogfood arc converges as the plan ships its features in order.

**No audit envelope was edited post-hoc.** All 4 audit envelopes preserved
verbatim under `audit/`.

## Decision: flip `passes:true`

The F001 deliverable is feature-complete:

- Helpers exported, importable, type-checked
- Pure-function discipline verified (100-call determinism + auditor-confirmed
  cwd I/O extracted to `resolve_repo`)
- 7 fixtures land per locked acceptance (#8) including case-g negative
  control per acceptance #10
- 65 targeted tests pass; 407/413 full suite green; ruff + sanitization clean
- Schema-validation requirements met (acceptance #6 four invalid shapes,
  #11 parametrized, #12 no supervisor changes)

The remaining HIGH is F002+F003 territory and is recorded in D010 with
explicit deferral. F001 ships passes:true.
