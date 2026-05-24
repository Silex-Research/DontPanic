# Dashboard Architecture Explorer v1 Assets

This directory is the intake location for design assets supporting plan
`2026-05-24-002-feat-dashboard-architecture-explorer-v1`.

The current Claude Design v3 pack is stored once at:

```text
../dashboard-platform-roadmap-v1/claude-design-v3/
```

This plan's asset map is:

```text
./claude-design-v3-manifest.md
```

Target design:

- interactive architecture flow map / system map
- swimlanes for system areas such as actors, client surfaces, runtime,
  evidence/data, capabilities/adapters, and external services
- nodes for modules, plans, capabilities, and surfaces where data exists
- typed relationship edges
- selectable flow list
- highlighted active-flow path
- numbered path steps
- right-side step inspector
- persistent legend
- dimmed non-selected paths
- clear-selection state
- scrollable step list
- search, filters, hover labels, click-to-detail side panel
- stale/missing architecture empty states
- project/fleet architecture context
- exact command-emitter pattern for `dontpanic architecture regen --with-html`
- source/provenance treatment consistent with the dashboard value-language IA

Constraints:

- Use existing `architecture.json` as source of truth.
- Do not design an auto-regenerating dashboard mutation.
- Do not require Firebase, hosted services, or CDN assets.
- Keep technical identifiers visible in details, not as the first-read layer.
- Design should be implementable in the existing static dashboard runtime.
