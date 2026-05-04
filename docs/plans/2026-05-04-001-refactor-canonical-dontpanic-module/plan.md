---
id: 2026-05-04-001-refactor-canonical-dontpanic-module
title: Refactor — Canonical Python module flip (jarvis_orchestrate → dontpanic_orchestrate)
type: refactor
tier: cross-cutting
status: active
date: "2026-05-04"
description: |
  Flip the canonical Python module from `jarvis_orchestrate` to
  `dontpanic_orchestrate`. The implementation moves to the canonical
  name; `jarvis_orchestrate` becomes a thin compatibility shim that
  re-exports from the canonical module and emits a one-shot
  `DeprecationWarning` per process. Console-script entrypoints,
  packaging metadata, and live operator-facing docs flip to the
  canonical name. **Historical plan folders, evidence strings, and
  committed audit envelopes are NOT renamed** — those are durable
  records.

  Single feature, single direct-path landing. The lead slice for
  the four queued platform fixes; merging it first means slices
  #2 (lifecycle-staged gates), #3 (subprocess timeout / envelope
  durability), and #4 (EC5 classifier purity) anchor on the
  canonical module name from day zero.
motivation: |
  After plan 2026-05-03-003 the brand renamed to DontPanic, but the
  canonical Python module is still `jarvis_orchestrate` — the
  `dontpanic_orchestrate/` directory is currently a thin alias that
  re-exports `__version__` and runs `jarvis_orchestrate.cli.main`.
  This is backwards relative to the brand. Every subsequent slice
  that touches imports has to anchor on the legacy name and either
  drag the rename along or get rebased against it later. Flipping
  the direction now is a one-shot mechanical refactor that
  unblocks the queued platform-fix slices.
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
  # Historical plan dirs + evidence + audit envelopes are durable
  # records — explicitly protected from this rename per D003.
  - docs/plans/
  # Operator-curated assets unchanged by this refactor.
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/maintainer/refresh-costs.sh
  # The agent-conventions subtree is upstream — touching it requires
  # a convention bump.
  - claude/shared/
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Single feature, direct-path landing. Three surfaces change:

1. **Implementation moves to `scripts/dontpanic_orchestrate/`** —
   every module file currently under `scripts/jarvis_orchestrate/`
   (excluding `tests/`) is relocated; intra-package imports flip to
   the canonical name. The existing thin `dontpanic_orchestrate/`
   directory is overwritten with the canonical implementation.

2. **`scripts/jarvis_orchestrate/` becomes a compatibility shim** —
   `__init__.py` and per-submodule modules re-export from the
   canonical name. The shim emits `DeprecationWarning` once per
   process via a lazy guard, with a clear message pointing to the
   canonical name. The shim is non-removing in v1; deletion is a
   separate plan with its own timeline.

3. **Packaging + console scripts + live docs flip to canonical** —
   `pyproject.toml` console scripts (`dontpanic`, `jarvis`) both
   point at `dontpanic_orchestrate.cli:main`. `version` attr reads
   from the canonical module. `find.include` lists both packages
   (canonical first). Live operator-facing docs (README,
   ECOSYSTEM.md, PRODUCT.md, ROADMAP.md, CONTRIBUTING.md,
   claude/PORTABILITY.md) flip `jarvis_orchestrate` import
   examples to `dontpanic_orchestrate`; "Jarvis" historical
   context (e.g. "the project was renamed from Jarvis…") stays
   where semantically correct.

## Out of scope (deliberate)

These are durable records or out-of-band concerns and **not**
rewritten by this refactor:

- **Historical plan dirs.** Slugs (`docs/plans/2026-04-XX-001-jarvis-...`),
  evidence file contents, audit envelope JSON, `decisions.jsonl`
  entries all stay byte-identical. The rename changes live import
  surfaces, not audit history. Per the plan-id brand policy
  memory, committed plan IDs and folders are durable identifiers.
- **Memory entries** (`~/.claude/projects/.../memory/*.md`) —
  reference "Jarvis" as a brand-historic. Not touched here.
- **The `jarvis` console-script alias** stays. The console-script
  surface is decoupled from internal module direction (D004): both
  `dontpanic` and `jarvis` resolve to the canonical entrypoint
  after this refactor; nothing about the user-facing CLI changes.
