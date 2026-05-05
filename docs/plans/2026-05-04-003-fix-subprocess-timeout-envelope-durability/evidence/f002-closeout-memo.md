# F002 close-out memo — 2026-05-04

Plan: `2026-05-04-003-fix-subprocess-timeout-envelope-durability`
Feature: F002 — Timeout evidence layered into the existing audit envelope schema. Reads F001's `SubprocessResult` from `DispatchResult.subprocess_result` and renders structured markers, summary blocks, sidecar partials, and a `correctness/medium` finding (when worktree changed) — all within the schema-locked envelope shape.

## Direct-path rationale

F002 is mechanical and AC-driven (D009): given F001's already-merged `SubprocessResult` shape, F002's job is to render that shape into existing audit-envelope fields. Schema discipline is the risk surface, and that's covered by 16 explicit acceptance items including a parametric schema round-trip test. No semantic decisions for an auditor to debate. Volley quota stays reserved for F003.

## What landed

| File | Change | Role |
|---|---|---|
| `scripts/dontpanic_orchestrate/audit_writer.py` | +5 module-level helpers + `build_audit()` extension (~140 added lines) | F002 evidence layer |
| `scripts/dontpanic_orchestrate/tests/test_audit_envelope_timeout_evidence.py` (new) | 21 tests across 6 classes covering all 16 ACs | Test surface |

Five new helpers in `audit_writer.py`:

- `_render_worktree_value(bool | None) -> str` — ternary `true|false|unknown` rendering shared by markers, summary block, and finding text.
- `_timeout_summary_block(SubprocessResult) -> str` — multi-line structured context replacing the bare `DISPATCH FAILED: TimeoutExpired...`.
- `_timeout_markers(SubprocessResult) -> list[str]` — `validation_performed` markers (`subprocess_timeout_seconds=N`, `timeout_stdout_bytes=N`, `worktree_changed=true|false|unknown`, `grace_period_used=true|false`, plus env_markers passthrough). No-op when `spr is None or not spr.timed_out`.
- `_timeout_finding(SubprocessResult, feature_id) -> dict | None` — structured `correctness/medium` finding emitted ONLY when `timed_out=true AND worktree_changed=true`. Returns `None` for the three non-firing cases (no false positives).
- `_write_partial_sidecars(plan_dir, audit_id, SubprocessResult) -> list[str]` — writes captured stdout/stderr to `<plan_dir>/audit/partials/<audit_id>.{stdout,stderr}.{txt,bin}` and returns the corresponding `partial_*_path=audit/partials/...` marker strings.

`build_audit()` extension is contained: when `result.subprocess_result` is present and indicates timeout, it appends timeout markers + sidecar markers to `validation_performed`, layers a structured timeout block into `summary` (via `_summary()` extension), and appends the timeout finding when applicable. All non-timeout paths are byte-stable.

## Verification

- **Targeted F002**: `pytest scripts/dontpanic_orchestrate/tests/test_audit_envelope_timeout_evidence.py` — **21 passed in 0.23s**.
- **Pre-existing audit_writer regression set**: `test_audit_writer_normalize.py` + `test_audit_writer_f002_supervisor_integration.py` + `test_audit_filename_feature_id.py` — **42 passed**.
- **Full orchestrate suite** (excl. `test_ec5_classifier.py` per Plan D scope): **920 passed, 6 skipped in 17.83s**. Baseline before F002 was 899+6 → **+21 net delta = exactly the 21 new F002 tests; ZERO regressions** in any pre-existing test.
- **Ruff check + format check clean** across canonical tree (auto-fixed import ordering + format on `audit_writer.py` and the new test file).
- **`python scripts/sanitization_check.py`** — 0 findings, 679 files scanned.

## All 16 acceptance items verified

