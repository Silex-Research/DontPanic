# DontPanic Static Dashboard

A local-first kanban + status dashboard for DontPanic state. Reads JSON
files from `dashboard/state/` (or any directory written by
`dontpanic state export-dashboard --out <dir>`).

**No runtime Firebase dependency.** Firebase Hosting is one of three
deployment options; it serves the dashboard as static files, not as a
runtime.

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
