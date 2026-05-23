# Dashboard Project Selector

DontPanic ships one local operator dashboard per install. A single user can
operate many repos, apps, and platforms (mobile app, backend, schema repo,
DontPanic itself) from that one dashboard. This page documents how the
multi-repo dashboard works, how to register projects, and what the security
boundary is.

This page is the operator-facing surface for plan
`2026-05-23-005-feat-dashboard-project-selector-v0` (substrate in F001,
CLI selection in F002, selector UI in F003, fleet/project What Now in F004).

---

## One Global Dashboard, Many Registered Projects

The dashboard lives in the operator's home directory, not in any target repo.
Every generated artifact is written under `~/.dontpanic/` (or
`$DONTPANIC_HOME` / legacy `$JARVIS_HOME`), never into a registered project
checkout. Target repos receive no dashboard files by default; running
`dontpanic dashboard build --project myapp` does not modify the `myapp`
working tree.

This is intentional:

- a single install can answer "what needs action now?" across every project
- registering a repo never edits files in that repo
- removing a project from the registry never touches the target repo
- generated state is operator-local and can be regenerated from the registry

Single-repo mode is preserved unchanged: with an empty registry, the
dashboard falls back to building from `<cwd>/docs/plans` against
`<cwd>/dashboard/state` exactly as it did before this plan.

---

## Cache Layout

```text
~/.dontpanic/
├── projects.json                          # registry (source of truth)
└── dashboard/
    ├── fleet-summary.json                 # All Projects rollup
    ├── fleet-what-now.json                # Fleet-level ActionItem aggregate
    └── projects/
        └── <project-name>/
            ├── state-snapshot.json
            ├── what-now.json
            ├── capabilities-required.json
            ├── architecture-status.json
            └── build-warnings.json
```

`<project-name>` is the stable identity from `ProjectEntry.name` (DNS-label
shape, ≤64 chars). Mutable fields like `path` or `display_name` may change
without invalidating the cache directory.

The dashboard's served-state directory (`<dashboard>/state`) mirrors the
selected project's cache plus `fleet-summary.json` and `fleet-what-now.json`
so the HTML shell has everything it needs to render the selector and
project-scoped views without crossing process boundaries.

---

## Registering a Project

Use the same registry shipped by plan 2026-05-03-001 — there is no second
registry for the dashboard. Project names are stable identities; paths are
mutable.

```bash
# Register a project (path must exist; name must match ^[a-z0-9][a-z0-9-]{0,63}$)
dontpanic projects add spindine /absolute/path/to/spindine

# Optional: scaffold a per-project config file at the same time
dontpanic projects add backend /absolute/path/to/backend --init-config

# Inspect the registry
dontpanic projects list
dontpanic projects show spindine

# Remove (dry-run by default; --yes to apply)
dontpanic projects remove spindine --yes
```

The registry file (`~/.dontpanic/projects.json`) stores names, absolute
paths, timestamps, default agent role names, free-form notes, and optional
dashboard fields (`display_name`, `profile`, `active`, `dontpanic_version`).
Older registry files without the optional fields keep loading unchanged.

`dontpanic doctor` reports the registry's project count as a non-blocking
`PASS` line; an empty registry prints a hint to run `dontpanic projects add`
but does not block any doctor profile. Single-repo users never need to touch
the registry.

---

## Building and Serving the Dashboard

```bash
# Build the fleet (every registered project + fleet summary)
dontpanic dashboard build --project all

# Build one project
dontpanic dashboard build --project spindine

# Serve (loopback-only). Default --project resolution is described below.
dontpanic dashboard serve
dontpanic dashboard serve --project spindine
dontpanic dashboard serve --project all
```

`--project` accepts either `all` or a registered project name. Unknown names
fail loud with the list of known names and the exact `dontpanic projects
add <name> <path>` shape needed to register the missing one.

### Default `--project` resolution

When `--project` is omitted:

| Registry state                        | Default              |
|---------------------------------------|----------------------|
| empty                                 | current-repo mode    |
| cwd is inside a registered project    | that project (cwd-match) |
| exactly one project registered        | that one project     |
| multiple projects, cwd not inside any | `all` (fleet)        |

The cwd-match wins over the multi-project default so an operator working
inside `spindine/` sees `spindine` even when other projects are registered.
The selector UI surfaces *why* a project was selected (cwd match, explicit
flag, only project, default).

### Server refresh on registry changes

`dashboard serve` fingerprints `~/.dontpanic/projects.json` alongside its
other source files. Running `dontpanic projects add|remove` while a server
is running triggers a rebuild on the next poll cycle (default 2 s), so the
selector picks up new projects without restarting the server.

---

## Scope Labels

Every visible surface declares its scope so operators know what data they
are looking at.

