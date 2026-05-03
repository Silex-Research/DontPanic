# F002 close-out memo — 2026-05-02

Plan: `2026-05-03-001-feat-global-install-project-registry`
Feature: F002 — project registry CRUD (`jarvis projects add | list | show | remove`).

## Direct-path rationale

F002 is a self-contained CRUD slice with deterministic acceptance: a Pydantic schema, a single new module, four CLI subcommands, no supervisor wiring, no behavioral changes to the dispatch path. The operator's read at planning time:

> F002 (project registry CRUD) is a self-contained module — Pydantic schema + CRUD helpers + CLI handlers + tests, modeled on F001's pattern. Acceptance is deterministic and a volley would mostly bikeshed CLI ergonomics.

The risk surface is footguns around `--force` semantics, JSON on-disk shape, and CLI ergonomics — all of which are pinned down by tests. Volley would have spent its budget on style and surface preferences rather than catching bugs that escape the test suite. F003 (which threads override precedence into hot supervisor call sites) is where adversarial review actually earns its keep, and that is the next slice.

## What landed (scope as shipped)

1. **Pydantic schema** (`scripts/jarvis_orchestrate/projects_registry.py`):
   - `ProjectEntry` with `model_config = ConfigDict(extra="forbid")` and a `name` field-validator enforcing the D003 regex `^[a-z0-9][a-z0-9-]{0,63}$`.
   - `Registry` wrapping `projects: list[ProjectEntry]` (also `extra='forbid'`).
   - Optional fields (`last_used_at`, `default_implementer`, `default_auditor`, `notes`) default to `None` and round-trip without coercion.

2. **CRUD helpers**:
   - `load_registry()` — total: missing → empty, invalid JSON / OSError → WARN + empty, schema-violation → WARN + empty. Mirrors F001's `load_config` semantics so a stale file from an older Jarvis cannot break a newer one.
   - `save_registry(reg)` — `exclude_none` so the on-disk file mirrors only fields the operator chose to set; whole-second ISO-8601 UTC timestamps for diff-friendliness (D008.3).
   - `add_project(name, path, *, force=False, ...)` — refuses on bad-shape name (Pydantic validator), refuses on non-existent path, refuses on collision unless `force=True`. Path is normalized to absolute via `Path.expanduser().resolve()` before persisting.
   - `remove_project(name)` — returns the removed entry or `None`.
   - `find_project(name)` — returns the entry or `None` (callers decide whether absence is an error).
   - `update_last_used(name)` — stamps `last_used_at` to now (UTC, second precision); raises `ProjectsRegistryError` for unknown name. Idempotent within the same second.

3. **CLI subcommands** (in `scripts/jarvis_orchestrate/cli.py`):
   - `jarvis projects add <name> <path> [--force --yes] [--implementer X] [--auditor Y] [--notes ...] [--json]`.
   - `jarvis projects list [--json]` — tabular default, structured JSON with `--json`.
   - `jarvis projects show <name> [--json]` — refuses missing name with exit 2.
   - `jarvis projects remove <name> [--yes] [--json]` — dry-run preview by default; `--yes` actually deletes; refuses missing name with exit 2.
   - All four accept `--json` (D008.2). `--force` requires `--yes` for non-interactive use (D008.1, no TTY prompts).
   - Wired into `main()` after the `quota-caps` branch.

4. **Test isolation**: autouse fixture redirects `$JARVIS_HOME` to `tmp_path / .jarvis` — the user's real `~/.jarvis/projects.json` is never read or written by the test suite.

5. **Tests** (`scripts/jarvis_orchestrate/tests/test_f002_projects_registry.py`, 52 tests across 9 classes):
   - `TestSchema` — D003 regex (parametrized happy + 7 bad-name cases), `extra='forbid'` on entry + registry, empty registry as zero state.
   - `TestLoadSave` — missing → empty, round-trip, invalid JSON → WARN + empty, extra field → WARN + empty, dir creation, `exclude_none`.
   - `TestAddProject` — persists, `~` expansion via `$HOME`, collision refuses, force overwrites, invalid name raises, non-existent path refuses, optional fields persist.
   - `TestFindAndUpdate` — find existing/missing, `update_last_used` sets field + idempotent within same second + raises on unknown name.
   - `TestRemoveProject` — existing returns entry, missing returns `None`.
   - `TestProjectsCLIAdd` — basic, collision exit 2, `--force` without `--yes` refuses, `--force --yes` overwrites, invalid name exit 2, non-existent path exit 2, optional flags persist, `--json` shape.
   - `TestProjectsCLIList` — empty + populated + `--json` round-trip.
   - `TestProjectsCLIShow` — existing + missing exit 2 + `--json` round-trip.
   - `TestProjectsCLIRemove` — dry-run default + `--yes` deletes + missing exit 2 + `--json` shape.
   - `TestProjectsCLIDispatch` — no-subcommand prints usage, unknown subcommand exit 2, works from arbitrary cwd.

