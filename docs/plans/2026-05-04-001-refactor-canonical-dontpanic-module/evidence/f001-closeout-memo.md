# F001 close-out memo — 2026-05-04

Plan: `2026-05-04-001-refactor-canonical-dontpanic-module`
Feature: F001 — Flip canonical Python module from `jarvis_orchestrate` to `dontpanic_orchestrate`; legacy package becomes a non-removing compatibility shim with one-shot `DeprecationWarning` per process.

## Direct-path rationale

F001 is a mechanical, deterministic refactor — every test that was green pre-rename must be green post-rename, plus explicit grep + warning assertions for the new boundary. No semantic decisions for an auditor to bikeshed. Volley quota was reserved for Plans B (lifecycle-staged gates) and C (subprocess timeout / envelope durability), where adversarial review actually adds signal. D005 of this plan committed direct-path execution at lock time.

## What landed

Three surfaces flipped, plus one operator-tightening (D003 — historical plan dirs untouched) was preserved verbatim:

| Surface | Change |
|---|---|
| **Implementation tree** | 32 .py files + `executors/` subpackage moved `scripts/jarvis_orchestrate/` → `scripts/dontpanic_orchestrate/`; tests moved with them. Every intra-package import in the canonical tree flipped via `sed`. Existing thin `dontpanic_orchestrate/{__init__,__main__}.py` aliases overwritten. Net diff: 110+ files touched. |
| **Compatibility shim** | New `scripts/jarvis_orchestrate/` containing 36 files (`__init__.py`, `__main__.py`, `_deprecation.py`, 30 top-level submodule re-export files, `executors/{__init__,base,claude_cli,codex_cli}.py`). Total ~1012 lines, ~28 lines/file. Every shim file is identical-shape re-export plumbing — zero business logic. One-shot `DeprecationWarning` per process via the `_warned` flag in `_deprecation.warn_once()`. |
| **Packaging + console scripts + live docs** | `pyproject.toml`: both `dontpanic` and `jarvis` console scripts → `dontpanic_orchestrate.cli:main` per D004; `version` attr + `find.include` order flipped to canonical-first. Live operator-facing docs (README, CONTRIBUTING, 2 SKILL.md files) flipped `jarvis_orchestrate` import examples to canonical; `~/.jarvis/` filesystem-fallback paths preserved (those are Phase A read-fallback, unrelated to module direction). 4 non-package Python files (quota_check.py, sanitization_check.py, jarvis_doctor.py, claude/skills/cost-guard/cost_guard.py) had imports flipped via `sed`. `scripts/jarvis_doctor.py` renamed to `scripts/dontpanic_doctor.py`; old name kept as a thin alias that runpy-executes the canonical script. |

## All 11 acceptance items verified (in this shell, on operator's machine)

| # | AC | Result |
|---|---|---|
| 1 | `from dontpanic_orchestrate import cli` works without warnings | ✓ verified via `python -W error::DeprecationWarning` |
| 2 | `from jarvis_orchestrate import cli` works AND emits exactly 1 `DeprecationWarning` per process | ✓ count=1 confirmed; message points to canonical + plan ID |
| 3 | `which dontpanic` and `which jarvis` both invoke `dontpanic_orchestrate.cli:main` | ✓ both at `$HOME/.pyenv/shims/{dontpanic,jarvis}` after `pip install -e .` |
| 4 | `python -m dontpanic_orchestrate <subcommand>` invokes canonical CLI | ✓ `python -m dontpanic_orchestrate projects list --json` returns valid JSON |
| 5 | Inside `scripts/dontpanic_orchestrate/`, `grep -r 'jarvis_orchestrate' .` returns hits ONLY in `tests/test_legacy_shim_compatibility.py` | ✓ zero hits outside the shim-test file |
| 6 | `scripts/jarvis_orchestrate/` contains only shim plumbing — no business logic | ✓ 36 files × ~28 lines each = ~1012 lines, all `from X import *` + `__getattr__` proxies |
| 7 | Full orchestrate suite (excluding `test_ec5_classifier.py` per plan 003 D011 caveat) passes from canonical path; +N delta = shim-compat test count | ✓ **873 passed, 6 skipped** (baseline 832+6 → +41 net = exactly the 41 new shim-compat tests; **zero regressions**) |
| 8 | Ruff check + format clean across canonical tree + shim files | ✓ "All checks passed" + "116 files already formatted" |
| 9 | `python scripts/sanitization_check.py` reports 0 findings | ✓ 0 findings, 705 files scanned (up from 614 baseline because 36 shim + ~91 plan-A-related files added) |
| 10 | `git diff --name-only HEAD` for this commit shows zero entries under `docs/plans/` (durable records preserved) | ✓ Plan A's own dir (`2026-05-04-001-refactor-canonical-dontpanic-module/`) is the only `docs/plans/` entry — and it's intentional new content, not a rewrite of historical plans. The pre-existing dirty state under other plan dirs is unrelated carryover and excluded from the commit boundary. |
| 11 | **No-shim-relay** — canonical surfaces emit ZERO `DeprecationWarning` from `jarvis_orchestrate` (operator tightening at lock time, D007) | ✓ 3 tests in `TestNoShimRelay` all green: parametric `cli.main(['manifest', 'show', '--json'])` + `cli.main(['projects', 'list', '--json'])` + canonical-module-imports test. Filter is shim-specific (only catches DeprecationWarning whose message contains `jarvis_orchestrate`), so third-party deprecation noise doesn't false-positive. |

