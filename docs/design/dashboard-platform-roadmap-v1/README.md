# Dashboard Platform Roadmap v1 Design Intake

This directory stores roadmap-level design packs that span more than one
dashboard child plan.

## Claude Design v3

Location:

```text
docs/design/dashboard-platform-roadmap-v1/claude-design-v3/
```

Source:

```text
/Users/bayesian/Downloads/DontPanic-3.zip
```

This pack is non-runtime design intake. Do not import React/JSX files directly
into the shipped dashboard. Implementation should port tokens, layout patterns,
copy, and small component behavior into the existing static dashboard runtime.

## Child Plan Ownership

- `2026-05-24-001-feat-dashboard-value-language-ia-v0` consumes shell,
  copy, token, Home, Work, Tools & Setup, Health, Preferences, empty-state, and
  fleet assets.
- `2026-05-24-002-feat-dashboard-architecture-explorer-v1` consumes
  Architecture, Architecture variants, flow-map, node-detail, stale/missing,
  fleet, mobile, and graph interaction assets.

Per-child manifests live in:

- `../dashboard-value-language-ia-v0/claude-design-v3-manifest.md`
- `../dashboard-architecture-explorer-v1/claude-design-v3-manifest.md`
