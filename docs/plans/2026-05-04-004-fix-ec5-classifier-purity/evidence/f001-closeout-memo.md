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

---

## Status-flip close-out verification (added 2026-05-07)

This section was added at the formal `active → completed` flip in the Tier 2/3 close-out batch and records the platform/agent-boundary discipline this plan honors. Impl-time content above is byte-untouched.

### Central correctness claim (operator-named, EC5-specific)

> Does the fix keep classifier responsibility at the platform boundary instead of letting the platform infer agent intent or judge content beyond the target-context contract?

**Answer: yes.** The classifier classifies structural conditions only.

| What the platform classifier MAY do | What it MUST NOT do |
|---|---|
| Check whether `target_context.repo` is present in the envelope (structural) | Subprocess into git / shell / any external process for environment inference |
| Parse a prelude string and check whether it has a `repo:` field (structural prose-vs-structured form check) | Reach the filesystem to look up "where am I running" |
| Compare envelope `canonical_render` against a computed render of the same fields (field-equality check) | Infer whether the agent *intended* to claim a particular repo / env / project |
| Detect env / project / command mismatch by structural comparison | Judge whether the auditor's reasoning is sound, well-grounded, or factually accurate |
| Return `i0` / `i1` based on structural-completeness rules locked in this plan's acceptance | Classify auditor-prompt quality, prompt-format variance, or content-correctness beyond the target-context contract |

Verified at code level:

- `scripts/dontpanic_orchestrate/ec5_classifier.py:99` — `classify_ec5_severity()` calls `_derive_classifier_repo(tc, parsed)`. The helper at line 114 reads `tc.get('repo')` first, falls back to `parsed.get('repo')`, returns None when neither is available. **Pure function. No subprocess. No filesystem.**
- `scripts/dontpanic_orchestrate/tests/test_ec5_classifier.py:295–298` — purity sentinels patch `subprocess.run`, `Path.read_text`, `Path.write_text`, `Path.open` only. `Path.stat` and `Path.exists` are NOT patched (D001 — pytest's traceback formatter calls them; trapping at class level produces `INTERNALERROR` instead of normal red).
- `scripts/dontpanic_orchestrate/target_context_prelude.py` is byte-identical to pre-Plan-D state (D002 + protected_paths). `resolve_repo()` and other helpers stay as-is; `audit_writer._normalize_summary` and any other caller continue using them unchanged.

### Phase B caveat citation — resolved cleanly, narrowly

Plan 2026-05-03-003 (Phase B) `evidence/plan-closeout-memo.md` lists this plan in its "Cross-link to follow-up platform slices" table, naming the caveat precisely:

> F001/D011 — EC5 classifier purity regression in `test_ec5_classifier.py`

That **named** caveat is now closed. Verifiable artifact: full orchestrate suite runs without `--ignore=scripts/dontpanic_orchestrate/tests/test_ec5_classifier.py` and reports 979 passed / 6 skipped (Plan C close-out 959 + 6 baseline + 20 newly-included ec5 tests = 979 + 6 — verified at impl-time, AC#9 above).

The Phase B caveat is **not** "all EC5/prompt-format issues are solved." It is specifically the test-purity regression introduced by the Jarvis → DontPanic rename (the cwd-dependent `resolve_repo()` mismatching historical `Repo: Jarvis` fixtures + the `Path.stat` global trap turning assertion failures into `INTERNALERROR`). Both root causes are addressed by this plan.

### What this plan does NOT solve

Per operator framing at close-out, the following remain separate concerns and are explicitly **not** subsumed by this plan:

- **Auditor-prompt quality** — whether the auditor consistently produces well-shaped EC5 envelopes with the correct structural fields, prose-vs-structured prelude format, and target-context block. This is a prompt-tuning concern, not a classifier-purity concern.
- **`resolve_repo()` itself** — D002 explicitly preserved this helper unchanged. It still does subprocess `git rev-parse` and is still used by `audit_writer._normalize_summary` and other callers. If a future plan needs to make `resolve_repo()` itself pure or move it behind a seam, that is a separate slice.
- **Other queued caveats** (impl-time memo's "Queued caveats" section, D008) — plan validator strict-validation (closed at `03cc0b9` by Plan 2026-05-05-001), per-plan subprocess timeout, jarvis_orchestrate shim removal — all separate slices.
- **Broader content-correctness or semantic-truth judgment** — the platform classifier intentionally does not assess whether the auditor's findings are factually grounded, intent-aligned, or reasoning-sound. That belongs at the agent level, not the platform-classifier level.

This plan's correctness claim is narrowly scoped: structural classification stays pure (no I/O), repo derivation stays envelope-local (no subprocess), and the previously-excluded test now runs in the full sweep.
