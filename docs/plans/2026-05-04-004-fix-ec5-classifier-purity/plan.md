---
id: 2026-05-04-004-fix-ec5-classifier-purity
title: Fix — EC5 classifier purity (no filesystem reach, classifier-local repo derivation)
type: fix
tier: cross-cutting
status: completed
date: "2026-05-04"
description: |
  Two-part scoped fix for the long-standing EC5 classifier purity test
  caveat (D011 of plan 2026-05-03-003) that has been excluding
  `test_ec5_classifier.py` from the full orchestrate sweep across Plans
  A/B/C.

  **Part 1 — purity test seam.** Replace the global
  `Path.stat` class-level monkeypatch with targeted sentinels around
  the *specific* collaborators the classifier could reach if it ever
  touched disk: `subprocess.run`, `Path.read_text`,
  `Path.write_text`, `Path.open`. **No `Path.stat` patching** —
  pytest's traceback formatter calls `code.path` → `p.exists()` →
  `self.stat()` during failure rendering, and a class-level trap
  there turns assertion failures into `INTERNALERROR` (the exact
  pathology Plan D exists to fix).

  **Part 2 — classifier-local repo derivation.** Stop calling
  `target_context_prelude.resolve_repo()` from
  `classify_ec5_severity()`. The classifier picks a repo for canonical
  render comparison purely from data already in the envelope:

  - if `target_context.repo` is present → use it;
  - else if the summary contained a parseable prelude → use
    `parsed["repo"]` for the render comparison;
  - else (struct-incomplete + no prelude) → `i1` per existing
    semantics; missing prelude with valid struct stays `i0`.

  This preserves historical fixtures with `Repo: Jarvis` (predating
  the DontPanic rename), avoids cwd-dependent classification mismatch,
  and keeps env / project / command-mismatch detection intact.

  **`resolve_repo()` itself is NOT modified.** It stays in
  `target_context_prelude.py` and other callers (notably
  `audit_writer._normalize_summary`) continue to use it as today.

motivation: |
  The EC5 classifier purity test (`test_classifier_is_pure_no_io`)
  was broken across the directory rename Jarvis → DontPanic
  (committed at plan 2026-05-03-003, formalized via D011 of that
  plan). Two intertwined failures:

  - The class-level `monkeypatch.setattr(Path, "stat", _explode)`
    leaked into pytest's traceback formatter when an assertion under
    the test failed, turning a normal red into `INTERNALERROR`.
  - The classifier's call to `resolve_repo()` (which runs
    `subprocess.run(['git', 'rev-parse', '--show-toplevel'])`)
    started returning the post-rename repo basename, mismatching
    historical fixtures that hardcoded `Repo: Jarvis`.

  Plan D closes both, lets the full orchestrate sweep run *without*
  the `--ignore=scripts/dontpanic_orchestrate/tests/test_ec5_classifier.py`
  exclusion that's been threaded through every close-out memo since
  Plan A. Plans A/B/C close-out memos stay byte-identical (D004 — they
  accurately record verification state at the time, durable record
  per the same plan-id-brand-policy memory that protects historical
  audit envelopes).
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 1
  no_progress_threshold: 1
  wall_clock_hours: 2
  hard_stop: false
privacy_tier: internal
protected_paths:
  # Same protected set as Plans A/B/C — historical plan dirs durable,
  # subtree upstream, operator assets unchanged.
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - claude/shared/
  # Plan D explicitly does NOT touch resolve_repo() (D002).
  - scripts/dontpanic_orchestrate/target_context_prelude.py
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Single feature, two-part fix:

1. **`scripts/dontpanic_orchestrate/ec5_classifier.py`** — replace the
   single-line `repo = resolve_repo(tc)` (or equivalent) with a
   classifier-local helper that derives `repo` from the envelope's
   own data: `tc.get("repo")` first, then the parsed prelude's
   `repo` if present, then None when neither is available. The render
   comparison uses that derived repo. No `subprocess.run`. No
   filesystem reach.

