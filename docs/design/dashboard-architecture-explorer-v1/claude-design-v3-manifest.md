# Claude Design v3 Manifest — Dashboard Architecture Explorer v1

Canonical design pack:

```text
docs/design/dashboard-platform-roadmap-v1/claude-design-v3/
```

This child plan owns the Architecture Explorer portions of the pack.

## Assets In Scope

- `dp-page-architecture.jsx`
  - Main Architecture & Flows visual specification.
  - Trust-boundary swimlanes: You, AI Agents, Plan, Execution,
    Cross-Model Audit, Human Gate, External Services.
  - Right rail with flow list and step inspector.
  - Numbered highlighted flow path.
  - Node type legend and provenance treatment.
- `dp-page-arch-variants.jsx`
  - Neutral/no-flow state.
  - Node click-detail state.
  - Stale-map banner state.
  - All Projects / fleet architecture cards.
  - Mobile architecture layout.
  - Module-category variant.
- `dp-shell.jsx`
  - Architecture nav entry and `active="arch"` convention.
  - Architecture worker must not restore old IA labels or Jarvis-era branding.
- `dp-icons.jsx`
  - Icon reference for Architecture, flows, warnings, commands, and status.
- `dp-tokens.css`
  - Token source for graph surfaces, panels, command chips, status pills, and
    responsive behavior.
- `DontPanic Dashboard.html`
  - Artboard index showing where Architecture variants sit in the design pack.
- `uploads/Screenshot 2026-05-23 at 11.04.02 PM.png`
  and `uploads/Screenshot 2026-05-23 at 11.04.13 PM.png`
  - Visual references for Architecture Explorer variants.

## Explicit Build Constraints

- F001 must not modify `dashboard/**`. It may use these design assets to shape
  view-model requirements, flow definitions, validation, and tests only.
- F002-F005 may implement the dashboard UI after IA shell cleanup lands or
  after explicit reconciliation with the IA copy map.
- Do not hardcode the demo arrays from the JSX into shipped runtime state.
  Runtime flows must come from architecture view-state, authored
  `docs/architecture/flows.json`, or validated derived data.
- Do not import JSX as runtime code.
- Keep the dashboard read-only and command-emitter only.

## Design Coverage Notes

The v3 design pack materially covers the Architecture plan's intended endstate:

- Architecture nav entry exists.
- Multiple flow variants are present.
- Authored/derived badges are represented.
- Missing-reference warning state is represented.
- Neutral/no-flow state is represented.
- Node-detail state is represented.
- Stale-map state is represented.
- Fleet architecture behavior is represented.
- Mobile behavior is represented.
- Zoom controls are represented in the mobile variant.

Remaining implementation responsibility:

- Convert visual flows into real `architecture-view-state` data.
- Validate authored/derived flow references.
- Implement deterministic layout from local architecture data.
- Add Playwright/snapshot evidence against the real dashboard.
