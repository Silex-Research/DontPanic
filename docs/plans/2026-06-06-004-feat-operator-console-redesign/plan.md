---
id: 2026-06-06-004-feat-operator-console-redesign
title: Operator console redesign — control tower over a log viewer
type: feat
tier: cross-cutting
status: active
date: "2026-06-06"
goal_type: new_feature
description: >
  Implement docs/design/operator-console-redesign.md as a phased, governed build — not a
  one-pass rewrite. Reframe the console from a flat monospace log into a calm, decision-first
  control tower: triaged "what needs me", visible trust (render-truth via freshness), and
  resolution affordances over copy-command homework. Non-negotiables from the spec: agent
  parity (every visual element maps to a real operator-triage/v0 field — no UI-only state),
  render-truth (never show confident unless a field proves it; stale = visibly demoted), one
  semantic token set themed via data-theme + data-density, and the terminal OFF by default with
  an unmistakable armed (red hazard) state. Schema gaps (F001) and the visual-token layer (F002)
  gate everything else. Decisions locked: additive-extend operator-triage/v0; audit F001 alone
  then batch F002-F005 and F006-F008; Architecture under Work; pause for human review after F001.
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
---

## Source of truth
`docs/design/operator-console-redesign.md` (§1 IA · §2 visual system · §3 the atom · §4 scope ·
§5 journeys · §6 state matrix · §7 agent parity + schema gaps · §8 a11y/density · §9 navigable
architecture · §10 phasing). Each feature below = one phase from §10, sequenced by dependency.

## Features (sequence + dependencies)
- **F001 schema gaps** (§7) — additive v0: `resolution[]`, `asserted_at`, `proven_live`,
  `provenance_source`. Gates F003 (resolution affordances) + F007 (freshness). SCHEMA-CLASS:
  human-gated; pause after.
- **F002 tokens** (§2, phase 1) — semantic token set, Inter/JetBrains, light+dark,
  data-density. Independent foundation; gates all visual phases.
- **F003 the atom** (§3) — comfort card + dense row + "you're clear"; resolution over
  copy-command. Needs F001 + F002.
- **F004 cockpit merge** (§1.2, J1/J3) — fold NEEDS ATTENTION into Cockpit; dock terminal;
  inspect-why panel. Needs F002 + F003.
- **F005 gate + dock** (J2, J4, §5.5) — approve/resume flow + side-by-side armed terminal.
  Needs F003 + F004.
- **F006 domain regroup** (§1) — 8 tabs → Cockpit/Work/System; dissolve Repair into the queue;
  Architecture under Work. Needs F004.
- **F007 freshness everywhere** (§2.2, §6) — filled/hollow dot grammar + desaturation. Needs F001.
- **F008 navigable architecture** (§9) — per-level Mermaid to docs/architecture/levels/*.mmd from
  architecture.json; C4 breadcrumb zoom; per-node drift coloring from source_fingerprint;
  regenerated on the commit hook. Needs F007 for drift coloring; structure can start in parallel.
