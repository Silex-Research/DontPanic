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
import fs from 'node:fs/promises';
import http from 'node:http';

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const DASHBOARD_ROOT = path.resolve(__dirname, '../../');
const EVIDENCE_DIR = path.resolve(
  __dirname,
  '../../../docs/plans/2026-05-24-002-feat-dashboard-architecture-explorer-v1/evidence/screenshots',
);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'text/javascript; charset=utf-8',
  '.mjs':  'text/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg':  'image/svg+xml',
  '.png':  'image/png',
};

let server;
let harnessURL;

function screenshotPath(name, projectName) {
  return path.join(EVIDENCE_DIR, `${name}-${projectName}.png`);
}

test.describe('F003 Architecture explorer screenshots', () => {
  test.beforeAll(async () => {
    server = http.createServer(async (req, res) => {
      try {
        const reqPath = decodeURIComponent(req.url.split('?')[0]);
        const rel = reqPath === '/' ? '/tests/playwright/architecture-harness.html' : reqPath;
        const filePath = path.join(DASHBOARD_ROOT, rel);
        if (!filePath.startsWith(DASHBOARD_ROOT)) {
          res.writeHead(403).end('forbidden');
          return;
        }
        const data = await fs.readFile(filePath);
        const ext = path.extname(filePath).toLowerCase();
        res.writeHead(200, { 'content-type': MIME[ext] || 'application/octet-stream' });
        res.end(data);
      } catch (e) {
        res.writeHead(404).end(String(e && e.message || e));
      }
    });
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', resolve);
    });
    harnessURL = `http://127.0.0.1:${server.address().port}/tests/playwright/architecture-harness.html`;
  });

  test.afterAll(async () => {
    if (!server) return;
    await new Promise((resolve) => server.close(resolve));
  });

  test('neutral state (no flow selected)', async ({ page }, testInfo) => {
    await page.goto(`${harnessURL}?variant=stale`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.waitForSelector('[data-explorer="1"]');
    await page.screenshot({
      path: screenshotPath('01-neutral', testInfo.project.name),
      fullPage: true,
    });
    await expect(page.locator('[data-canvas]')).toBeVisible();
  });

  test('selected-flow state (path highlighted, step inspector visible)', async ({ page }, testInfo) => {
    await page.goto(`${harnessURL}?variant=stale`);
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
    await page.goto(`${harnessURL}?variant=stale`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.locator('.arch-node').first().click();
    await page.waitForSelector('[data-detail-panel]:not([hidden])');
    await page.screenshot({
      path: screenshotPath('03-node-detail', testInfo.project.name),
      fullPage: true,
    });
  });

  test('filtered state (search narrowed)', async ({ page }, testInfo) => {
    await page.goto(`${harnessURL}?variant=stale`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.locator('[data-arch-search]').fill('supervisor');
    await page.waitForTimeout(150);
    await page.screenshot({
      path: screenshotPath('04-filtered', testInfo.project.name),
      fullPage: true,
    });
  });

  test('stale freshness banner (default fixture state)', async ({ page }, testInfo) => {
    await page.goto(`${harnessURL}?variant=stale`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.waitForSelector('[data-freshness="stale"]');
    await page.screenshot({
      path: screenshotPath('05-stale', testInfo.project.name),
      fullPage: true,
    });
  });

  test('absent/missing state (empty card with regen command)', async ({ page }, testInfo) => {
    await page.goto(`${harnessURL}?variant=absent`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.waitForSelector('[data-empty-state="missing"]');
    await page.screenshot({
      path: screenshotPath('06-absent', testInfo.project.name),
      fullPage: true,
    });
  });

  test('F004 responsive summary, insights, and fleet states do not overlap', async ({ page }, testInfo) => {
    await page.goto(`${harnessURL}?variant=f004`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.waitForSelector('[data-summary="1"]');
    await page.waitForSelector('[data-insights-detail="1"]');

    if (testInfo.project.name === 'mobile') {
      const layout = await page.evaluate(() => {
        const box = (selector) => {
          const el = document.querySelector(selector);
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return { top: r.top, bottom: r.bottom, left: r.left, right: r.right };
        };
        return {
          viewportWidth: window.innerWidth,
          scrollWidth: document.documentElement.scrollWidth,
          summary: box('[data-summary="1"]'),
          insights: box('[data-insights-detail="1"]'),
        };
      });
      expect(layout.summary).not.toBeNull();
      expect(layout.insights).not.toBeNull();
      expect(layout.scrollWidth).toBeLessThanOrEqual(layout.viewportWidth + 2);
      expect(layout.summary.bottom).toBeLessThanOrEqual(layout.insights.top + 2);
    }

    await page.goto(`${harnessURL}?variant=fleet`);
    await page.waitForFunction(() => window.__harnessReady === true);
    await page.waitForSelector('[data-fleet="1"]');
    await expect(page.locator('[data-fleet-card]')).toHaveCount(3);
    await expect(page.locator('[data-fleet-card="unbuilt"]')).toBeVisible();

    if (testInfo.project.name === 'mobile') {
      const fleetLayout = await page.evaluate(() => {
        const cards = Array.from(document.querySelectorAll('[data-fleet-card]'))
          .map((el) => {
            const r = el.getBoundingClientRect();
            return { top: r.top, bottom: r.bottom, left: r.left, right: r.right };
          });
        return {
          viewportWidth: window.innerWidth,
          scrollWidth: document.documentElement.scrollWidth,
          cards,
        };
      });
      expect(fleetLayout.scrollWidth).toBeLessThanOrEqual(fleetLayout.viewportWidth + 2);
      expect(fleetLayout.cards.length).toBe(3);
      expect(fleetLayout.cards[0].bottom).toBeLessThanOrEqual(fleetLayout.cards[1].top + 2);
      expect(fleetLayout.cards[1].bottom).toBeLessThanOrEqual(fleetLayout.cards[2].top + 2);
    }
  });
});
