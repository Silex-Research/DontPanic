# F001 close-out memo — 2026-05-02

Plan: `2026-05-03-001-feat-global-install-project-registry`
Feature: F001 — pipx-installable global tool, console-script entry, global config helpers, --version flag, backward-compat path.

## Direct-path rationale

F001 is a packaging / config / bootstrap slice with deterministic acceptance and no behavioral risk to the supervisor. The substrate-discipline rule (D012 of plan 003) — "defer next-version plans until a real-world signal arrives" — does not apply here: this is the platform mechanics that make the *real-world signal* possible in the first place. Direct path was authorized by the operator at plan-lock time:

> Start Phase A F001 directly. This is a packaging/config/bootstrap slice with deterministic acceptance, and we already decided direct is appropriate for small mechanical platform work when the risk is low and tests are clear.

## What landed (scope as shipped)

1. **PEP 621 packaging**: `pyproject.toml` extended with `[build-system]` (setuptools), `[project]` (name=`jarvis-orchestrate`, requires-python `>=3.10`, dynamic version, runtime deps `pydantic>=2.0`, `pyyaml>=6.0`, optional `firebase` and `dev` extras), `[project.scripts]` (`jarvis = "jarvis_orchestrate.cli:main"`), `[project.urls]`, `[tool.setuptools.dynamic]` reading version from `jarvis_orchestrate.__version__` (single source of truth), and `[tool.setuptools.packages.find]` rooted at `scripts/` with `jarvis_orchestrate*` include and `jarvis_orchestrate.tests*` exclude (tests are not shipped in the wheel).
2. **`__version__` single source of truth**: `scripts/jarvis_orchestrate/__init__.py` exposes `__version__ = "0.1.0"`. Pyproject's dynamic-version resolution and the CLI's `--version` flag both read the same attribute — there is no second copy that can drift.
3. **`jarvis --version` / `-V`**: handled at the top of `cli.main()` before any subcommand resolution. Prints `jarvis {__version__}` and returns 0. Works from any cwd.
4. **Backward compat for `python -m jarvis_orchestrate`**: the existing `__main__.py` continues to route through `cli.main()` unchanged. Verified by a subprocess-based test (`test_version_via_module_invoke`) so the path is exercised end-to-end, not just by import.
5. **Global config module** (`scripts/jarvis_orchestrate/global_config.py`): `GlobalConfig` Pydantic v2 model (`extra='forbid'`) with optional `default_implementer` / `default_auditor` / `default_tier` / `calibration_path`. `jarvis_home()` honors the `JARVIS_HOME` env override (test isolation + power-user use) and falls back to `~/.jarvis`. `load_config()` is total: missing-file → empty config (no warning, this is the first-run zero state); invalid JSON / OSError → WARN + empty; schema-violation (extra field) → WARN + empty. Never raises. `save_config()` writes JSON with `exclude_none` so the on-disk file mirrors only the fields the user chose to set. `merge_with_defaults()` resolves to the hardcoded fallbacks (`implementer='claude'`, `auditor='codex'`) when the corresponding fields are unset.
6. **Tests** (`scripts/jarvis_orchestrate/tests/test_f001_packaging_and_global_config.py`, 27 tests across 7 classes):
   - `TestPyproject` — PEP 621 shape, console-script entry, runtime deps, dynamic version, packages.find layout, build-system.
   - `TestVersion` — `__version__` resolves with PEP 440-shaped value, `--version` long form, `-V` short form, `python -m jarvis_orchestrate --version` subprocess test.
   - `TestJarvisHome` — env override, default to `~/.jarvis` when env unset, idempotent `ensure_jarvis_home`.
   - `TestLoadConfig` — missing → empty, valid → populates, invalid JSON → WARN + empty, extra field → WARN + empty, OSError → no raise.
   - `TestSaveConfig` — round-trip, exclude_none, creates dir if missing.
   - `TestMergeWithDefaults` — empty uses fallbacks, populated overrides, partial mixes.
   - `TestNoRepoSpecificAssumptions` — global config + `--version` work from arbitrary cwd; `JARVIS_HOME` can point anywhere.

   All tests use an autouse fixture (`_isolate_jarvis_home`) that redirects `$JARVIS_HOME` to `tmp_path / .jarvis` so the user's real `~/.jarvis` is never read or written.

## Verification

- `PYTHONPATH=scripts python -m pytest scripts/jarvis_orchestrate/tests/test_f001_packaging_and_global_config.py -v` — **27 passed in 0.31s**.
- `PYTHONPATH=scripts python -m pytest scripts/jarvis_orchestrate/tests/` (full orchestrate suite) — **607 passed, 6 skipped in 29.39s**. Baseline before F001 was ~580 passed + 6 skipped; the +27 delta accounts for the new F001 tests with no regressions.
- `ruff check` on `pyproject.toml`, `__init__.py`, `global_config.py`, `cli.py`, `tests/test_f001_packaging_and_global_config.py` — **All checks passed**.
- `python scripts/sanitization_check.py` — **0 findings, 573 files scanned**.
- Manual `python -m jarvis_orchestrate --version` (working tree, `PYTHONPATH=scripts`) prints `jarvis 0.1.0`.

