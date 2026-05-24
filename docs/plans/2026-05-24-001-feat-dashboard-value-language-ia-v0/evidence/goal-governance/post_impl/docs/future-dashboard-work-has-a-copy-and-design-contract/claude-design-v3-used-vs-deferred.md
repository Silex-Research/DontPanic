# Claude Design v3 — Used vs Deferred

Plan: `2026-05-24-001-feat-dashboard-value-language-ia-v0`
Feature: F005 (dashboard documentation and objective closeout)

Records which Claude Design v3 pack assets the V0 IA implementation
actually pulled in, which were treated as visual specification only,
and which were intentionally deferred to follow-on plans. Manifest:
[`docs/design/dashboard-value-language-ia-v0/claude-design-v3-manifest.md`](../../../design/dashboard-value-language-ia-v0/claude-design-v3-manifest.md).

The implementation rule for the whole pack (D012) is that JSX is
**visual specification only**. The shipped dashboard stays vanilla
HTML/CSS/JS, so "used" below means "the visual / copy / token decision
was ported into the static implementation," not "the JSX was imported
at runtime."

## Used in V0

| Asset | How it landed |
|---|---|
| `dp-shell.jsx` | Nav layout + V0 surface table drove F002 (`dashboard/index.html`, `dashboard/core.js`) and the `dashboard-core-nav-snapshot.html` evidence. `Active reviews` language and the V0 nav labels (Needs Attention, Work, Tools & Setup, Health, Preferences) came from this asset. |
| `dp-tokens.css` | Source for the dark operator-console palette, spacing, typography, command-chip / badge / panel / drawer treatments now backing `dashboard/core.css` and the per-page CSS in `pages/*/`. |
| `dp-page-home.jsx` | Drove the first-viewport Needs Attention language, the setup-needed copy, the recommendation card pattern, and the provenance footer placement now rendered by `dashboard/lib/what-now-logic.js`. Snapshot evidence: `dashboard-needs-attention-snapshot.html`. |
| `dp-page-work.jsx` | Drove the read-only Work layout in `dashboard/lib/mission-control-logic.js` and the F004 provenance row appended by `renderWorkProvenanceHTML`. |
| `dp-page-caps.jsx` | Drove the Tools & Setup framing in `dashboard/lib/capabilities-logic.js`. Snapshot evidence: `dashboard-tools-setup-snapshot.html`. |
| `dp-page-health.jsx` | Drove the Health honesty surface — missing-data states, per-card source rows, fleet warnings card — in `dashboard/lib/health-logic.js`. Snapshot evidence: `dashboard-health-empty-state-snapshot.html` and `dashboard-fleet-health-snapshot.html`. |
| `dp-page-prefs.jsx` | Drove the Preferences-as-browser-local framing in `dashboard/pages/settings/settings.js`, plus the explicit "no DontPanic config writes" disclosure. Snapshot evidence: `dashboard-preferences-snapshot.html`. |
| `dp-page-fleet.jsx` | Drove the All Projects grouping patterns now rendered by `renderFleetWhatNowHTML` and the project-selector summary. Snapshot evidence: `dashboard-fleet-home-snapshot.html`. |
| `dp-page-plain.jsx` | Drove the non-technical wording, glossary, and Layer-1 value-first phrasing now encoded in [`copy-map.md`](../../../design/dashboard-value-language-ia-v0/copy-map.md) and enforced by `dashboard/lib/value-language-static-checks.js`. |
| `dp-page-docs.jsx` | Drove the empty-state patterns, the provenance treatment, and the explicit drag/drop guidance now reflected in `dashboard/lib/provenance.js` and the F004 accessibility checks. |

## Treated as visual specification, not runtime

`dp-shell.jsx`, `dp-page-work-board.jsx`, and the JSX page modules above
were never imported. Their command-emitter affordances were ported by
hand into the vanilla DOM helpers under `dashboard/lib/`. Drag-to-command
specifically followed D010 — preview-only, no mutation, and the F003
implementation reused that decision when rendering Work and Needs
Attention command chips.

## Deferred from V0

| Asset | Deferred to |
|---|---|
| `dp-page-architecture.jsx` and `dp-page-arch-variants.jsx` | Architecture Explorer child plan under parent roadmap `2026-05-24-003`. V0 only adds a muted future-affordance pointer per D014; the interactive renderer ships separately. See [`future-surfaces-contract.md`](./future-surfaces-contract.md). |
| `dp-page-work-board.jsx` (drag-to-mutate variant) | Permanently deferred — D010 locks drag affordances to command-preview only. Drag-to-mutate is incompatible with the command-emitter invariant. |
| `uploads/FinalDontPanic.png` | Product/social visual reference only; not loaded as a runtime asset. Reserved for marketing/docs use under a future docs plan if needed. |
| `design-canvas.jsx` / `dp-icons.jsx` (Storybook-style canvases) | Used as inspection-only artifacts in design review; not ported to runtime. Re-evaluate during the Architecture Explorer plan if its component set diverges. |

## Why these splits matter for future plans

The next child plans (Architecture Explorer, Review/Evidence,
Configuration editor, Agent Session Registry) inherit the pack's
visual identity through `dashboard/core.css` and the design-token CSS
extracted from `dp-tokens.css`. They MUST NOT take a runtime
dependency on the JSX assets or re-introduce a framework rewrite. The
[`future-surfaces-contract.md`](./future-surfaces-contract.md)
companion document spells out the inheritance rules.
