# F003 Architecture explorer screenshot evidence

Capture script: `dashboard/tests/playwright/capture-screenshots.mjs`
Harness: `dashboard/tests/playwright/architecture-harness.html`
Run from the dashboard dir: `node tests/playwright/capture-screenshots.mjs`

The harness boots `pages/architecture/architecture.js` against the
`tests/fixtures/architecture-view-state.json` view-state envelope and
drives interactions deterministically. The script captures both
desktop (1440×900) and mobile (iPhone 14 Pro device emulation) for
each of the six required F003 states:

| # | State | Desktop | Mobile |
|---|---|---|---|
| 01 | Neutral (no flow selected) | `01-neutral-desktop.png` | `01-neutral-mobile.png` |
| 02 | Selected flow + step markers | `02-selected-flow-desktop.png` | `02-selected-flow-mobile.png` |
| 03 | Click-to-detail panel open | `03-node-detail-desktop.png` | `03-node-detail-mobile.png` |
| 04 | Filtered (search="supervisor") | `04-filtered-desktop.png` | `04-filtered-mobile.png` |
| 05 | Stale freshness banner | `05-stale-desktop.png` | `05-stale-mobile.png` |
| 06 | Absent / missing-state card | `06-absent-desktop.png` | `06-absent-mobile.png` |

These satisfy F003 acceptance #12 (Playwright screenshots prove the
tab is non-blank, framed correctly, and usable on desktop/mobile).
