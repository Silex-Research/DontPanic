// Playwright screenshot evidence for the F003 architecture explorer.
//
// Each capture writes to:
//   docs/plans/2026-05-24-002-feat-dashboard-architecture-explorer-v1/evidence/screenshots/<name>-<project>.png
//
// Runs against `tests/playwright/architecture-harness.html` — a static
// harness that loads the architecture-view-state fixture and boots the
// real `pages/architecture/architecture.js` module.

import { test, expect } from '@playwright/test';
import path from 'node:path';
import url from 'node:url';

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const HARNESS = url.pathToFileURL(path.resolve(__dirname, 'architecture-harness.html')).toString();
const EVIDENCE_DIR = path.resolve(
  __dirname,
  '../../../docs/plans/2026-05-24-002-feat-dashboard-architecture-explorer-v1/evidence/screenshots',
);

function screenshotPath(name, projectName) {
  return path.join(EVIDENCE_DIR, `${name}-${projectName}.png`);
}

test.describe('F003 Architecture explorer screenshots', () => {
  test('neutral state (no flow selected)', async ({ page }, testInfo) => {
    await page.goto(`${HARNESS}?variant=stale`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.waitForSelector('[data-explorer="1"]');
    await page.screenshot({
      path: screenshotPath('01-neutral', testInfo.project.name),
      fullPage: true,
    });
    await expect(page.locator('[data-canvas]')).toBeVisible();
  });

  test('selected-flow state (path highlighted, step inspector visible)', async ({ page }, testInfo) => {
    await page.goto(`${HARNESS}?variant=stale`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.locator('[data-arch-flow="flow:architecture-regen"]').click();
    await page.waitForTimeout(150); // let the DOM settle after selection
    await page.screenshot({
      path: screenshotPath('02-selected-flow', testInfo.project.name),
      fullPage: true,
    });
    await expect(page.locator('.arch-node.is-selected')).toHaveCount(2);
    await expect(page.locator('[data-step-inspector]')).toBeVisible();
  });

  test('node-detail state (click-to-detail panel open)', async ({ page }, testInfo) => {
    await page.goto(`${HARNESS}?variant=stale`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.locator('.arch-node').first().click();
    await page.waitForSelector('[data-detail-panel]:not([hidden])');
    await page.screenshot({
      path: screenshotPath('03-node-detail', testInfo.project.name),
      fullPage: true,
    });
  });

  test('filtered state (search narrowed)', async ({ page }, testInfo) => {
    await page.goto(`${HARNESS}?variant=stale`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.locator('[data-arch-search]').fill('supervisor');
    await page.waitForTimeout(150);
    await page.screenshot({
      path: screenshotPath('04-filtered', testInfo.project.name),
      fullPage: true,
    });
  });

  test('stale freshness banner (default fixture state)', async ({ page }, testInfo) => {
    await page.goto(`${HARNESS}?variant=stale`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.waitForSelector('[data-freshness="stale"]');
    await page.screenshot({
      path: screenshotPath('05-stale', testInfo.project.name),
      fullPage: true,
    });
  });

  test('absent/missing state (empty card with regen command)', async ({ page }, testInfo) => {
    await page.goto(`${HARNESS}?variant=absent`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.waitForSelector('[data-empty-state="missing"]');
    await page.screenshot({
      path: screenshotPath('06-absent', testInfo.project.name),
      fullPage: true,
    });
  });
});
