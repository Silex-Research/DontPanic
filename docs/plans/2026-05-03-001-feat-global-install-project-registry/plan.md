---
id: 2026-05-03-001-feat-global-install-project-registry
title: Phase A — global install, project registry, doctor integration
type: feat
tier: cross-cutting
status: completed
date: "2026-05-03"
description: |
  Turn Jarvis from a private orchestration repo (operated only by the
  author from inside the source tree) into a globally-installed tool
  that manages many projects from one binary. Three feature surfaces:
  (F001) pipx-installable package + `jarvis` console script + global
  config at `~/.jarvis/`; (F002) `jarvis projects` registry CRUD against
  `~/.jarvis/projects.json`; (F003) per-project `.jarvis/jarvis.json`
  config + `jarvis doctor` integrated for global + per-project preflight.

  Phase A is the foundation every later phase assumes. After Phase A
  ships, every subsequent phase (init, intake, MCP, agent.json) can
  assume a global binary, a project registry, and a per-project config
  file already exist. Phase A does NOT include `jarvis init`
  scaffolding (Phase B), the intake pipeline (Phase C), or the MCP
  server (Phase D).
motivation: |
  Today Jarvis runs only from inside its source tree, requires
  PYTHONPATH=scripts on every invocation, and has no concept of
  multiple registered projects. Every conversation in the recent
  development cycle has hit this friction. Plans 002, 003, 004
  validated the substrate is structurally complete; what's missing is
  the access layer. Phase A is the smallest chunk of that access layer
  that materially changes who can use Jarvis: it makes installation,
  invocation, and multi-project management routine instead of
  PYTHONPATH-prefixed-incantations from inside one repo.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  no_progress_threshold: 2
  wall_clock_hours: 3
  hard_stop: false
privacy_tier: internal
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/maintainer/refresh-costs.sh
  - claude/shared/
dependencies:
  - 2026-04-19-001-infra-cross-agent-orchestration
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  product: ../../PRODUCT.md
  roadmap: ../../ROADMAP.md
---

# Phase A — global install, project registry, doctor integration

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Three features that compose into "Jarvis is now a global tool that
manages many projects."

- **F001 — pipx-installable package + `jarvis` console script + global
  config.** Turn `scripts/jarvis_orchestrate/` into a published
  Python package with `[project.scripts] jarvis = "jarvis_orchestrate.cli:main"`
  in `pyproject.toml`. After `pipx install jarvis-orchestrate`, users
  invoke `jarvis ...` from any cwd. Global config defaults at
  `~/.jarvis/config.json` (default agent pair, default tier, calibration
  pointers).
- **F002 — project registry.** `jarvis projects add | list | show |
  remove` against `~/.jarvis/projects.json`. Each entry: `name`,
  `path`, `created_at`, optional `default_implementer`,
  `default_auditor`, optional `notes`. Non-clobbering: `add` refuses
  if the name already exists; `add --force` overwrites only with
  explicit confirmation.
- **F003 — per-project config + doctor integration.** Each registered
  project gets a `<project>/.jarvis/jarvis.json` (committable, per-
  project) that can override global defaults: implementer / auditor
  agents, declared `human_gates`, declared `protected_paths`, plans
  directory, target_env defaults. `jarvis doctor` (existing tool from
  F022) extended to check global config + per-project config when a
  project is registered: gates registry presence, plans dir presence,
  agent CLI availability, environments.json shape if present.

## Out of scope (deferred to later phases)

- **Project initialization with discovery / inference (`jarvis init`)
  — Phase B.** Phase A's `projects add` registers an existing project;
  it does NOT detect language / test runners / .firebaserc / governance
  docs. That's Phase B.
- **Intake pipeline (`jarvis intake prd|feature|issue|parity`) — Phase
  C.** Phase A does not turn briefs into plans.
- **MCP server (`jarvis mcp serve`) — Phase D.** Phase A is CLI-only.
- **Agent-discovery manifest (`agent.json`) — Phase D.** No
  agent-self-onboarding contract in Phase A.
- **Remote daemon (`jarvis serve` HTTP).** Demand-driven (Phase E or
  later); existing remote-agent surfaces absorb the burden.
- **PRD ingester / plan drafter.** Demand-driven (Phase E+).

## Acceptance (per F001, F002, F003)

See `features.json` for the per-feature acceptance contract. High-level
acceptance for the plan as a whole:

1. From a fresh shell on a fresh user account, `pipx install
   jarvis-orchestrate` (or local `pipx install .` against the source
   tree) produces a working `jarvis` binary on PATH.
2. From any cwd, `jarvis --help` lists the implemented subcommands
   without a `PYTHONPATH=` prefix.
3. `jarvis projects add foo /path/to/foo` writes
   `~/.jarvis/projects.json` and is idempotent on re-add (refuses or
   prompts).
4. `jarvis projects list` and `jarvis projects show foo` round-trip the
   registry without losing fields.
5. `jarvis doctor` reports global config + registered-project config
   health with structured PASS / WARN / FAIL per check, and a non-zero
   exit code when any FAIL.
6. Per-project `.jarvis/jarvis.json` is read by the supervisor at
   dispatch time and overrides global defaults where set.
7. Existing `python -m jarvis_orchestrate <plan>` invocation continues
   to work for backward compatibility (no flag-day break for the
   maintainer's own dogfood plans).
8. All existing tests pass (~580 + 6 skipped baseline; no regression).
   Ruff clean. Sanitization clean.

## Why Phase A first

Per `docs/ROADMAP.md`: every later phase assumes a global binary, a
project registry, and a per-project config exist. Locking Phase A
alone — without bundling B/C/D — means the install + registry surface
gets battle-tested by real friend / OSS-user installation before the
more ambitious phases (intake pipeline, MCP server) lock against it.
This is the same demand-driven discipline the substrate followed.
