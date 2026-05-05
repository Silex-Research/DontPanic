# F001 close-out memo — 2026-05-04

Plan: `2026-05-04-004-fix-ec5-classifier-purity`
Feature: F001 — Two-part scoped fix for the ec5_classifier purity caveat (D011 of plan 2026-05-03-003) that has been excluding `test_ec5_classifier.py` from every full-suite invocation across Plans A/B/C.

## Direct-path rationale

F001 is mechanical and deterministic — replace one helper call (`resolve_repo` → `_derive_classifier_repo`) and one test's monkeypatch surface (class-level `Path.stat` → targeted sentinels). Acceptance is provable by running the suite with and without the `--ignore` flag and observing the test count delta. No semantic decisions for an auditor to debate. Volley quota stays unjustified for this surface.

## What landed

| File | Change | Role |
|---|---|---|
| `scripts/dontpanic_orchestrate/ec5_classifier.py` | Removed `resolve_repo` import; replaced `repo = resolve_repo(tc)` with `repo = _derive_classifier_repo(tc, parsed)`; new pure helper added (~20 lines) | Part 2 — classifier-local pure repo derivation (D002) |
| `scripts/dontpanic_orchestrate/tests/test_ec5_classifier.py` | Replaced `monkeypatch.setattr(Path, 'stat', _explode)` with the locked targeted sentinel set (`subprocess.run`, `Path.read_text`, `Path.write_text`, `Path.open`); added `import subprocess`; renamed `_explode`→`_trip` | Part 1 — purity test seam (D001) |

`scripts/dontpanic_orchestrate/target_context_prelude.py` is byte-identical to pre-Plan-D per D002 — `git diff` returns empty. `resolve_repo()` and other helpers stay as-is; `audit_writer._normalize_summary` and any other caller continue using them.

## All 13 acceptance items verified

| # | AC | Result |
|---|---|---|
| 1 | `test_classifier_is_pure_no_io` passes | ✓ targeted sentinels intercept `subprocess.run`, `Path.read_text`, `Path.write_text`, `Path.open`; classifier reaches none of them. |
| 2 | Patch set excludes `Path.stat` and `Path.exists` | ✓ explicit grep on test file: zero hits for `monkeypatch.setattr(Path, 'stat'` or `monkeypatch.setattr(Path, 'exists'`. |
| 3 | No INTERNALERROR on assertion failure | ✓ verified by injection — `assert False` under the targeted sentinels produces a normal `AssertionError`, not the previous `INTERNALERROR` that the class-level `Path.stat` trap caused. |
| 4 | `_derive_classifier_repo` selection logic correct | ✓ `tc.get('repo')` first, else `parsed.get('repo')` when `parsed is not None`, else None. Implemented as a pure function. |
| 5 | `classify_ec5_severity()` no longer calls `resolve_repo()` | ✓ `grep -n 'resolve_repo' scripts/dontpanic_orchestrate/ec5_classifier.py` returns zero hits (comment was tightened to avoid the substring match). |
| 6 | `target_context_prelude.py` byte-identical | ✓ `git diff scripts/dontpanic_orchestrate/target_context_prelude.py` returns empty. Other callers (audit_writer._normalize_summary) continue to use `resolve_repo()` unchanged. |
| 7 | `test_case_c_golden_returns_none` passes WITHOUT cwd repo fallback (operator-added AC) | ✓ The fixture has `Repo: Jarvis` in its prelude and no `target_context.repo`. Classifier picks `parsed['repo']` = `"Jarvis"` for the comparison; renders match parsed; verdict = `'none'`. |
| 8 | Other ec5_classifier semantics preserved | ✓ All 20 ec5 tests pass — env/project/command-mismatch detection still produces `i1` (test_case_g); struct-incomplete still produces `i1` (test_invalid_struct); missing prelude with valid struct still produces `i0`. |
| 9 | Full orchestrate suite passes WITHOUT `--ignore=test_ec5_classifier.py` | ✓ **979 passed, 6 skipped** in 18.45s. Plan C close-out baseline 959+6 → +20 net = exactly the 20 ec5_classifier tests now included. **Zero regressions** in any pre-existing test. |
| 10 | Ruff check + format clean | ✓ `ruff check` and `ruff format --check` both pass on `ec5_classifier.py` and `test_ec5_classifier.py`. |
| 11 | Sanitization clean | ✓ 0 findings, 693 files scanned. |
| 12 | Plans A/B/C close-out memos byte-identical | ✓ `git diff docs/plans/` for the Plan D commit boundary shows zero entries outside `2026-05-04-004-fix-ec5-classifier-purity/`. The `--ignore` references in Plans A/B/C close-out memos remain accurate-as-of-then. |
| 13 | `git diff --name-only HEAD` zero entries under `docs/plans/` outside Plan D's own dir | ✓ Same evidence as #12 — durability of audit history preserved per D004. |

## EC5 ignore caveat — closed at this commit

Per D006, this commit is the canonical record that the `--ignore=scripts/dontpanic_orchestrate/tests/test_ec5_classifier.py` caveat is closed going forward. Plans A/B/C close-out memos accurately recorded the verification approach at the time those plans shipped — they remain byte-identical (D004).

**Going-forward command shape:**

```
PYTHONPATH=scripts python -m pytest scripts/dontpanic_orchestrate/tests/ -p no:cacheprovider
```

(no `--ignore` flag).

## Plan C → Plan D test-count progression

| Plan | Sweep command | Result |
|---|---|---|
| Plan C close-out | `pytest --ignore=test_ec5_classifier.py ...` | 959 passed, 6 skipped |
| Plan D close-out | `pytest ...` (no ignore) | **979 passed, 6 skipped** |

Delta: +20 = the count of tests in `test_ec5_classifier.py`, all now green.

## Four-plan sequence complete

| Plan | Slice | Path | Commit |
|---|---|---|---|
| A | Canonical Python module rename | direct | `8edd953` |
| B | Lifecycle-staged human gates | volley | `dc9c6cd` |
| C | Subprocess timeout / envelope durability (F001+F002+F003) | direct + direct + volley | `3b4c0b1`, `3d47ce2`, `89061a3` |
| D | EC5 classifier purity | direct | this commit |

## Queued caveats — not addressed by Plan D (D008)

Three caveats remain on the durable queue, each as a standalone future slice:

1. **Plan validator strict-validates `audit/*.json`** — fails on `gate-state.json` and similar non-envelope files. Surfaced at F003 close-out of Plan C.
2. **Per-plan `loop_caps.subprocess_timeout_seconds`** — deferred from Plan C D003 (env-var configurability ships v1; per-plan needs schema bump or `executor_caps:` parser carve-out).
3. **`jarvis_orchestrate` shim removal timeline** — deferred from Plan A D006 (wait for migration evidence).

## Files NOT in this commit

- The pre-existing dirty / untracked state under `docs/plans/2026-05-01-001-feat-onboarding-ux/`, `docs/plans/2026-05-01-002-feat-discord-notification-sink/`, `docs/plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/`, `docs/plans/2026-05-03-003-feat-agent-access-manifest-thin-mcp/INBOX.md`, `claude/PORTABILITY.md`, `claude/scripts/sync-harness.sh`, `dashboard/state/costs.json`, etc. — same unrelated carryover that's been excluded from every prior plan's commit boundary.
