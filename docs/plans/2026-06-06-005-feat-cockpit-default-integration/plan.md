---
id: 2026-06-06-005-feat-cockpit-default-integration
title: Cockpit default integration — make the redesigned Cockpit the dashboard, on real state
type: feat
tier: cross-cutting
status: active
date: "2026-06-06"
goal_type: new_feature
description: >
  Ship the operator-console redesign (plan 2026-06-06-004) by making the redesigned Cockpit the
  DEFAULT landing surface, rendered from live operator-triage/v0 state — the smallest version
  where "the redesign IS the dashboard" is true. Deliberately narrow: mount + prove parity on
  real state before reshaping anything else. NOT in scope (deferred to 006/007/008): Repair +
  What-Now dissolution (IA/product change), the Architecture map renderer, terminal-dock chrome,
  legacy-page theming, and the full multi-surface state matrix. Old tabs stay until Cockpit
  proves parity. Per operator review: the redesign should ship by becoming the default Cockpit
  first; don't retire or reshape the rest of the dashboard until that path is proven on real state.
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
---

## Why this scope
The redesign substrate (schema, tokens, components, arch generator) is built + audited (2026-06-06-004).
What's missing to ship is INTEGRATION, not invention. But I1-I8 as one push mixes eight risk
profiles; the failure mode is a "mostly-integrated" dashboard. This plan does only the critical
path to a default Cockpit on real state, behind the existing shell, keeping all old tabs.

## Features
- **F001 build/state contract** — a rebuild writes a fresh operator-triage.json carrying the four
  F001 fields (resolution, asserted_at, freshness_basis, provenance_source); pin the serve-path so
  the served state is the freshly-built one; if architecture levels are emitted, CACHE-ONLY (never
  touch tracked repos — consistent with 2026-06-06-003 F001).
- **F002 Cockpit default mount** — an Operator/Cockpit page module (via Jarvis.registerPage) renders
  renderQueue + the inspect panel from live operator-triage.json, and is the LANDING surface. Old
  tabs remain registered.
- **F003 real-state journey** — real build → real shell → default Cockpit visible; assert the
  queue count, no raw JSON leak, freshness basis rendered honestly (hollow when not item_probe),
  resolution intents present; anti-synthetic negative: stale/missing triage → honest error/fallback.
- **F004 Cockpit state matrix** — loading / missing / stale / corrupt-or-error for the Cockpit ONLY
  (not every legacy page).

## Sequence
F001 (data contract) → F002 (mount) → F004 (states) → F003 (journey proves the whole path).
