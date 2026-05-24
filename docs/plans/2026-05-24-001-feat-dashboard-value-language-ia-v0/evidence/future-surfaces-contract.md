# Future-Surface Inheritance Contract — F005

Plan: `2026-05-24-001-feat-dashboard-value-language-ia-v0`
Feature: F005 (dashboard documentation and objective closeout)

This document records exactly how the future dashboard surfaces deferred
from V0 must inherit the value-language contract delivered here. It is
referenced from `dashboard/README.md` and the V0 copy map at
[`docs/design/dashboard-value-language-ia-v0/copy-map.md`](../../../design/dashboard-value-language-ia-v0/copy-map.md).

## Deferred surfaces (V0 non-goals)

| Surface | V0 disposition | Owning child plan / pointer |
|---|---|---|
| Architecture Explorer | Muted future nav affordance only (D014). Must point at a regen command or plan id; no inline architecture renderer. | `docs/design/dashboard-architecture-explorer-v1/` (next child of parent roadmap `2026-05-24-003`) |
| Review / Evidence | Not in V0 nav. Auditor signoffs remain readable on disk under `docs/plans/<plan>/audit/`. | Future child plan under parent roadmap `2026-05-24-003` |
| Configuration editor | Not in V0. Preferences is browser-local only. DontPanic configuration is still edited through the `dontpanic` CLI surfaced in Tools & Setup. | Future child plan under parent roadmap `2026-05-24-003` |
| Agent Session Registry | Not in V0. `dontpanic ps` remains the supervisor-introspection seam. | Future child plan under parent roadmap `2026-05-24-003` |
| Local executor / inline approve | Permanent non-goal of V0. The command-emitter invariant must be preserved by every future surface; mutations stay in the operator's terminal. | (No child plan is needed; would require a roadmap-level lock) |

## Inheritance rules every future child plan MUST follow

1. **Value-first first-read.** Add the new surface's Layer-1 labels to
   the copy map at
   [`docs/design/dashboard-value-language-ia-v0/copy-map.md`](../../../design/dashboard-value-language-ia-v0/copy-map.md)
   **before** any implementer dispatch. Title, nav label, card
   headlines, and empty-state copy use plain operator/business language.
   Technical nouns (gate names, capability_ids, supervisor ids, plan_ids,
   feature_ids, file paths, exact CLI commands) live in metadata rows,
   detail sections, tooltips, source/provenance footers, and exact
   command chips — never in the first-read line.

2. **Static check coverage.** Extend
   `dashboard/lib/value-language-static-checks.js` with the new
   surface's Layer-1 selectors so the existing forbidden-first-read
   token scan (Vitest
   `dashboard/tests/unit/value-language-static-checks.test.js`) catches
   regressions automatically. Do not bypass the check with per-surface
   suppression lists.

3. **Status taxonomy reuse.** Use the existing four-band taxonomy
   (`needs_action`/`advisory`/`ready`/`quiet`). Render `optional` as a
   relevance chip on the same row, not as a fifth status colour. New
   bands are out of scope without a parent-roadmap decision.

4. **Provenance.** Render the source filename, last-updated timestamp,
   and refresh command through
   [`dashboard/lib/provenance.js`](../../../../dashboard/lib/provenance.js).
   Hand-rolled provenance lines are a regression — the helper is the
   contract.

5. **Command-emitter invariant.** Every operator-actionable affordance
   emits an exact CLI command into a copyable `<pre>` / `<code>` block.
   No in-page mutation, no inline approval, no embedded local executor,
   no Firebase realtime writes. Drag affordances are allowed only as
   non-mutating command previews (D010).

6. **Fleet mode.** Route through the existing project selector
   (`dashboard/lib/project-selector-logic.js`). `All Projects` and a
   specific-project view must both be coherent; cross-project blockers
   surface under the `__global__` band the fleet what-now renderer pins
   at the top.

7. **Design-asset boundary.** Treat any Claude Design v3 (or later)
   output as visual specification and design-token input. Keep the
   shipped dashboard vanilla HTML/CSS/JS (D012). A framework rewrite is
   explicitly out of scope for V0 and any direct successor.

## How this contract is enforced

- The copy map's "Forbidden first-read tokens" section is a
  machine-readable data source for the static check that fails CI on
  Jarvis-era or internal-first labels appearing in Layer 1.
- New child plans gate their `pre_impl` step on copy-map amendments and
  Layer-1 selector registration so the auditor can confirm the
  inheritance contract before the implementer runs.
- The dashboard README links to this contract from its V0 Value-Language
  Contract section, so a future implementer reading the dashboard repo
  cannot miss it.

## Operational note for the planning intelligence work

When the next child plan opens, the planner SHOULD:

- Cite [`docs/design/dashboard-value-language-ia-v0/copy-map.md`](../../../design/dashboard-value-language-ia-v0/copy-map.md)
  in its plan.md `## Boundaries / Design Translation` section.
- Land the copy-map amendment in the same PR series as the new surface's
  shell skeleton.
- Add static-check coverage **before** the surface's value-first labels
  ship so any drift is caught by the existing Vitest run.
