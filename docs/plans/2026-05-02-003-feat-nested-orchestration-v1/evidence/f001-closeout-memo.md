# Plan 2026-05-02-003 F001 — Close-out Memo

**Status:** F001 closed (passes: true). F002 + F003 not yet started.
**Path:** Direct (no volley). Operator-approved per the discussion that
followed the plan lock.

## Why direct

F001 is a schema/validation/guard slice with locked decisions (D001–D006)
and mostly deterministic tests. The only design ambiguity at lock time was
the spawn-identity shape, and D001 resolved it (structured five-field
SpawnFinding + deterministic SHA-256 finding_signature). A confirmation
volley adds little here — the logic is mechanical, the contract surfaces
were settled in the plan, and a real recursive-finding case to exercise
end-to-end won't exist until F003 (parent pause/fan-in) lands. Direct
delivery now; volley later when there is a real flow to dogfood.

## What shipped

### New module — `scripts/jarvis_orchestrate/nested_orchestration.py`
- `SpawnFinding` Pydantic model (five required fields per D001:
  `parent_audit_id`, `finding_id`, `finding_code`, `finding_class`,
  `finding_signature`).
- `Orchestration` Pydantic model with cross-field invariants:
  - `spawn_reason='auditor_finding'` requires `spawn_finding`
  - `spawn_reason='operator_manual'` rejects `spawn_finding`
  - `depth_limit > DEFAULT_DEPTH_LIMIT (3)` rejected at parse time (D002 —
    frontmatter cannot raise the platform cap)
  - `depth_limit < 1` rejected.
- `compute_finding_signature(code, class, issue) -> str` — deterministic
  SHA-256 hex prefix of `{code}|{class}|{normalized_issue}` where
  `normalized_issue` = whitespace-collapsed lowercase issue text. Returns
  the first 16 hex chars (64 bits) — collision-free within a plan tree.
- `walk_parent_chain` / `compute_depth` — transitive walk over
  `orchestration.parent_plan_id`, returns `[child, parent, grandparent, ...]`
  for nested plans, `[plan_id]` for top-level.
- Three guards (each raises `NestedOrchestrationError`):
  - `check_depth(plan_dir, override_max=None)` — effective cap is the
    LOWER of frontmatter `depth_limit` and `override_max`; CLI's
    `--allow-depth N` passes `override_max=N` (D002).
  - `check_cycle(plan_dir)` — refuses dispatch if any plan_id repeats in
    the chain.
  - `check_repeated_finding(plan_dir)` — refuses dispatch if the current
    plan's `finding_signature` matches any parent's recorded signature
    (D001 — inception-loss guard).

### Plan loader extension — `scripts/jarvis_orchestrate/plan_loader.py`
- `LoadedPlan` gains `orchestration: Orchestration | None = None`.
- `load()` pops `orchestration` from frontmatter dict BEFORE
  `Plan.model_validate(fm)` — Plan model has `extra="forbid"` and would
  reject the unknown key. This is D006-style schema discipline:
  `agent-conventions/schemas/v1.0` is unchanged; the orchestration block
  is a parser-level concern.

### Supervisor wiring — `scripts/jarvis_orchestrate/supervisor.py`
- New helper `_run_nested_orch_guards(plan_dir, *, allow_depth)` invokes
  all three guards and returns a marker string when an override was used:
  `depth_override applied (N)`.
- Both `dispatch_single_agent` and `dispatch_volley` accept
  `allow_depth: int | None = None` and call the helper after
  `plan_loader.load`. The marker is appended to the audit envelope's
  `validation_performed` (or volley `extra_validation`) list for
  audit-trail visibility.

### CLI flag — `scripts/jarvis_orchestrate/cli.py`
- `--allow-depth N` int flag added to both volley and single-agent
  paths. CLI is the ONLY mechanism for raising the depth cap (D002 —
  frontmatter cannot raise its own cap).

