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
    // Render against a file:// harness — the dashboard is static and
    // the screenshot rig boots the page module from the local files.
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'mobile',
      use: { ...devices['iPhone 14 Pro'] },
    },
  ],
});
