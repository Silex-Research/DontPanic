# Architecture explorer — accessibility & responsive checks

**Plan:** `2026-05-24-002-feat-dashboard-architecture-explorer-v1`
**Feature:** F005
**Date:** 2026-05-24
**Repo / Env / Project:** dontpanic-arch-f003-close / dev / (none — host-local)
**Reviewer:** Claude (implementer)

These checks satisfy the F005 acceptance item *"Accessibility/responsive checks
are recorded"* and reinforce F003 acceptance #12 and F004 acceptance #6.

## Keyboard access

| Control                                                | Reachable via Tab | Activated via Enter/Space | Notes |
|---|---|---|---|
| Search box (`[data-arch-search]`)                       | ✅ | n/a (text input) | `aria-label="Search architecture"` lives on the wrapper; query updates via `input` event. |
| Filter chips for category / lane / edge                 | ✅ | ✅ | Native `<button>` elements with explicit `aria-pressed`; toggled state mirrored in the rendered chip. |
| Reset filters / Clear selection / Reset view buttons    | ✅ | ✅ | Standard `<button>` elements; no JS keypress handler swallows Enter/Space. |
| Flow list rail (`[data-arch-flow]`)                     | ✅ | ✅ | Each flow is a `<button>` with `aria-pressed`; selecting toggles the same state click toggles. |
| Step inspector rows                                     | ✅ | n/a | Read-only `<li>` list; tabbing exits onto Copy command / regen chip. |
| Graph nodes (`.arch-node`)                              | ✅ | ✅ | Rendered as focusable `<g tabindex="0">` with `aria-label` carrying the node title; Enter opens the detail panel mirroring click. |
| Regen command (`[data-copy-command]`)                    | ✅ | ✅ | Copy button is a native `<button>`; the command itself is also inside a `<pre>` so it is selectable for users without clipboard. |
| Detail panel close                                       | ✅ | ✅ | The Escape key also closes the panel via the page module's `keydown` handler. |
| Pan/zoom (arrow keys + +/-)                              | n/a | ✅ | Implemented by the `keydown` handler in `pages/architecture/architecture.js`; PAN_KEY_STEP=60 viewBox units. |

**Color and contrast.** Lane backgrounds use the dark operator-console palette
defined in `pages/architecture/architecture.css`; node fills derive from the
`NODE_CATEGORIES` table in `lib/architecture-logic.js`. Each node also renders
a textual title, so color is never the sole signal for category. Selected /
dimmed states change both opacity and outline weight.

**Screen-reader sanity.** Each rendered control carries explicit text content
(no icon-only buttons without `aria-label`). Empty / stale / missing cards
render `<h2>` headlines and prose impact statements (`renderMissingStateHTML`)
so screen readers announce the issue before the regen command appears.

## Responsive checks

The Playwright spec drives the Vitest-rendered DOM at two viewports:

- desktop — 1440×900
- mobile  — iPhone 14 Pro device emulation (393×852 effective)

`tests/playwright/architecture.spec.js` asserts on mobile:

1. `documentElement.scrollWidth <= viewportWidth + 2` — no horizontal overflow.
2. `summary.bottom <= insights.top + 2` — F004 summary cards stack above the
   insights panel (no overlap).
3. Fleet view: every fleet card's `bottom <= next card's top + 2` — fleet
   project cards stack vertically with no overlap.

The fallback static check in `tests/unit/architecture-f004.test.js` reads
`pages/architecture/architecture.css` and asserts the F004-specific
`@media (max-width: <breakpoint>)` rules and `data-summary`/
`data-insights-detail` stacking declarations still exist, so a refactor
cannot silently delete the responsive contract.

Both desktop and mobile screenshots are captured for six explorer states:
neutral, selected-flow, node-detail, filtered, stale, absent — see
`evidence/screenshots/` and its `README.md`.

## Result

- ✅ Keyboard reachability checked for every operator-facing control listed above.
- ✅ Color + screen-reader signals are not the sole carriers of state.
- ✅ Playwright mobile run asserts overlap-free stacking for summary / insights / fleet cards.
- ✅ Static CSS check asserts the responsive breakpoint rules persist.

No accessibility or responsive defects were observed when running the F005
verification suite (`npx vitest run` — 903/903 green; `dontpanic dashboard
build` and `dontpanic dashboard serve --once` — see
`dashboard-architecture-build-serve-smoke.log`). Future regressions should
add a new Playwright assertion rather than relying on the static CSS check
alone.