| Label              | What it covers                                                      |
|--------------------|----------------------------------------------------------------------|
| `Scope: Global`    | DontPanic install configuration, doctor blockers, capability install state |
| `Scope: Project`   | Plans, gates, architecture, evidence, build warnings for one project |
| `Scope: Fleet`     | Cross-project summaries: grouped What Now actions, project health rollup |

Global blockers (capability not installed, doctor blocker, install drift,
adapter not configured) follow the F004 relevance rules so a backend
project's view does not show capability blockers that only matter to the
mobile project. See `scripts/dontpanic_orchestrate/dashboard_relevance.py`
for the typed relevance table.

When a single project is selected, the dashboard shows global blockers only
when they are relevant to that project. When All Projects is selected, the
fleet view groups actions by project section header (ordered by worst
health band, then project name) and shows global blockers once at the top.

---

## Add Project from the UI

The selector's "Add project" option does not mutate the registry. It emits
the exact command shape (`dontpanic projects add <name> <path>`) for the
operator to run in a terminal. This preserves the command-emitter invariant:
the dashboard is a projection of governed state, not a control plane.

A missing fleet summary cache surfaces the same way — the UI prints
`run dontpanic dashboard build --project all` and waits for the operator
to act. Selecting a project that is missing from the fleet summary prints
the exact `dontpanic projects add <name> <path>` shape and does not retry
silently.

---

## Selection Persistence

The selected project lives in the URL query string (`?project=<name>` or
`?project=all`) as the primary store and falls back to `localStorage` when
the operator opens the dashboard without a query string. Neither
persistence layer mutates the project registry; clearing browser storage
returns the operator to the default resolution above.

---

## Security Posture

The multi-repo dashboard inherits the same boundary as the single-repo
operator console.

- **Local-only server.** `dashboard serve` binds `127.0.0.1` by default.
  `--allow-remote` exists for explicit operator opt-in and is never set
  automatically.
- **Command emitter, not a control plane.** Add Project, missing fleet
  summary, missing project, and stale cache states all emit shell commands
  for the operator to run. The browser never writes to `projects.json` or
  to any plan-state file.
- **No secret values in cache or UI.** Every JSON write goes through the
  operator-console no-secret assertion shared with the single-repo build.
  Cache files, fleet summary, build warnings, and ActionItem payloads are
  expected to contain only identifiers and metadata.
- **No Firebase requirement.** Multi-repo operation works against a local
  registry and local cache. Firebase realtime, remote approve/dispatch, and
  hosted control planes are explicitly out of scope for V0.
- **Registered projects are read-only inputs.** In registered project and
  fleet mode, dashboard state is written under `global_config.dontpanic_home()`
  and target repos are read-only inputs. The legacy unregistered
  current-repo fallback still writes `dashboard/state/` in the current repo;
  use registered mode when you need the no-target-write boundary.
- **Project names are DNS-label shape.** `^[a-z0-9][a-z0-9-]{0,63}$` —
  paths are normalized to absolute at add time, and a non-directory path
  refuses with a clear error before anything lands on disk.

---

## Working Across Repos

A typical multi-project session:

```bash
# One-time registration of each project
dontpanic projects add spindine /abs/path/to/spindine
dontpanic projects add backend /abs/path/to/backend
dontpanic projects add dontpanic /abs/path/to/DontPanic

# Build everything (fleet view + per-project caches)
dontpanic dashboard build --project all

# Serve and operate. Cwd-match resolves the project automatically.
cd /abs/path/to/spindine
dontpanic dashboard serve              # selects spindine by cwd match
cd ~
dontpanic dashboard serve              # selects All Projects (multi-project)
dontpanic dashboard serve --project backend  # explicit selection

# When inside an unregistered repo, single-repo mode still works
cd /tmp/sandbox-repo
dontpanic dashboard build              # falls back to cwd/docs/plans
```

Agents reading the cache directly should consume `fleet-summary.json` and
`projects/<name>/what-now.json` rather than scraping HTML. The JSON envelope
carries a `schema_version` field; refuse cache files whose schema_version
the consumer does not understand rather than rendering them.

---

## Where to Look in Code

- Registry CRUD: `scripts/dontpanic_orchestrate/projects_registry.py`
- ProjectContext projection + per-project build + fleet summary:
  `scripts/dontpanic_orchestrate/projects_dashboard.py`
- CLI selection + `--project` flag + serve watcher:
  `scripts/dontpanic_orchestrate/dashboard.py`
- Typed global-blocker relevance: `scripts/dontpanic_orchestrate/dashboard_relevance.py`
- Selector UI logic: `dashboard/lib/project-selector-logic.js`
- Fleet/project What Now: `dashboard/lib/what-now-logic.js`
- Selector shell wiring: `dashboard/core.js`
