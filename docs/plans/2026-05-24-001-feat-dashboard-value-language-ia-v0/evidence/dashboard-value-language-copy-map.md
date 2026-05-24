# Dashboard Value-Language Copy Map — objective-contract pointer

Plan: `2026-05-24-001-feat-dashboard-value-language-ia-v0`
Feature: F005 (dashboard documentation and objective closeout)

The canonical V0 copy map lives next to the design intake so future
plans can amend it as new surfaces land:

- [`docs/design/dashboard-value-language-ia-v0/copy-map.md`](../../../design/dashboard-value-language-ia-v0/copy-map.md)

This evidence file is the named-artifact pointer required by
`objective_contract.json -> required_evidence`. Co-locating the copy map
with the design assets keeps the contract close to the mockups it
governs and keeps the static check (`dashboard/lib/value-language-static-checks.js`,
`dashboard/tests/unit/value-language-static-checks.test.js`) in sync
with the single source of truth.

## What the copy map covers

- §1 Two-layer language rule (primary value labels + technical disclosure).
- §2 Surface-by-surface copy map for the nav shell, Needs Attention,
  Work, Tools & Setup, Health, Preferences, and deferred surfaces.
- §3 Four-band status taxonomy (`needs_action`/`advisory`/`ready`/`quiet`)
  and the separate `optional` relevance chip.
- §4 Cross-cutting rules: audience expansion, drag-to-command
  decision, JSX-to-vanilla translation, fleet-mode expectations,
  command-emitter invariant, source/provenance treatment, forbidden
  first-read tokens.

## Why this lives outside the plan directory

The plan directory is volatile by design — features close, evidence
turns over, the plan rolls into pre_merge. The copy map is a long-lived
contract that future child plans (Architecture Explorer, Review /
Evidence, Configuration, Agent Session Registry) must inherit. Keeping
it next to the design assets, with a pointer here, gives every audit
trail a single canonical URI without duplicating the document or risking
divergence between two copies.

The dashboard README links to the same file from
[`dashboard/README.md`](../../../../dashboard/README.md#v0-value-language-contract-plan-2026-05-24-001),
which is the source future implementers will read first.
