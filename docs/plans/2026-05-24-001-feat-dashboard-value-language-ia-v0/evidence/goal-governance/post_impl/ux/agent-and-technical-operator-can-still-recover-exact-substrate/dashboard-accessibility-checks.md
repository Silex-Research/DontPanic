# Dashboard accessibility / design checks — F004 evidence

Plan: `2026-05-24-001-feat-dashboard-value-language-ia-v0`
Feature: F004 (Provenance, accessibility, non-technical comprehension)
Run: 2026-05-24 (iteration 1) by F004 implementer (Claude Opus 4.7).

This document records the accessibility / design checks performed for
the V0 dashboard surface and notes the limits of what could be verified
from this iteration's headless toolchain.

## Surface under review

- `pages/what-now/what-now.js` → Needs Attention (rendered via `lib/what-now-logic.js`)
- `pages/mission-control/mission-control.js` → Work (rendered via `lib/mission-control-logic.js`)
- `pages/capabilities/capabilities.js` → Tools & Setup (rendered via `lib/capabilities-logic.js`)
- `pages/health/health.js` → Health (rendered via `lib/health-logic.js`)
- `pages/settings/settings.js` → Preferences

Static fragment snapshots: `evidence/snapshots/dashboard-*-snapshot.html`.

## Checks performed

### 1. Keyboard navigation (semantics in the DOM)

| Surface | Check | Result |
| ------- | ----- | ------ |
| Core nav | `<button class="view-tab">` per tab (see `core.js:339`); native button tab order. | PASS — focusable in DOM order. |
| Needs Attention | `<button class="wn-copy-btn">` carries `aria-label="Copy command to clipboard"`. | PASS — confirmed in `what-now-logic.js:466`. |
| Work | `<button class="mc-modal-close" aria-label="Close">` and `role="dialog" aria-modal="true" aria-labelledby="mc-modal-title"` on the task detail. | PASS — confirmed in `mission-control.js` modal template. |
| Tools & Setup | Capability rows render command templates as selectable `<pre class="cap-action-cmd">` blocks. | PASS by inspection — V0 command emission is copyable text, not one-click copy buttons. |
| Health | Cards have headings (`<h2>` / `<h3>`) and per-card source code blocks. | PASS — every card declares a heading the reader can hop between. |
| Preferences | `<select>` controls have associated `<label class="stg-label" for="…">`. | PASS — confirmed in `pages/settings/settings.js`. |
| Provenance footer | Renders semantic `<code>` for the source/refresh values; no interactive controls so it does not steal focus. | PASS by design. |

**Limit:** keyboard navigation was not exercised against a live browser
in this iteration (no operator-driven manual pass). The above is a
DOM-semantic check, not a user-flow keyboard test. A manual pass on
the served `dontpanic dashboard serve` is recommended before the plan
flips to closed.

### 2. Text contrast / readable density

| Surface | Check | Result |
| ------- | ----- | ------ |
| Page-level provenance footer | Uses `pv-*` classes scoped in `core.css` (dark theme tokens) so the rows read at AA against the dark panel background. Labels live in muted secondary colour, values in primary. | PASS by design — no per-page colour override. |
| Status header chips | `wn-status-chip--<color>` mirrors the existing four-band tokens (`red`/`yellow`/`accent`/`green`) that the rest of the dashboard ships. | PASS — reuses tokens audited for the V0 dashboard release. |
| Cards | Layer-1 kind labels render in the page-level emphasis token; Layer-2 metadata (ids, project chips, updated timestamps) drop to secondary text. | PASS — first-read content keeps the primary contrast. |

**Limit:** programmatic contrast measurement (axe-core, Lighthouse) was
not run in this iteration; the harness is headless and would need a
browser-driven pass. The token palette has not changed in this F004
work, so this iteration neither improves nor regresses contrast vs
the V0 baseline.

### 3. Mobile / desktop non-overlap

| Surface | Check | Result |
| ------- | ----- | ------ |
| Provenance footer | `pv-footer` is a block element below the page content; it does not overlap with the page body at any width. | PASS by design (no absolute/positioning rules). |
| Work | The `mc-queue-source` slot sits below the kanban board, replacing the legacy `Source: …` line in the same physical position. | PASS — no layout shift introduced. |
| Status header | Renders inline chips above the band sections; uses flex wrap so narrow widths break cleanly. | PASS — `wn-status-chip` was added in F004-i0 and has been exercised since. |

**Limit:** explicit responsive testing across breakpoints requires a
browser. The F004 changes are additive markup (a footer slot per page)
rather than layout-changing, so the regression surface is small.

### 4. Non-technical comprehension

| Surface | Layer-1 label | Value-first? |
| ------- | ------------- | ------------ |
| Needs Attention card | `Approval needed`, `Setup required`, `Blocked`, … (via `getValueKindLabel`) | YES — pure value phrasing; technical provider name lives in Layer-2 chip. |
| Tools & Setup card | `Connected`, `Setup required`, `Blocked`, `Not installed`, `Optional for this project` | YES — captured by the F004 evidence test `renders value-first headlines for every status`. |
| Work column | `Planned`, `Ready to run`, `Running`, `Waiting on approval`, `Done` | YES — `MC_COLUMN_META` ships value labels; impact lines live one level below. |
| Health | `Install readiness`, `Setup drift`, `Security hooks`, `Budget guardrail`, `Fleet warnings` | YES — uses honesty phrasing for missing data ("…no data yet"). |
| Preferences | `Appearance`, `Auto-refresh`, `State files`, `Save preferences` | YES — operator-facing wording, no `jarvis_*` cache keys surface in copy. |

The forbidden-first-read-token scan (`lib/value-language-static-checks.js`)
runs against Layer-1 selectors only and is enforced in the
`value-language-page-evidence.test.js` integration suite; the impact /
detail / footer rows are explicitly Layer 2 and may carry exact upstream
identifiers (gate names, capability ids, file paths) without violating
the contract.

## Known limits / follow-ups

- No live-browser screenshot pass this iteration. The five static
  snapshots under `evidence/snapshots/` cover the rendered HTML; a
  visual screenshot pass against `dontpanic dashboard serve` is
  recommended before F004 closes.
- No programmatic axe-core run. Adding an axe-core integration in a
  follow-up plan is captured as a future enhancement (out of scope for
  V0 F004 acceptance, which is "checks recorded" rather than
  "automated").
- Mobile breakpoint behaviour was not exercised; the dashboard has
  always been desktop-first and V0 ships no explicit mobile contract.