## Scope cut (recorded as D007)

The original `features.json` F001 entry listed steps and acceptance items that go beyond what shipped:

| Original item | Status |
| --- | --- |
| `pyproject.toml` PEP 621 + console script + dynamic version | ✅ shipped |
| `~/.jarvis/config.json` loader (missing/invalid/valid) | ✅ shipped |
| `python -m jarvis_orchestrate` backward compat | ✅ shipped |
| `--version` flag | ✅ shipped (out of scope on the original list, but in the operator's narrowed scope; it ships) |
| Tests proving no repo-specific assumptions | ✅ shipped |
| `pipx install .` smoke verification (acceptance #2) | ⏸ deferred — operator-side gate at F002 close-out |
| `pip install -e .` developer-mode smoke (acceptance #3) | ⏸ deferred — operator-side gate at F002 close-out |
| Wire global config into supervisor `dispatch_volley` / `dispatch_single_agent` / `_approve_main` / `_resume_main` (step 4 / acceptance #5) | ⏸ deferred to F003 — same code paths get touched there for per-project override precedence (D004), so wiring twice is wasteful |
| README quickstart rewrite to lead with `pipx install jarvis-orchestrate` (step 5 / acceptance #7) | ⏸ deferred to F002 — README quickstart needs the project-add UX from F002 to show the canonical end-to-end flow |

The narrower scope was authorized by the operator:

> Keep F001 scoped to: package metadata / console entry point, `jarvis --version`, backward compatibility for `python -m jarvis_orchestrate`, global config path `~/.jarvis/config.json`, config read/write helpers if needed, tests proving no repo-specific assumptions. Do not implement project registry or per-project config yet; those are F002/F003.

D007 records this scope cut so the F002 / F003 close-outs know they own the deferred items. The features.json acceptance list is left intact but the deferred items are explicitly called out as cross-feature responsibilities; F001 is signed off on what shipped, not on the original full list.

## Why these particular cuts (not others)

- **Supervisor wiring → F003.** F003 is where per-project `.jarvis/jarvis.json` lands, and per-project values are designed to override global values per D004. Wiring global-config lookups into the supervisor in F001 would mean re-touching the same call sites in F003 to layer the per-project read on top, which is churn. F003 will do it once with the full precedence chain in place.
- **README rewrite → F002.** A `pipx install jarvis-orchestrate` quickstart that doesn't show how to register a project is the wrong shape for the README's "five-minute quickstart" promise. The pipx install + `jarvis projects add` pair is the canonical onboarding flow; F002 is the natural place to write it.
- **`pipx install .` smoke → F002.** This is a manual operator gate, not a test-surface item. Folding it into F002's close-out is honest: F001 can pass automated tests without anyone running pipx end-to-end, and we should not pretend the wheel-install path is verified just because pyproject parses.

## Files changed in F001

- `pyproject.toml` — added `[build-system]`, `[project]`, `[project.optional-dependencies]`, `[project.scripts]`, `[project.urls]`, `[tool.setuptools.dynamic]`, `[tool.setuptools.packages.find]`. Existing `[tool.ruff]` block left intact.
- `scripts/jarvis_orchestrate/__init__.py` — added `__version__ = "0.1.0"` plus a docstring documenting it as the single source of truth.
- `scripts/jarvis_orchestrate/global_config.py` — new module.
- `scripts/jarvis_orchestrate/cli.py` — `--version` / `-V` handling at the top of `main()`. No other behavioral change.
- `scripts/jarvis_orchestrate/tests/test_f001_packaging_and_global_config.py` — new test module.

## Pointers for F002 close-out

When closing F002, verify:

1. `pipx install .` from a fresh shell (or the source tree) places a `jarvis` executable on PATH; `which jarvis` resolves to the pipx-managed binary.
2. `jarvis --version` from any cwd post-install prints `jarvis {__version__}` (no `PYTHONPATH=scripts` needed).
3. `jarvis ps` and any other already-shipped subcommand runs from any cwd post-install.
4. README quickstart leads with `pipx install jarvis-orchestrate` (or `pipx install .` in the source-tree case) and the new `jarvis projects add` workflow. `PYTHONPATH=scripts` removed from primary instructions.

## Pointers for F003 close-out

When closing F003, verify:

1. Override precedence at dispatch time matches D004: per-project `<project>/.jarvis/jarvis.json` > global `~/.jarvis/config.json` > hardcoded fallbacks (`implementer='claude'`, `auditor='codex'`).
2. `supervisor.dispatch_volley` and `supervisor.dispatch_single_agent` consult the precedence chain when no explicit override is passed via CLI args.
3. `cli._approve_main` / `cli._resume_main` similarly resolve through the precedence chain when they need to know which agent owns the gate.
4. Parametric test covers per-project-only, global-only, both-set (per-project wins), neither-set (fallback wins) cases.