| # | AC | Result |
|---|---|---|
| 1 | Schema validity preserved (audit_status stays `blocked`, no `additionalProperties` violations) | ✓ `TestSchemaValidityAndByteStability::test_timeout_envelope_validates_against_schema` writes envelope through `audit_writer.write()` which validates via `Audit.model_validate`; spot-checks forbidden top-level keys absent. |
| 2 | Structured `summary` for timeouts | ✓ `TestStructuredTimeoutSummary::test_summary_replaces_bare_dispatch_failed` — block contains all 5 required fields. |
| 3 | `validation_performed` markers present | ✓ `TestValidationPerformedMarkers::test_all_required_timeout_markers_present` — all 5 markers asserted. |
| 4 | Env-var fallback markers surfaced | ✓ `TestEnvFallbackMarkers::test_env_invalid_marker_surfaces_in_validation_performed`. |
| 5 | Structured finding on timeout + worktree_changed=true | ✓ `TestTimeoutFinding::test_finding_emitted_when_timeout_and_worktree_changed` — severity `medium`, category `correctness`, issue text and evidence checked. |
| 6 | No false-positive finding | ✓ Three parametric cases: `worktree_changed=False`, `worktree_changed=None`, no timeout — all return zero timeout findings. |
| 7 | Sidecar partials written + referenced via marker | ✓ `TestSidecarPartials::test_stdout_sidecar_written_when_bytes_captured` — sidecar at expected path; marker in `validation_performed`; NOT a top-level field. |
| 8 | No sidecar when no bytes | ✓ `test_no_sidecar_when_no_bytes_captured` — no partials/ dir, no marker. |
| 9 | UTF-8-undecodable bytes → `.bin` sidecar | ✓ `test_undecodable_bytes_written_as_bin_with_adjusted_marker` — invalid byte sequence written as `.bin`, marker reflects path. |
| 10 | No new top-level audit envelope fields | ✓ Schema validation gates this (would fail on `additionalProperties: false`); plus explicit spot-check assertion. |
| 11 | Non-timeout cases byte-stable | ✓ Three byte-stability tests cover: subprocess_result=None, subprocess_result.timed_out=False, success=True. Each asserts validation_performed unchanged + no sidecar dir + no timeout markers in summary. |
| 12 | No `circuit_breakers.py` diff in F002 commit | ✓ `TestF002BoundaryDiscipline::test_f002_does_not_import_circuit_breakers` — grep on audit_writer.py source for circuit_breakers imports returns zero hits. F003 may diff per D008. |
| 13 | Full orchestrate suite passes; +N delta exactly | ✓ 920 passed (baseline 899 + 21 new = 920); 6 skipped unchanged. Zero regressions. |
| 14 | Ruff check + format clean | ✓ `ruff check` and `ruff format --check` both pass. |
| 15 | Sanitization clean | ✓ 0 findings, 679 files scanned. |
| 16 | Zero `docs/plans/` entries outside Plan C dir | ✓ Only `2026-05-04-003-fix-subprocess-timeout-envelope-durability/` touched in this commit. |

## Schema discipline confirmed

- **`audit_status` enum unchanged** — timeouts stay `blocked` per D002. No agent-conventions schema bump required.
- **No new top-level audit JSON fields** per D004 — the schema's `additionalProperties: false` would reject anything new. All evidence flows through the existing `summary`, `validation_performed`, and `findings` fields.
- **Sidecars at `<plan_dir>/audit/partials/`** per D004 — referenced from `validation_performed` strings (e.g., `partial_stdout_path=audit/partials/<audit_id>.stdout.txt`), never inline as a structured envelope field.
- **Finding category stays `correctness`** per D007 — existing schema-locked enum value, no extension.
- **Worktree detection optional** per D006 — `worktree_changed=None` (rendered `unknown`) when cwd is not a git repo or git is unavailable; never fails dispatch; doesn't trigger the timeout-with-work finding.
- **`circuit_breakers.py` untouched in F002** — boundary preserved per AC #12; F003 may diff per D008.

## What this enables for F003

F003 (volley) reads F002's `validation_performed` markers — specifically the combination `audit_status: blocked AND worktree_changed=true` — to classify timeout-with-work envelopes as "real progress, just envelope-truncated" rather than "zero progress." That classifier change is the actual fix Plan B's exact failure pattern (timeout both rounds, work landed, supervisor called `stopped_no_progress`).

After F003 ships, the established accept-on-direct-review workaround for timeout-with-work runs becomes diagnosable from envelope evidence alone — no operator tribal memory required.

## Next slice

F003 — supervisor classifier excludes timeout-with-work from no-progress / diminishing-returns counting. **Volley** path per D009. The pre-volley audit-focus addendum is already inside `plan.md`; the F002 lock-commit + this close-out commit double as the pre-volley boundary. Dispatch via:

```
dontpanic dispatch-from-plan docs/plans/2026-05-04-003-fix-subprocess-timeout-envelope-durability --feature F003 --confirm
```

Plan B's lifecycle-staged gates govern the dispatch: `pre_impl` clears before iter 0, `pre_merge` only fires on candidate-success path. If F003's volley itself produces timeout-with-work envelopes (likely — the new classifier isn't merged yet), accept on direct review per D011 and the established F002/F003-of-plan-003 + Plan-B pattern.
