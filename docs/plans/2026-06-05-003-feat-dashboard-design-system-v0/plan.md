---
id: 2026-06-05-003-feat-dashboard-design-system-v0
title: Dashboard design system v0 — shared component layer + Repair worked example
type: feat
tier: cross-cutting
status: draft
date: "2026-06-05"
goal_type: new_feature
description: >
  The 2026-06-05 UX audit (docs/dashboard-ux-audit-2026-06-05.md) found the operator
  console is not just inconsistent but structurally incomplete: there is no shared
  component layer below .panel/.status-badge/.empty-state, so every tab reinvents
  cards/badges/buttons (~110 bespoke classes on Architecture alone); several tabs
  render UNSTYLED markup because classes are emitted by JS with no CSS rule anywhere
  (Repair has no stylesheet at all; settings' sr-* skill-recs, ~13 capabilities
  card-body classes, what-now + health Global-tools blocks); action affordances are
  dishonest or absent (Repair's "Repair automatically" copies a command; capabilities
  has no copy button); there are no loading/error states; tokens leak (32 hardcoded
  hex across page CSS) with no spacing or type scale; and 4 orphan pages bleed CSS
  onto the live pages. This plan builds the FOUNDATION (tokens + scales + shared
  component layer + page skeleton), proves it on the worst tab (Repair) end to end,
  adds the conformance checks that would have caught the unstyled-class bug class, and
  retires the orphan pages. The standard it implements is docs/dashboard-design-system.md.
  Per-tab migration of the other six tabs is an explicit, demand-gated follow-on — this
  plan does not boil the ocean.
---

# Dashboard design system v0

## Why now
The audit's seven systemic failures all trace to one root cause: **no shared component
system**. You cannot make seven tabs consistent by editing seven bespoke CSS files; you
make them consistent by giving them one set of primitives and a page skeleton, then
migrating onto it. This plan ships that substrate + the first migrated tab + the guard
rails, so subsequent per-tab migration is mechanical and safe.

## Scope boundary
- IN: token foundation (semantic color aliases + NEW spacing/type scales); the shared
  component layer (Button, CopyCommand with copied/failed states, Card, StatTile +
  StatStrip, SectionHeader, Banner, Skeleton) + render helpers; the `renderPage()`
  skeleton + shell hardening (`<main>`, skip-link, `:focus-visible`, nav reorder);
  **Repair fully migrated as the worked example**; the "no unstyled emitted class" +
  "token-only values" conformance checks; retiring the 4 orphan pages.
- OUT (demand-gated follow-on, one slice per tab): migrating Work / Architecture /
  Capabilities / Health / Needs Attention / Preferences onto the component layer. Each
  is its own plan slice, gated by the same conformance checks + a per-tab journey test.
- OUT (deferred): visual-regression/screenshot testing, responsive/mobile breakpoints,
  full light-theme, motion system beyond the copied-flash + skeleton shimmer.

## Verification posture (per docs/qa-sufficiency-contract.md)
This is a read-only-UI surface. Every feature names its **entering-surface proof** — a
real-state→real-shell Vitest journey assertion (extending dashboard-journey.test.js),
not a render-helper snapshot. Component primitives also get isolated unit tests. The
branch stays unmerged; pre_merge is the human gate.

## Decision log
See decisions.jsonl.

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal: the local dashboard's shared component layer + Repair worked
example + conformance checks + orphan retirement. No external services; no production
deploy. Read-only-UI surface verified by the real-state→real-shell journey harness.
