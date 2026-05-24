# Dashboard Value-Language IA v0 Assets

This directory is the intake location for Claude Design output used by plan
`2026-05-24-001-feat-dashboard-value-language-ia-v0`, and the home of the
value-language copy contract that governs the V0 dashboard.

## Contents

- [`copy-map.md`](./copy-map.md) — the V0 dashboard value-language copy map.
  This is the canonical reference for first-read labels, technical
  disclosure rules, the four-band status taxonomy + optional relevance chip,
  the audience expansion, drag-to-command decision, JSX-to-vanilla
  translation strategy, fleet-mode expectations, identified Jarvis-era and
  internal-first labels, and the forbidden first-read token list.
- Claude Design assets (added on intake) — visual mockups, design tokens,
  component inventory, copy deck excerpts, empty-state examples, and
  implementation notes.
- [`claude-design-v3-manifest.md`](./claude-design-v3-manifest.md) — maps the
  roadmap-level Claude Design v3 pack to this child plan's implementation
  scope.

## Expected Claude Design assets

- dashboard shell mockups
- Needs Attention, Work, Tools & Setup, Health, and Preferences mockups
- design tokens
- component inventory
- copy deck or terminology map
- empty-state examples
- implementation notes for the existing static dashboard

When Claude Design output arrives, file it under this directory using the
following pattern (case-sensitive subdirectory names):

```
docs/design/dashboard-value-language-ia-v0/
├── README.md            (this file)
├── copy-map.md          (V0 copy contract — see above)
├── mockups/             (PNG/SVG/PDF visual specs per surface)
├── tokens/              (color/spacing/typography token tables)
├── components/          (per-primitive notes: command chips, status pills, …)
├── empty-states/        (missing-data screenshots and notes)
└── notes/               (implementation guidance / open questions)
```

Subdirectories are optional — create only the ones for which assets exist.
F005 records which assets were used and which were deferred.

Current roadmap-level pack:

```text
../dashboard-platform-roadmap-v1/claude-design-v3/
```

## Constraints

- Adapt the existing static dashboard; do not introduce a framework rewrite.
- Use value-first primary labels and keep technical DontPanic terms in
  secondary details (see [`copy-map.md`](./copy-map.md) §1).
- Preserve exact copyable commands and source/provenance metadata
  (see [`copy-map.md`](./copy-map.md) §4.6).
- Keep the dashboard read-only by default and command-emitter only.
- Drag affordances are allowed only as non-mutating command previews
  (see [`copy-map.md`](./copy-map.md) §4.2).
- Do not add Architecture, Review/Evidence, Configuration editor, browser
  terminals, local executor, or Firebase realtime controls in this V0.

## Decision pointers

The locked decisions for this plan live in
[`../../plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/decisions.jsonl`](../../plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/decisions.jsonl).
Relevant IDs:

- D001 — value-first primary labels with technical disclosure second
- D003 — keep four-band status taxonomy; render `optional` as a relevance chip
- D004 — V0 nav labels: Needs Attention, Work, Tools & Setup, Health, Preferences
- D005 — remove or hide demo/non-core surfaces from V0 core nav
- D006 — preserve the command-emitter invariant
- D007 — integrate Claude Design assets by adapting the existing static dashboard
- D008 — non-technical reviewer audience expansion
- D010 — drag-to-command as command-preview only; never mutate
- D011 — Home as route label, Needs Attention as first-viewport content
- D012 — JSX-to-vanilla translation; no framework runtime dependency
- D013 — fleet-mode variants required for Home, Work, and Health
- D014 — defer Architecture implementation; muted future nav affordance only