2. **`scripts/dontpanic_orchestrate/tests/test_ec5_classifier.py`** —
   replace the existing `Path.stat` class-level monkeypatch with
   targeted sentinels around classifier-reachable collaborators only.
   Patch set: `subprocess.run`, `Path.read_text`, `Path.write_text`,
   `Path.open`. Pytest's `Path.stat` and `Path.exists` are NOT
   patched (they're used by traceback formatting and other framework
   internals; trapping them turns assertion failures into
   `INTERNALERROR`).

## Out of scope (deliberate)

- **`target_context_prelude.resolve_repo()` modification.** The
  helper stays as-is; other callers (`audit_writer._normalize_summary`)
  continue using it. The classifier just stops calling it. D002.
- **Other purity tests in the orchestrate suite.** Plan D's surface
  is ec5_classifier purity only.
- **Schema changes to `target_context.repo`.** Already optional in
  the schema; Plan D uses the existing field shape.
- **Rewriting Plans A/B/C close-out memos** to remove the
  `--ignore=...test_ec5_classifier.py` references. Those memos
  accurately record the verification state at the time; rewriting
  them would conflate Plan D's progress with the historical audit
  trail. D004.
- **The validator-hygiene caveat** (audit/*.json strict-validation
  failing on `gate-state.json`) — separately queued slice. D008.
- **Per-plan timeout configurability** (deferred from Plan C D003)
  and **shim removal** (deferred from Plan A D006) — both stay
  queued.

## Cross-cutting tightenings (operator-supplied)

Per pre-draft conversation. Codified in D001-D006:

1. **Targeted purity sentinels, NOT class-level `Path.stat`.** Patch
   only the classifier-reachable I/O surfaces (`subprocess.run`,
   `Path.read_text`, `Path.write_text`, `Path.open`). Avoid `Path.stat`
   and `Path.exists` because pytest's traceback formatter uses them
   during failure rendering. D001.

2. **Classifier-local pure repo derivation, NOT `resolve_repo()`
   modification.** The classifier reads `target_context.repo` first,
   falls back to the parsed prelude's `repo`, then defaults to
   missing-prelude i0 semantics. `resolve_repo()` itself unchanged.
   D002.

3. **Historical close-out memos preserved.** Plans A/B/C evidence
   stays byte-identical. Plan D's own D-entry + close-out memo
   record that the ignore caveat is closed going forward. D004.

4. **Historical fixtures with `Repo: Jarvis` remain valid.** The
   classifier-local derivation must accept the parsed prelude's
   repo as the comparison value when `target_context.repo` is
   absent — so pre-DontPanic-rename fixtures don't suddenly become
   `i1` after Plan D ships. D005.

## Execution path

**Direct.** Locked at parent-sequence scoping turn (D003). The fix
is mechanical and deterministic — replacing one helper call + the
test's monkeypatch surface. Acceptance is provable by running the
suite with and without the `--ignore` flag.

## Acceptance summary

Binding contract is in `features.json` F001. Highlights:

- `test_ec5_classifier.py::test_classifier_is_pure_no_io` passes.
- `test_ec5_classifier.py::test_case_c_golden_returns_none` passes
  WITHOUT cwd repo fallback — proving historical `Repo: Jarvis`
  fixtures remain valid when `target_context.repo` is absent
  (operator-added AC).
- Test failure path does NOT `INTERNALERROR` — a deliberate
  assertion failure produces a normal pytest failure.
- Full orchestrate suite passes WITHOUT the
  `--ignore=...test_ec5_classifier.py` flag. Test count goes
  from 959 (Plan C close-out baseline) up by approximately +N
  where N is the ec5_classifier test file's count.
- `classify_ec5_severity()` no longer calls `resolve_repo()`
  (greppable assertion: zero `resolve_repo` references in
  `ec5_classifier.py` after the diff).
- `resolve_repo()` and the rest of `target_context_prelude.py`
  are byte-identical to pre-Plan-D (greppable: zero diffs).
- Plans A/B/C close-out memos byte-identical (zero entries under
  `docs/plans/` outside Plan D's own dir).
- Ruff clean. Sanitization clean.
