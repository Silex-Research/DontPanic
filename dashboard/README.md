# DontPanic Static Dashboard

A local-first kanban + status dashboard for DontPanic state. Reads JSON
files from `dashboard/state/` (or any directory written by
`dontpanic state export-dashboard --out <dir>`).

**No runtime Firebase dependency.** Firebase Hosting is one of three
deployment options; it serves the dashboard as static files, not as a
runtime.

---

## V0 Value-Language Contract (Plan 2026-05-24-001)

The local dashboard is a **value-first operator console**. First-read labels
describe user/business intent; the exact DontPanic substrate (gates,
capabilities, supervisors, plan/feature ids, source files, commands) sits
one layer below in metadata rows, source/provenance footers, and command
chips. The contract is canonical:

- **Copy map:** [`docs/design/dashboard-value-language-ia-v0/copy-map.md`](../docs/design/dashboard-value-language-ia-v0/copy-map.md)
  is the source of truth for V0 first-read labels, the forbidden first-read
  token list, the four-band status taxonomy, the optional relevance chip,
  fleet-mode expectations, and the drag-to-command rule.
- **Static check:** `dashboard/lib/value-language-static-checks.js` plus
  `dashboard/tests/unit/value-language-static-checks.test.js` enforce the
  forbidden first-read tokens against every Layer-1 selector. Add new
  surfaces to the registry there, not by hand-grepping.
- **Visible V0 nav:** Needs Attention (route may be `Home`), Work, Tools &
  Setup (or `Connections`), Health, Preferences. Demo / non-core tabs
  (`Financial`, `Cloud Costs`, adapter-specific views) are hidden or gated.
- **Command-emitter invariant:** the dashboard renders exact CLI commands
  inside `<pre>` / `<code>` blocks the operator can copy and run in their
  own terminal. There is no in-page mutation, no inline approve/reject,
  no embedded executor, no Firebase realtime write. Drag affordances are
  command-preview only (D010 in
  [`decisions.jsonl`](../docs/plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/decisions.jsonl)).
- **Fleet mode:** Needs Attention, Work, and Health each render an
  `All Projects` variant from `dashboard/state/fleet-what-now.json` and
  `dashboard/state/fleet-summary.json`. Project filtering pins the
  `__global__` reconcile/doctor band so cross-project blockers stay
  visible (D013).
- **Provenance:** every page footer renders `Source: …`, `Last updated:
  …`, and the refresh command (`dontpanic dashboard build`) via
  `dashboard/lib/provenance.js`. New pages MUST go through that helper.

### Future surfaces (non-goals for V0)

These are explicit non-goals for V0 and are deferred to future child
plans. When those plans land they MUST inherit the value-language
contract above — first-read labels in business terms, exact substrate
disclosed in metadata, no in-page mutation, value-language static check
extended to cover the new Layer-1 selectors:

| Surface | V0 disposition | Future plan reference |
|---|---|---|
| Architecture Explorer | muted future nav affordance only (D014); page is not implemented in V0 | `docs/design/dashboard-architecture-explorer-v1/` |
| Review / Evidence | not in V0 nav; auditor signoffs live on disk under `docs/plans/<plan>/audit/` | tracked by parent roadmap `2026-05-24-003` |
| Configuration editor | not in V0; Preferences is browser-local only — DontPanic config still edits via `dontpanic` CLI surfaced in Tools & Setup | tracked by parent roadmap `2026-05-24-003` |
| Agent Session Registry | not in V0; `dontpanic ps` remains the supervisor inspection seam | tracked by parent roadmap `2026-05-24-003` |
| Local executor / inline approve | non-goal — the command-emitter invariant is permanent | (no plan; would require a roadmap-level lock) |

Each future plan MUST:

1. Reference the copy map and add its surface's first-read labels to it
   before implementation begins.
2. Add the new surface's Layer-1 selectors to
   `dashboard/lib/value-language-static-checks.js` so the forbidden-token
   scan covers it.
3. Reuse `dashboard/lib/provenance.js` for source/last-updated/refresh
   command rendering.
4. Reuse the four-band status taxonomy
   (`needs_action`/`advisory`/`ready`/`quiet`) and the optional
   relevance chip; no new health bands.
5. Honor fleet mode by routing through the existing `project-selector`
   logic so `All Projects` and project-filtered views remain coherent.

The Claude Design v3 pack referenced in
[`docs/design/dashboard-value-language-ia-v0/claude-design-v3-manifest.md`](../docs/design/dashboard-value-language-ia-v0/claude-design-v3-manifest.md)
is visual specification and design-token input only. Treat the JSX as a
mockup; the shipped dashboard stays vanilla HTML/CSS/JS (D012).

---

## V0 Operator Console (Plan 2026-05-23-004)

