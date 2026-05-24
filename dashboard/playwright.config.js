// Playwright config — F003 architecture explorer screenshot evidence.
// Run: `npx playwright test --config=playwright.config.js`
// Output: docs/plans/2026-05-24-002-feat-dashboard-architecture-explorer-v1/evidence/screenshots/

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/playwright',
  fullyParallel: false,
  reporter: [['list']],
  use: {
    headless: true,
    viewport: { width: 1440, height: 900 },
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    // The spec serves a static harness over localhost so ES modules and
    // fetch() behave like they do under the dashboard server.
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'mobile',
      use: {
        ...devices['iPhone 14 Pro'],
        browserName: 'chromium',
      },
    },
  ],
});
