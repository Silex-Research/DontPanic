// Standalone Playwright screenshot capture for the F003 architecture
// explorer. Avoids @playwright/test's parallel worker plumbing, which
// fights the harness's sandbox boundary. Run with:
//   node tests/playwright/capture-screenshots.mjs
//
// Outputs PNGs to docs/plans/.../evidence/screenshots/<name>-<viewport>.png

import { chromium, devices } from 'playwright';
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

await fs.mkdir(EVIDENCE_DIR, { recursive: true });

// Minimal static file server so `fetch()` and ES module imports work
// (chromium blocks both from file:// URLs).
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'text/javascript; charset=utf-8',
  '.mjs':  'text/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg':  'image/svg+xml',
  '.png':  'image/png',
};
const server = http.createServer(async (req, res) => {
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
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;
const HARNESS = `http://127.0.0.1:${port}/tests/playwright/architecture-harness.html`;

const VIEWPORTS = [
  { name: 'desktop', viewport: { width: 1440, height: 900 }, isMobile: false },
  { name: 'mobile',  viewport: { width: 390, height: 844 },  isMobile: true,
    deviceScaleFactor: 3, userAgent: devices['iPhone 14 Pro'].userAgent },
];

const browser = await chromium.launch({ headless: true });
try {
  for (const vp of VIEWPORTS) {
    const ctx = await browser.newContext({
      viewport: vp.viewport,
      deviceScaleFactor: vp.deviceScaleFactor || 1,
      userAgent: vp.userAgent,
      isMobile: vp.isMobile,
    });
    const page = await ctx.newPage();
    page.on('console', (m) => console.log(`[${vp.name}/${m.type()}]`, m.text()));
    page.on('pageerror', (e) => console.log(`[${vp.name}/pageerror]`, e.message));

    async function go(variant) {
      const u = new URL(HARNESS);
      u.searchParams.set('variant', variant);
      await page.goto(u.toString(), { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => window.__harnessReady === true, { timeout: 10_000 });
    }
    async function snap(name) {
      const file = path.join(EVIDENCE_DIR, `${name}-${vp.name}.png`);
      await page.screenshot({ path: file, fullPage: true });
      console.log(`captured ${path.relative(process.cwd(), file)}`);
    }

    // 1. neutral
    await go('stale');
    await page.waitForSelector('[data-explorer="1"]');
    await snap('01-neutral');

    // 2. selected-flow
    await page.click('[data-arch-flow="flow:architecture-regen"]');
    await page.waitForTimeout(150);
    await snap('02-selected-flow');

    // 3. node-detail
    await go('stale');
    await page.waitForSelector('[data-explorer="1"]');
    await page.evaluate(() => {
      const n = document.querySelector('.arch-node');
      n.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await page.waitForSelector('[data-detail-panel]:not([hidden])', { timeout: 5_000 });
    await snap('03-node-detail');

    // 4. filtered (search)
    await go('stale');
    await page.waitForSelector('[data-explorer="1"]');
    await page.fill('[data-arch-search]', 'supervisor');
    await page.waitForTimeout(100);
    await snap('04-filtered');

    // 5. stale (default fixture state — pure neutral with stale banner visible)
    await go('stale');
    await page.waitForSelector('[data-freshness="stale"]');
    await snap('05-stale');

    // 6. absent / missing-state empty card
    await go('absent');
    await page.waitForSelector('[data-empty-state="missing"]');
    await snap('06-absent');

    await ctx.close();
  }
} finally {
  await browser.close();
  server.close();
}

console.log('all screenshots captured');