### Tests — `scripts/jarvis_orchestrate/tests/test_nested_orchestration.py`
21 tests covering:
- Signature determinism (whitespace + case invariance) and distinctness
  across `(code, class, issue)`.
- Pydantic cross-field invariants — auditor_finding/operator_manual
  consistency, depth_limit upper/lower bounds.
- `walk_parent_chain` at depths 1, 2, 3.
- `check_depth` pass/fail/override paths.
- `check_cycle` on a 3-plan A→B→C→A loop.
- `check_repeated_finding`: passes on distinct signatures sharing
  `(code, class)`; raises on signature collision climbing the chain.
- `plan_loader.load` integration: top-level plans return
  `orchestration=None`; child plans parse correctly.

## Anti-recursion enforcement (the thesis)

Three guards together make unbounded "fixing the same thing" chains
structurally impossible:

1. **Depth cap (default 3, D002)** — bounds total nesting; only operators
   at dispatch can lift it.
2. **Cycle detection** — a `plan_id` cannot appear twice in its own
   parent chain.
3. **Signature-based repeated-finding hard stop (D001)** — even at
   depth ≤ 3 with no cycle, a child claiming to fix the same finding
   that any ancestor already claimed to fix is refused at dispatch.

The signature, not the `(code, class)` pair, is what gates: a single
auditor produces many `(EC5, correctness)` findings across plans, but
each has different concrete issue text and therefore a different
signature. Repeated **identical** findings — the inception-loss shape —
collide; distinct findings that happen to share a code don't.

## Test / lint / sanitization state

- **Targeted:** `pytest scripts/jarvis_orchestrate/tests/test_nested_orchestration.py`
  → 21 passed.
- **Full orchestrate suite:** `pytest scripts/jarvis_orchestrate/tests/`
  → 490 passed, 6 skipped (was 469 before this work; +21 F001 tests).
- **Ruff:** `ruff check` on the five changed/added files → all checks
  passed.
- **Sanitization:** `python scripts/sanitization_check.py` →
  `✓ no campaign IDs or secret shapes in sanitized surface (557 files
  scanned)`.

### Test state

| Surface | Before | After | Delta |
| --- | --- | --- | --- |
| F001 targeted | n/a | 21 passed | +21 |
| Full orchestrate suite | 469 + 6 skipped | 490 + 6 skipped | +21 |
| Ruff (changed files) | clean | clean | — |
| Sanitization | clean | clean | — |

## Files in this commit (scoped per operator directive)

- `scripts/jarvis_orchestrate/nested_orchestration.py` (new)
- `scripts/jarvis_orchestrate/plan_loader.py` (orchestration field +
  pop-before-validate)
- `scripts/jarvis_orchestrate/supervisor.py` (`_run_nested_orch_guards`
  + `allow_depth` plumbing on both dispatch paths)
- `scripts/jarvis_orchestrate/cli.py` (`--allow-depth N` flag)
- `scripts/jarvis_orchestrate/tests/test_nested_orchestration.py` (new,
  21 tests)
- `docs/plans/2026-05-02-003-feat-nested-orchestration-v1/decisions.jsonl`
  (D007 close-out entry)
- `docs/plans/2026-05-02-003-feat-nested-orchestration-v1/features.json`
  (F001 → passes: true with 7 evidence_refs)
- `docs/plans/2026-05-02-003-feat-nested-orchestration-v1/evidence/f001-closeout-memo.md`
  (this file)

F002 and F003 surfaces (`ChildCharter`, `CommitPolicy`,
`pre_resume_after_child` gate, events.jsonl writer, INBOX
`nested_child_pending` template) are **not** touched in this commit.

## Plan 003 status after this commit

- F001: ✅ closed (parent/child metadata + depth/cycle/repeated-finding
  guards).
- F002: pending (child charter + commit policy — depends on F001).
- F003: pending (parent pause/fan-in protocol — depends on F001 + F002).

Next: F002. Path-decision (direct vs volley) deferred to dispatch time;
volley becomes more useful once F003's parent-pause flow exists to
exercise charter compliance against a real child run.