- **The `~/.jarvis/` filesystem fallback** in `global_config.py` —
  Phase A already shipped read-fallback semantics; this refactor
  does not change `DONTPANIC_HOME` / `JARVIS_HOME` precedence.
- **Behavioral changes.** Imports change; behavior does not.
  Pre/post test outcomes should be byte-identical modulo
  deprecation warnings emitted on the legacy shim path.
- **The agent-conventions subtree (`claude/shared/`)** — upstream
  in `agent-conventions` repo; a touch here would require a
  convention version bump and a coordinated subtree pull.
- **Internal documentation that references "Jarvis" as a name.**
  Files that talk *about* the project's history (e.g.
  `feedback_*.md` memories) keep historical references. Only live
  *import-target* docs flip.

## Cross-cutting tightenings (operator-supplied)

Per pre-draft conversation. These constrain the implementer and
are checked by the auditor before pre-merge:

1. **Legacy import compatibility remains.** A consumer that already
   has `from jarvis_orchestrate.cli import main` (or any other
   submodule import) continues to work after this refactor. The
   shim is non-removing in v1 — only a deprecation warning, no
   deletion date. Acceptance assertion: an external smoke step
   imports every public submodule via the legacy name and
   verifies success + a single warning.
2. **Historical plan folders / evidence strings are not renamed.**
   The rename touches *live* import surfaces and *canonical*
   docs. It does NOT rewrite audit history or plan metadata.
   Acceptance assertion: `git diff --name-only` for this commit
   shows zero entries under `docs/plans/`.

## Execution path

**Direct (no volley).** Mechanical sweep with deterministic
acceptance — every test green pre-rename must be green post-rename,
and explicit grep assertions verify canonical direction. No
semantic decisions for an auditor to debate. Volley quota is
reserved for the lifecycle-gates (Plan B) and
subprocess-timeout (Plan C) slices that follow.

## Execution risks

- **Missed call sites in canonical code.** Any `from
  jarvis_orchestrate import X` that survives inside
  `dontpanic_orchestrate/` itself is a defect — the canonical tree
  must be self-referential. Pre-merge sweep greps for the legacy
  name in the canonical tree and asserts zero hits.
- **Stale `__pycache__`.** F001 of plan 003 hit this post-rename
  (the directory rename Jarvis → DontPanic caused INTERNALERROR
  in pytest). Pre-test step clears `find scripts -type d -name
  __pycache__ -exec rm -rf {} +`.
- **Console-script wiring.** `pip install -e .` re-registers the
  console scripts after `pyproject.toml` changes; an in-shell
  verification step ensures `which dontpanic` and `which jarvis`
  both resolve to the canonical entrypoint.
- **Test discovery.** Tests move under
  `scripts/dontpanic_orchestrate/tests/`. `pyproject.toml` /
  `conftest.py` adjustments may be needed if pytest's rootdir
  inference shifts.
- **Subtree-touched files.** `claude/shared/` is a git subtree
  pulled from `agent-conventions`; explicitly excluded from this
  rename per protected_paths.

## Acceptance summary

Binding contract is in `features.json` F001. Highlights:

- Both `from dontpanic_orchestrate import cli` and `from
  jarvis_orchestrate import cli` work; the latter emits a single
  `DeprecationWarning`.
- `which dontpanic` and `which jarvis` both invoke the canonical
  entrypoint.
- `git diff --name-only` shows zero entries under `docs/plans/`.
- Full orchestrate test suite (excluding the pre-existing-broken
  `test_ec5_classifier.py` per plan 003 D011 caveat) passes from
  the canonical path.
- Sanitization clean. Ruff clean.
- Grep assertions: zero `from jarvis_orchestrate` /
  `import jarvis_orchestrate` strings inside
  `scripts/dontpanic_orchestrate/` except inside
  `tests/test_legacy_shim_compatibility.py` (where the shim is the
  unit under test).
- **No-shim-relay (D007 / AC #11):** invoking canonical surfaces
  (`python -m dontpanic_orchestrate manifest show --json`,
  `dontpanic projects list --json`, direct
  `dontpanic_orchestrate.cli.main(...)` calls) emits ZERO
  `DeprecationWarning` from `jarvis_orchestrate`. Verified by a
  pytest case wrapping representative CLI invocations in
  `warnings.catch_warnings()` + `simplefilter('error', DeprecationWarning)`.
  The deprecation signal fires ONLY when consumers explicitly
  import the legacy name.