## Verification

- `PYTHONPATH=scripts python -m pytest scripts/jarvis_orchestrate/tests/test_f002_projects_registry.py -v` — **52 passed in 0.30s**.
- `PYTHONPATH=scripts python -m pytest scripts/jarvis_orchestrate/tests/` (full orchestrate suite) — **659 passed, 6 skipped in 34.70s**. Baseline before F002 was 607 + 6 skipped; the +52 delta accounts for the new F002 tests with no regressions.
- `ruff check` on `projects_registry.py`, `cli.py`, `tests/test_f002_projects_registry.py` — **All checks passed** (after tightening `pytest.raises(Exception)` to `pytest.raises(ValueError)` per B017 — Pydantic v2's `ValidationError` inherits from `ValueError`).
- `python scripts/sanitization_check.py` — **0 findings, 576 files scanned**.
- `features.json` validates against agent-conventions v1.0 Pydantic schema after the flip.

## What was NOT touched (deliberately)

Per the operator's split:

> Do F002 direct: project registry schema, CRUD helpers, CLI handlers, deterministic tests, no supervisor dispatch behavior.

- `supervisor.dispatch_volley` — unchanged. The registry is consulted at dispatch time by F003 once the per-project override precedence chain lands (D004).
- `supervisor.dispatch_single_agent` — unchanged.
- `cli._approve_main` / `cli._resume_main` — unchanged.
- `plan_loader.load` — unchanged. The per-project `plans_dir` override is F003's concern.
- README quickstart — still on `python -m jarvis_orchestrate`. The pipx-led quickstart (F001's deferred item) has a natural home in F002+F003 close-out, but per scope discipline was not added in this slice — it depends on F003's `jarvis doctor` integration to give the quickstart a real verification step.

## Pointers for F003 close-out

When closing F003 (volley), verify:

1. Override precedence at dispatch time matches D004: per-project `<project>/.jarvis/jarvis.json` > global `~/.jarvis/config.json` > hardcoded fallbacks (`implementer='claude'`, `auditor='codex'`).
2. `supervisor.dispatch_volley` and `supervisor.dispatch_single_agent` consult the precedence chain when no explicit override is passed via CLI args.
3. `cli._approve_main` / `cli._resume_main` similarly resolve through the precedence chain when they need to know which agent owns the gate.
4. `plan_loader.load` accepts a per-project `plans_dir` override.
5. `jarvis doctor` (new subcommand wrapping `scripts/jarvis_doctor.py`) preflights global + per-registered-project config: path exists, jarvis.json parses, declared agents recognized, declared gates valid.
6. `update_last_used(<project_name>)` is called from the supervisor when a dispatch resolves a registered project (so `jarvis projects list` shows real recency).

## F003 volley audit prompt focus areas

When dispatching the F003 volley, the auditor prompt should explicitly call out:

- **Look for missed call sites.** The override-resolution helper must be threaded into every code path that today reads `agents_required[0]` / `agents_required[1]` or hardcodes `'claude'` / `'codex'` — not just the obvious ones in `dispatch_volley`. Grep `supervisor.py` and `cli.py` for both shapes.
- **Look for wrong precedence.** Per-project must win over global must win over fallback. A bug where global wins when both are set is a silent drift bug — the test must cover all four cells of (per-project set/unset × global set/unset).
- **Look for unsafe fallback to cwd.** Resolving a project's `path` should not default to `Path.cwd()` anywhere — that's how Jarvis ends up operating on the wrong repo. Project resolution must come from the registry (F002), and a missing/unregistered project name is a hard refusal, not a silent cwd fallback.
- **Look for project-name / path confusion.** The CLI takes both shapes (`jarvis dispatch myproject` vs `jarvis dispatch /abs/path/to/proj`). The override-resolution helper must not accidentally treat a project name as a path or vice versa.
- **Look for tests that only cover happy path.** Override precedence has missing-vs-explicit-null edge cases (per-project sets `default_implementer: null` in JSON — does that mean "no override, fall through to global" or "explicit override to None"?). The volley should refuse to sign off until the auditor sees a parametric test covering the matrix, not just one happy path.