## Ripple-effect tally

| Category | Count | Example |
|---|---|---|
| Module files relocated (canonical implementation) | 32 | `scripts/dontpanic_orchestrate/cli.py`, `supervisor.py`, `agent_manifest.py`, etc. |
| Subpackage relocated | 1 | `executors/` (4 files) |
| Test files relocated + import-flipped | 40 | `scripts/dontpanic_orchestrate/tests/test_*.py` |
| Shim files created (top-level) | 33 | `scripts/jarvis_orchestrate/{__init__,__main__,_deprecation,X}.py` |
| Shim files created (executors subpackage) | 4 | `scripts/jarvis_orchestrate/executors/{__init__,base,claude_cli,codex_cli}.py` |
| Non-package Python imports flipped | 4 | `scripts/quota_check.py`, `scripts/sanitization_check.py`, `claude/skills/cost-guard/cost_guard.py`, `scripts/dontpanic_doctor.py` (renamed from jarvis_doctor.py) |
| Doctor file renamed + alias created | 2 | `scripts/dontpanic_doctor.py` (canonical), `scripts/jarvis_doctor.py` (thin alias) |
| Live docs flipped | 4 | `README.md`, `CONTRIBUTING.md`, `claude/skills/revenue-check/SKILL.md`, `claude/skills/cost-guard/SKILL.md` |
| Packaging metadata flipped | 1 | `pyproject.toml` (4 lines: console scripts × 2, version attr, packages.find ordering) |
| Tests added (shim-compat) | 41 | `scripts/dontpanic_orchestrate/tests/test_legacy_shim_compatibility.py` (3 classes × parametric coverage) |
| Test file path corrections (post-rename) | 2 | `test_f022_jarvis_doctor.py` and `test_f003_project_config.py` had `DOCTOR_PATH` updated to canonical |

## Notable subtleties

- **Sed-based import flip is safe inside the canonical tree** because AC #5 asserts the canonical tree has zero `jarvis_orchestrate` references post-flip — the shim-compat test is the only deliberate exception. Outside the canonical tree (`scripts/quota_check.py` etc.), sed was applied per-file with explicit verification.
- **Stale `__pycache__` was cleared three times** during the work — at start (Stage 1), pre-installation (Stage 6), pre-final-suite (Stage 11). F001-of-plan-003 hit the same gotcha post-directory-rename; clearing pycache is now a standard pre-flight step.
- **ec5_classifier purity test still excluded** per plan 003 D011 caveat — this plan does NOT fix that pre-existing breakage (it's Plan D's scope).
- **Initial test sweep had 41 failures** all attributable to two issues: (a) `test_f022_jarvis_doctor.py` and `test_f003_project_config.py` had `DOCTOR_PATH = .../jarvis_doctor.py` which now resolves to the alias instead of the canonical doctor — fixed by pointing at `dontpanic_doctor.py`; (b) the original no-shim-relay test deleted entries from `sys.modules` to force re-imports, which polluted volley_synthetic's module-level state — fixed by switching to non-destructive `record=True` capture with shim-specific message filtering.

## Pointers for the next slice

- **Plan B** (lifecycle-staged gates, volley): the supervisor module is now under `scripts/dontpanic_orchestrate/supervisor.py`. Volley dispatch will work against the canonical name; both `dontpanic dispatch-from-plan` and `python -m dontpanic_orchestrate dispatch-from-plan` invoke the same code path.
- **Plan C** (subprocess timeout / envelope durability, volley): the executor wrappers are under `scripts/dontpanic_orchestrate/executors/` (claude_cli.py + codex_cli.py). The 600s subprocess deadline lives there.
- **Plan D** (EC5 classifier purity, direct): `scripts/dontpanic_orchestrate/ec5_classifier.py` and `scripts/dontpanic_orchestrate/target_context_prelude.py`. The broken test at `scripts/dontpanic_orchestrate/tests/test_ec5_classifier.py` reproduces under the canonical path post-rename.
- **Shim removal** (separately-planned future slice per D006): the shim is non-removing in v1. A future plan with its own deprecation timeline would (a) bump the warning to a louder visibility, (b) audit downstream consumers, (c) drop the shim files + console-script alias + packaging exclusions. Wait for migration evidence before scheduling.