For the operator-in-the-loop "what needs action now?" view, use the
bundled CLI rather than the legacy export-dashboard incantation. The
console is local-first, requires no Firebase, and writes an
agent-readable cache alongside the rendered dashboard:

```bash
# One-shot build (export + cache + render)
dontpanic dashboard build

# Build, print local path/URL, best-effort GUI launch
dontpanic dashboard open

# Localhost-only HTTP server with file-watch refresh
dontpanic dashboard serve
```

`serve` binds `127.0.0.1` by default and refuses non-loopback hosts
unless the operator passes `--allow-remote`. The watch loop polls
plan/dashboard sources on a 2s interval and rebuilds without a manual
restart.

Each invocation also writes the operator-readable what-now cache to
`~/.dontpanic/dashboard/what-now.json` (or `$DONTPANIC_HOME` if set).
The same `ActionItem` envelope powers the dashboard, MCP, and any
headless agent — see `scripts/dontpanic_orchestrate/operator_console.py`
for the schema.

`dontpanic doctor` reports dashboard readiness (`dashboard-files`,
`dashboard-cache`, `dashboard-state`) as advisory checks with exact
remediation commands. `dontpanic init` prints the dashboard hand-off
line after a successful walk.

---

## Three deployment shapes

### 1. Local-only (`python -m http.server`)

For per-operator review, a contractor running off a laptop, or a
sandboxed CI runner.

```bash
dontpanic state export-dashboard --out dashboard/state
cd dashboard
python -m http.server 8000
# open http://localhost:8000
```

Or any equivalent: `file://` (some pages may not work with strict CORS),
`npx serve`, `bun --hot`, `caddy file-server`, etc.

### 2. Firebase Hosting (optional)

For team viewing without exposing the operator's laptop. **Firebase is
optional** — the dashboard is just static HTML/CSS/JS. Firebase Hosting
is a CDN; the dashboard does not call any Firebase runtime API.

```bash
dontpanic state export-dashboard --out dashboard/state
firebase deploy --only hosting
```

Requires a `firebase.json` with a `hosting.public` pointing at
`dashboard/`. The bundled `firebase.json` in this repo already wires
this for the platform's own dashboard.

### 3. Any other static host

GitHub Pages, nginx, Vercel static, Netlify, S3 + CloudFront — anything
that serves files. Run the export, point the host at `dashboard/`, done.

---

## What `dontpanic state export-dashboard` writes

The export drops the following files into the named `--out <dir>`:

| File | Content |
|---|---|
| `state-snapshot.json` | Full F001 envelope (`schema_version`, `captured_at`, `redact_level`, 7 streams). The canonical adapter input. |
| `plans.json` | Just the `plans` stream as a JSON array. |
| `gates.json` | Just the `gates` stream. |
| `inbox.json` | Just the `inbox` stream. |
| `supervisors.json` | Just the `supervisors` stream. |
| `quota.json` | Just the `quota` stream. |
| `decisions.json` | Just the `decisions` stream. |
| `evidence_refs.json` | Just the `evidence_refs` stream. |
| `manifest.json` | Index of the directory: schema_version, captured_at, redact_level, per-stream filename + count. |

Single-stream files are a convenience for dashboard pages that render
one stream and don't want to parse the whole envelope; the canonical
contract for adapters is `state-snapshot.json` + the
`state-snapshot.schema.json` schema.

---

## Legacy state files vs. F001 projection

The pre-existing `dashboard/state/*.json` files (`agents.json`,
`tasks.json`, `activity.json`, `costs.json`, `security.json`,
`settings.json`) were hand-shaped for the legacy dashboard before plan
2026-05-09-003 introduced the F001 state-snapshot envelope.

Those legacy files are **not** what `export-dashboard` writes today.
`export-dashboard` writes the F001 stream shape; the legacy pages may
not render against it without a small adapter shim in
`dashboard/lib/*-logic.js`.

This is a deliberate scope cut for F007 — see
[`docs/STATE_PROJECTION.md`](../docs/STATE_PROJECTION.md) for the
adapter governance contract and plan 2026-05-09-003 features.json F007
acceptance refinement (D016) for the boundary rationale. A follow-up
plan can add a "view adapter" layer that maps F001 streams to the
legacy page shapes, but the projection contract stays canonical.

---

## Adapter authors: pin the schema

Every dashboard page consuming `state-snapshot.json` MUST pin the
schema version it was written against:

```javascript
const SUPPORTED_VERSION = "1.0";
fetch("state-snapshot.json")
  .then((r) => r.json())
  .then((snap) => {
    if (snap.schema_version !== SUPPORTED_VERSION) {
      throw new Error(
        `dashboard pinned to ${SUPPORTED_VERSION}, ` +
        `state-snapshot.json is ${snap.schema_version}`
      );
    }
    // ... render
  });
```

See [`docs/STATE_PROJECTION.md`](../docs/STATE_PROJECTION.md) for the
full four-invariant contract every adapter must follow.
